#!/usr/bin/env python3
"""Erase one removable macOS disk as whole-device exFAT with 64 KiB clusters."""

import argparse
import plistlib
import re
import subprocess
import sys

DISKUTIL = "/usr/sbin/diskutil"
NEWFS = "/sbin/newfs_exfat"
SUDO = "/usr/bin/sudo"


def cluster_bytes_for_size(disk_bytes):
    # StorageMgr supports exFAT clusters up to 64 KiB. Use that size for all
    # supported cards, including 128 GB, as requested.
    return 65536


def run(*args, privileged=False):
    command = ([SUDO] if privileged else []) + list(args)
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or
                           f"Command failed ({completed.returncode}): {command[0]}")
    return completed.stdout


def info(device):
    return plistlib.loads(subprocess.check_output([DISKUTIL, "info", "-plist", device]))


def check_disk(disk_id):
    details = info("/dev/" + disk_id)
    removable = bool(details.get("RemovableMedia") or details.get("Removable"))
    external = not details.get("Internal", True) and bool(
        details.get("Ejectable") or details.get("RemovableMediaOrExternalDevice") or removable)
    built_in_sd = (details.get("Internal", True) and removable and
                   str(details.get("BusProtocol", "")).lower() == "secure digital")
    if (details.get("DeviceIdentifier") != disk_id or not details.get("WholeDisk") or
            details.get("OSInternalMedia") or
            details.get("VirtualOrPhysical") != "Physical" or
            not details.get("WritableMedia") or not (external or built_in_sd)):
        raise RuntimeError("Refusing disk: it is not a writable physical removable card.")
    size = int(details.get("TotalSize", 0))
    if size <= 0 or size > 2_000_000_000_000:
        raise RuntimeError("Refusing disk: unsupported or unknown capacity.")
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disk", help="whole disk identifier from diskutil list, e.g. disk4")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("formatting is supported on macOS only")
    disk_id = args.disk.removeprefix("/dev/")
    if not re.fullmatch(r"disk[1-9][0-9]*", disk_id):
        parser.error("provide a whole disk identifier such as disk4")
    details = check_disk(disk_id)
    size = int(details["TotalSize"])
    cluster_bytes = cluster_bytes_for_size(size)
    print(f"Disk: /dev/{disk_id} | {details.get('MediaName', 'SD card')} | "
          f"{size / 1_000_000_000:.1f} GB | {details.get('BusProtocol', 'unknown bus')}")
    print(f"Format: whole-device exFAT, no partition table, "
          f"{cluster_bytes // 1024} KiB clusters")
    print("ERASES THE ENTIRE DISK. Make and check a separate backup first.")
    if input(f"Type ERASE {disk_id} to continue: ").strip() != f"ERASE {disk_id}":
        print("Cancelled. No changes made.")
        return
    run(SUDO, "-v")
    current = check_disk(disk_id)
    if (current.get("TotalSize") != details.get("TotalSize") or
            current.get("MediaName") != details.get("MediaName") or
            current.get("BusProtocol") != details.get("BusProtocol")):
        raise RuntimeError("Disk identity changed. No erase started.")
    erase_started = False
    cluster_verified = False
    try:
        print("Removing the old partition map and filesystem signatures...")
        erase_started = True
        run(DISKUTIL, "unmountDisk", "/dev/" + disk_id, privileged=True)
        run(DISKUTIL, "zeroDisk", "short", "/dev/" + disk_id, privileged=True)
        after_wipe = check_disk(disk_id)
        if int(after_wipe.get("TotalSize", 0)) != size:
            raise RuntimeError("Disk identity changed after erasing.")
        print(f"Setting {cluster_bytes // 1024} KiB exFAT clusters...")
        run(NEWFS, "-R", "-b", str(cluster_bytes), "-v", "PSVITA", "/dev/" + disk_id,
            privileged=True)
        output = run(NEWFS, "-N", "/dev/" + disk_id, privileged=True)
        match = re.search(r"Bytes per cluster\s*:\s*(\d+)", output, re.I)
        if not match or int(match.group(1)) != cluster_bytes:
            raise RuntimeError(f"Could not verify {cluster_bytes // 1024} KiB clusters.")
        offset = re.search(r"Partition offset\s*:\s*(\d+)\s+sectors", output, re.I)
        if not offset or int(offset.group(1)) != 0:
            raise RuntimeError("ExFAT does not start at sector 0 as on the working card.")
        cluster_verified = True
        try:
            run(DISKUTIL, "mount", "/dev/" + disk_id, privileged=True)
        except RuntimeError:
            run(DISKUTIL, "mountDisk", "/dev/" + disk_id, privileged=True)
        whole = info("/dev/" + disk_id)
        if (not whole.get("WholeDisk") or
                str(whole.get("FilesystemType", "")).lower() != "exfat" or
                not whole.get("MountPoint")):
            raise RuntimeError("Whole-device exFAT mount verification failed.")
        print(f"FORMAT SUCCEEDED: {whole['MountPoint']} "
              f"(whole-device exFAT, {cluster_bytes // 1024} KiB clusters)")
    except Exception:
        if erase_started:
            try:
                run(DISKUTIL, "mount", "/dev/" + disk_id, privileged=True)
            except Exception:
                pass
            print(("The whole-device exFAT filesystem and cluster size were verified, "
                   "but macOS did not finish mounting it. Eject and reinsert the card; "
                   "do not reformat it yet." if cluster_verified else
                   "Formatting started and may have erased the card. "
                   "Do not assume its files remain."), file=sys.stderr)
        raise


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"FORMAT FAILED: {exc}")
