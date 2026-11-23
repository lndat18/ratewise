"""Test lưu file đính kèm content-addressed."""

import hashlib
from pathlib import Path

import pytest

from falcon.tracking.storage import attachment_path, store_attachment

SHA = hashlib.sha256(b"data").hexdigest()


def test_attachment_path_layout(tmp_path: Path) -> None:
    assert attachment_path(tmp_path, SHA) == tmp_path / "attachments" / SHA


@pytest.mark.parametrize(
    "bad", ["", "../../etc/passwd", "a" * 63, "a" * 65, "A" * 64, "g" * 64, SHA + "/x"]
)
def test_attachment_path_rejects_bad_sha(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="sha256"):
        attachment_path(tmp_path, bad)


def test_store_writes_content_without_leftover_tmp(tmp_path: Path) -> None:
    path = store_attachment(tmp_path, SHA, b"data")
    assert path.read_bytes() == b"data"
    assert [p.name for p in path.parent.iterdir()] == [SHA]


def test_store_existing_is_skipped(tmp_path: Path) -> None:
    path = store_attachment(tmp_path, SHA, b"data")
    mtime = path.stat().st_mtime_ns
    store_attachment(tmp_path, SHA, b"other")
    assert path.read_bytes() == b"data"
    assert path.stat().st_mtime_ns == mtime


def test_store_failure_cleans_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(src: str, dst: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("falcon.tracking.storage.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store_attachment(tmp_path, SHA, b"data")
    assert list((tmp_path / "attachments").iterdir()) == []
