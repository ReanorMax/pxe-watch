from typing import List
from textwrap import dedent


def _disk_names(count: int) -> List[str]:
    """Return list of disk device names like /dev/sda, /dev/sdb."""
    if count < 1:
        raise ValueError('disk count must be >= 1')
    return [f"/dev/sd{chr(ord('a') + i)}" for i in range(count)]


def generate_preseed(disks: int, size_gb: int) -> str:
    """Generate preseed file content for the given number of disks and size.

    The resulting preseed config creates RAID1 arrays across all disks for
    /boot, root and swap. Disk size is specified in gigabytes per disk.
    """
    if disks < 1:
        raise ValueError('disks must be >= 1')
    if size_gb < 4:
        raise ValueError('size_gb must be >= 4')

    disk_list = ' '.join(_disk_names(disks))
    boot_size = 1024  # 1 GiB boot
    swap_size = 2048  # 2 GiB swap
    total_mb = size_gb * 1024
    root_size = total_mb - boot_size - swap_size
    if root_size <= 0:
        raise ValueError('disk size too small for partitions')

    expert_recipe = dedent(
        f"""
        d-i partman-auto/expert_recipe string \
            raid :: \
                {boot_size} {boot_size} {boot_size} raid \\
                    $primary{{ }} method{{ raid }} \\
                . \\
                {root_size} {root_size} {root_size} raid \\
                    method{{ raid }} \\
                . \\
                {swap_size} {swap_size} {swap_size} raid \\
                    method{{ raid }} \\
                .
        """
    ).strip()

    raid_recipe = dedent(
        f"""
        d-i partman-auto-raid/recipe string \
            1 {disks} 0 ext4 /boot \
                method{{ raid }} format{{ }} \
                $primary{{ }} $bootable{{ }} \
            . \
            1 {disks} 0 ext4 / \
                method{{ raid }} format{{ }} \
            . \
            1 {disks} 0 linux-swap - \
                method{{ raid }} format{{ }} \
            .
        """
    ).strip()

    preseed = (
        "d-i partman-auto/method string raid\n"
        f"d-i partman-auto/disk string {disk_list}\n"
        f"{expert_recipe}\n"
        f"{raid_recipe}\n"
        "d-i mdadm/boot_degraded string true\n"
        "d-i partman-md/device_remove_md boolean true\n"
        "d-i partman-md/device_remove_lvm boolean true\n"
        "d-i partman/confirm_write_new_label boolean true\n"
        "d-i partman/confirm boolean true\n"
        "d-i partman/confirm_nooverwrite boolean true\n"
    )
    return preseed
