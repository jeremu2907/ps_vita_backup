# SD2Vita card scripts (macOS, StorageMgr)

These are three separate operations. **Formatting never runs during backup or
restore.** The copy scripts include hidden Vita files and verify every copied
file with SHA-256. They do not filter any files or folders, including hidden
files and macOS metadata.

## 1. Back up a readable card

Create an empty folder on the computer, then run:

```sh
mkdir -p "$HOME/Desktop/vita-backup"
python3 backup_sd2vita.py /Volumes/VITA "$HOME/Desktop/vita-backup"
```

The script reads the card and writes only to the empty backup folder. Wait for
`BACKUP SUCCEEDED` before considering formatting. A failed backup leaves its
partial files in the folder; start again with a **new empty folder**.

## 2. Format the card

Only after checking the backup, find the whole disk identifier with
`diskutil list`. For example, if the card is `/dev/disk4`:

```sh
python3 format_sd2vita.py disk4
```

The script checks that the disk is writable, physical, and removable, then
requires the exact phrase `ERASE disk4`. It erases the entire disk and formats
exFAT directly on the whole device, with **no partition table**, matching the
working card you showed. It sets and verifies 64 KiB clusters, including on a
128 GB card, and checks that exFAT starts at sector 0. This **destroys the card's current
files**. The disk number can change when the card is reinserted; check it each
time. The script does not copy any files. If it reports a failure after erasing,
the card may be empty or incompletely formatted.

## 3. Copy the backup to the formatted card

After the card mounts as an exFAT volume:

```sh
python3 restore_sd2vita.py "$HOME/Desktop/vita-backup" /Volumes/VITA
```

The script copies all backup files and verifies each one. Matching files already
on the card are replaced; files absent from the backup remain on the card. It
does not format the card. A failed copy can be rerun against the same card.

This workflow targets **StorageMgr / macOS exFAT**. The
[Vita Hacks Guide's Mac procedure](https://vita.hacks.guide/storage-format-%28mac%29.html)
formats exFAT directly on the whole disk. The guide requires a special cluster
size for cards of 256 GB or larger; StorageMgr supports clusters up to 64 KiB.
The script uses 64 KiB on a 128 GB card as requested. These scripts do not
configure the Vita's storage plugin.
