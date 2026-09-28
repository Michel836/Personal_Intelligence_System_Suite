from types import SimpleNamespace

from src.utils import disk_utils


def test_unix_drive_detection_filters_pseudo_mounts_and_deduplicates(monkeypatch):
    mounts = """/dev/nvme0n1p2 / ext4 rw 0 0
proc /proc proc rw 0 0
tmpfs /run tmpfs rw 0 0
/dev/loop0 /snap/core/1 squashfs ro 0 0
/dev/loop1 /snap/app/2 squashfs ro 0 0
/dev/nvme0n1p2 /mnt/bind ext4 rw,bind 0 0
/dev/sdb1 /media/user/DATA ext4 rw 0 0
"""

    class FakeFile:
        def __enter__(self):
            return mounts.splitlines(True)

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: FakeFile())
    monkeypatch.setattr(disk_utils.os.path, "isdir", lambda path: True)

    def fake_stat(path):
        if path in {"/", "/mnt/bind"}:
            return SimpleNamespace(st_dev=1)
        if path == "/media/user/DATA":
            return SimpleNamespace(st_dev=2)
        return SimpleNamespace(st_dev=100)

    monkeypatch.setattr(disk_utils.os, "stat", fake_stat)
    monkeypatch.setattr(
        disk_utils.shutil,
        "disk_usage",
        lambda path: (4 * 1024**4, 2 * 1024**4, 2 * 1024**4),
    )

    drives = disk_utils._get_unix_drives()

    assert [drive["path"] for drive in drives] == ["/", "/media/user/DATA"]
    assert [drive["type"] for drive in drives] == ["fixed", "removable"]


def test_loop_and_image_mounts_are_not_user_volumes():
    assert not disk_utils._is_user_volume_source("/dev/loop0", "squashfs", "/snap/core/1")
    assert not disk_utils._is_user_volume_source("/dev/loop9", "ext4", "/mnt/image")
    assert not disk_utils._is_user_volume_source("/dev/sr0", "iso9660", "/media/cdrom")
    assert disk_utils._is_user_volume_source("/dev/nvme0n1p2", "ext4", "/")
    assert disk_utils._is_user_volume_source("/dev/sdb1", "ext4", "/media/user/DATA")


def test_validate_scan_path_does_not_emit_fake_estimate(tmp_path):
    result = disk_utils.validate_scan_path(str(tmp_path))
    assert result["valid"] is True
    assert result["estimated_files"] == 0
