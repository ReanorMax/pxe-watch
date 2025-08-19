"""Utilities for updating preseed files with dynamic disk layouts."""

from __future__ import annotations

from pathlib import Path
from typing import List


def _disk_names(count: int) -> List[str]:
    """Return list of disk device names (/dev/sda, /dev/sdb, ...)."""
    return [f"/dev/sd{chr(ord('a') + i)}" for i in range(count)]


def update_disk_layout(path: str, disks: int, size_gb: int) -> str:
    """Update disk and RAID layout inside existing preseed file.

    The function searches for common partman directives and updates them in place.
    Only lines describing disk list and raid method are touched; the rest of the
    file is left intact.  A short summary of calculated partition sizes is
    returned as a string.

    Parameters
    ----------
    path: str
        Path to preseed file that should be edited in-place.
    disks: int
        Number of disks that should participate in the installation.
    size_gb: int
        Size of each disk in gigabytes.  All disks are assumed to be equal.
    """

    if disks <= 0:
        raise ValueError("disks must be positive")
    if size_gb <= 0:
        raise ValueError("size_gb must be positive")

    file_path = Path(path)
    lines = file_path.read_text(encoding="utf-8").splitlines()

    devices = _disk_names(disks)
    disk_line = f"d-i partman-auto/disk string {' '.join(devices)}"
    method_line = "d-i partman-auto/method string raid" if disks > 1 else "d-i partman-auto/method string regular"

    updated: List[str] = []
    for line in lines:
        if line.startswith("d-i partman-auto/disk string"):
            updated.append(disk_line)
        elif line.startswith("d-i partman-auto/method string"):
            updated.append(method_line)
        else:
            updated.append(line)

    file_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

    # calculate partition summary: allocate 1G boot, 1G swap, rest root.
    boot = 1
    swap = 1
    root = size_gb - boot - swap
    if root < 0:
        root = 0

    summary = [f"Disks: {', '.join(devices)}", f"/boot: {boot}G each", f"swap: {swap}G each"]
    if disks > 1:
        summary.append(f"root (RAID1): {root}G")
    else:
        summary.append(f"root: {root}G")
    return "\n".join(summary)


__all__ = ["update_disk_layout"]
