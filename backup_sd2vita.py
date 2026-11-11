#!/usr/bin/env python3
"""Copy a mounted SD2Vita card into a new empty folder without changing the card."""

import argparse
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys

BUFFER = 1024 * 1024


def card_info(path):
    root = os.path.realpath(path)
    if not os.path.isdir(root) or not os.path.ismount(root) or root == "/":
        raise ValueError("Card path must be the root of a mounted card volume.")
    details = plistlib.loads(subprocess.check_output(
        ["/usr/sbin/diskutil", "info", "-plist", root]))
    if os.path.realpath(details.get("MountPoint", "")) != root:
        raise ValueError("Card path does not identify a mounted disk volume.")
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
                    raise ValueError(f"Unsupported card item: {rel}")
    walk(source)
    return items


def copy_verified(source, destination, expected_size):
    digest = hashlib.sha256()
    count = 0
    with open(source, "rb") as input_file, open(destination, "xb") as output_file:
        while block := input_file.read(BUFFER):
            output_file.write(block)
            digest.update(block)
            count += len(block)
        output_file.flush()
        os.fsync(output_file.fileno())
    if count != expected_size:
        raise IOError(f"Source size changed while copying: {source}")
    check = hashlib.sha256()
    with open(destination, "rb") as output_file:
        while block := output_file.read(BUFFER):
            check.update(block)
    if check.digest() != digest.digest():
        raise IOError(f"Destination verification failed: {destination}")
    try:
        shutil.copystat(source, destination)
    except OSError:
        pass  # File data has already been verified; metadata support varies by volume.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("card", help="mounted card root, e.g. /Volumes/VITA")
    parser.add_argument("backup_folder", help="existing empty folder on another volume")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("this card check is supported on macOS only")
    source = card_info(args.card)
    destination = os.path.realpath(args.backup_folder)
    if not os.path.isdir(destination) or os.listdir(destination):
        raise ValueError("Backup folder must exist and be empty.")
    if os.path.commonpath((source, destination)) in (source, destination):
        raise ValueError("Card and backup folder overlap.")
    if os.stat(source).st_dev == os.stat(destination).st_dev:
        raise ValueError("Backup folder must be on another volume.")
    items = files_under(source)
    total = sum(size for _, is_dir, size in items if not is_dir)
    top_level = sorted({relative.split(os.sep, 1)[0] for relative, _, _ in items})
    print("Card top-level items: " + ", ".join(top_level), flush=True)
    if shutil.disk_usage(destination).free < total:
        raise ValueError("Backup folder does not have enough free space.")
    copied = 0
    for relative, is_dir, size in items:
        target = os.path.join(destination, relative)
        if is_dir:
            os.mkdir(target)
        else:
            copy_verified(os.path.join(source, relative), target, size)
            copied += 1
            print(f"Verified {relative}", flush=True)
    print(f"BACKUP SUCCEEDED: {copied} files, {total} bytes verified in {destination}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"BACKUP FAILED: {exc}. Any files already copied remain in the backup folder.")
