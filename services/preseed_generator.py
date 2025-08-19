import re
from typing import List

MARKER_BEGIN = "# BEGIN AUTO-DISKS"
MARKER_END = "# END AUTO-DISKS"


def _disk_names(count: int) -> List[str]:
    """Return list of linux disk device names like /dev/sda."""
    if count < 1:
        raise ValueError("disk count must be >= 1")
    return [f"/dev/sd{chr(ord('a') + i)}" for i in range(count)]


def generate_disk_section(count: int, volume_gb: int) -> str:
    """Generate preseed lines describing RAID1 layout for given disks and volume."""
    disks = _disk_names(count)
    swap_size = max(1, volume_gb // 10)
    root_size = volume_gb - swap_size

    lines = [
        f"d-i partman-auto/disk string {' '.join(disks)}",
        "d-i partman-auto/method string raid",
        "d-i partman-md/device_remove_md boolean true",
        "d-i partman-lvm/device_remove_lvm boolean true",
        "d-i partman/confirm boolean true",
        "d-i partman/confirm_nooverwrite boolean true",
        f"d-i partman-md/0/device string {' '.join(f'{d}1' for d in disks)}",
        "d-i partman-md/0/level string 1",
        f"d-i partman-md/0/size string {root_size}GB",
        "d-i partman-md/0/format string ext4",
        "d-i partman-md/0/mountpoint string /",
        f"d-i partman-md/1/device string {' '.join(f'{d}2' for d in disks)}",
        "d-i partman-md/1/level string 1",
        f"d-i partman-md/1/size string {swap_size}GB",
        "d-i partman-md/1/format string swap",
        "d-i partman-md/1/mountpoint string swap",
    ]
    return "\n".join(lines) + "\n"


def update_disk_section(content: str, disks: int, volume_gb: int) -> str:
    """Replace disk section in preseed content or append it if not present."""
    section = generate_disk_section(disks, volume_gb)
    pattern = re.compile(rf"{MARKER_BEGIN}.*?{MARKER_END}", re.DOTALL)
    replacement = f"{MARKER_BEGIN}\n{section}{MARKER_END}"
    if pattern.search(content):
        return pattern.sub(replacement, content)
    return content.rstrip() + "\n\n" + replacement + "\n"
