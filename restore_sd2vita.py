#!/usr/bin/env python3
"""Copy a backup folder onto a mounted SD2Vita card, replacing matching files."""

import argparse
import hashlib
import os
import plistlib
import subprocess
import sys
import tempfile

BUFFER = 1024 * 1024


def card_info(path):
    root = os.path.realpath(path)
    if not os.path.isdir(root) or not os.path.ismount(root) or root == "/":
        raise ValueError("Card path must be the root of a mounted card volume.")
    details = plistlib.loads(subprocess.check_output(
        ["/usr/sbin/diskutil", "info", "-plist", root]))
    if (os.path.realpath(details.get("MountPoint", "")) != root or
            str(details.get("FilesystemType", "")).lower() != "exfat"):
        raise ValueError("Destination must be a mounted exFAT card volume.")
    disk_id = (details.get("DeviceIdentifier") if details.get("WholeDisk")
               else details.get("ParentWholeDisk", ""))
    if not isinstance(disk_id, str) or not disk_id.startswith("disk"):
        raise ValueError("Cannot identify the card's physical disk.")
    disk = plistlib.loads(subprocess.check_output(
        ["/usr/sbin/diskutil", "info", "-plist", "/dev/" + disk_id]))
    removable = bool(disk.get("RemovableMedia") or disk.get("Removable"))
    external = not disk.get("Internal", True) and bool(
        disk.get("Ejectable") or disk.get("RemovableMediaOrExternalDevice") or removable)
    built_in_sd = (disk.get("Internal", True) and removable and
                   str(disk.get("BusProtocol", "")).lower() == "secure digital")
    if (disk.get("DeviceIdentifier") != disk_id or not disk.get("WholeDisk") or
            disk.get("OSInternalMedia") or disk.get("VirtualOrPhysical") != "Physical" or
            not disk.get("WritableMedia") or not (external or built_in_sd)):
        raise ValueError("Destination is not a writable physical removable card.")
    return root


def files_under(source):
    items = []
    def walk(folder, relative=""):
        with os.scandir(folder) as children:
            for entry in children:
                rel = os.path.join(relative, entry.name)
                if entry.is_symlink():
                    raise ValueError(f"Symbolic link is unsupported: {rel}")
                if entry.is_dir(follow_symlinks=False):
                    items.append((rel, True, 0))
                    walk(entry.path, rel)
                elif entry.is_file(follow_symlinks=False):
                    items.append((rel, False, entry.stat(follow_symlinks=False).st_size))
                else:
                    raise ValueError(f"Unsupported backup item: {rel}")
    walk(source)
    return items


def copy_verified(source, destination, expected_size):
    if os.path.isfile(destination) and os.path.getsize(destination) == expected_size:
        def hash_file(path):
            digest = hashlib.sha256()
            with open(path, "rb") as file:
                while block := file.read(BUFFER):
                    digest.update(block)
            return digest.digest()
        if hash_file(source) == hash_file(destination):
            return
    digest = hashlib.sha256()
    count = 0
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".sd2vita-copy-",
                                         dir=os.path.dirname(destination))
        with open(source, "rb") as input_file, os.fdopen(fd, "wb") as output_file:
            while block := input_file.read(BUFFER):
                output_file.write(block)
                digest.update(block)
                count += len(block)
            output_file.flush()
            os.fsync(output_file.fileno())
        if count != expected_size:
            raise IOError(f"Source size changed while copying: {source}")
        os.replace(temporary, destination)
        temporary = None
        check = hashlib.sha256()
        with open(destination, "rb") as output_file:
            while block := output_file.read(BUFFER):
                check.update(block)
        if check.digest() != digest.digest():
            raise IOError(f"Destination verification failed: {destination}")
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_folder", help="folder containing the card files")
    parser.add_argument("card", help="mounted card root, e.g. /Volumes/VITA")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("this card check is supported on macOS only")
    source = os.path.realpath(args.backup_folder)
    destination = card_info(args.card)
    if not os.path.isdir(source):
        raise ValueError("Backup folder does not exist.")
    if os.path.commonpath((source, destination)) in (source, destination):
        raise ValueError("Backup folder and card overlap.")
    if os.stat(source).st_dev == os.stat(destination).st_dev:
        raise ValueError("Backup must be on another volume.")
    items = files_under(source)
    total = sum(size for _, is_dir, size in items if not is_dir)
    if not items:
        raise ValueError("Backup folder is empty.")
    top_level = sorted({relative.split(os.sep, 1)[0] for relative, _, _ in items})
    print("Backup top-level items: " + ", ".join(top_level), flush=True)
    if "app" not in top_level:
        print("NOTE: This backup has no app folder, so installed apps cannot be restored from it.",
              flush=True)
    copied = 0
    for relative, is_dir, size in items:
        target = os.path.join(destination, relative)
        parent = os.path.dirname(target)
        if os.path.islink(parent):
            raise ValueError(f"Destination parent is a symbolic link: {parent}")
        if is_dir:
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(parent, exist_ok=True)
            copy_verified(os.path.join(source, relative), target, size)
            copied += 1
            print(f"Verified {relative}", flush=True)
    print(f"RESTORE SUCCEEDED: {copied} files, {total} bytes verified on {destination}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"RESTORE FAILED: {exc}. Any files already copied remain on the card.")
