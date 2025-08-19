from services.preseed_generator import (
    generate_disk_section,
    update_disk_section,
    MARKER_BEGIN,
    MARKER_END,
)


def test_generate_disk_section_contains_disks():
    text = generate_disk_section(2, 100)
    assert "d-i partman-auto/disk string /dev/sda /dev/sdb" in text
    assert "d-i partman-md/0/level string 1" in text


def test_update_disk_section_adds_markers():
    content = "some preseed content"
    updated = update_disk_section(content, 1, 50)
    assert MARKER_BEGIN in updated
    assert MARKER_END in updated
