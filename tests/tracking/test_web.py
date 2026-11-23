"""Test web (TestClient) với repository giả thay cho PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from falcon.tracking.models import (
    AttachmentInfo,
    EmailView,
    ShipmentDetail,
    ShipmentSummary,
    StoredAttachment,
)
from falcon.tracking.web.app import create_app, sanitize_filename

SHA = "a" * 64
XSS = "<script>alert(1)</script>"


class FakePool:
    """Pool giả: `connection()` trả context manager."""

    @contextmanager
    def connection(self) -> Iterator[None]:
        yield None


class FakeRepo:
    """Repository giả có dữ liệu cố định."""

    last_query: str | None = None
    attachments: dict[int, StoredAttachment] = {}

    def __init__(self, conn: object) -> None:
        pass

    def list_shipments(self, query: str | None = None) -> list[ShipmentSummary]:
        FakeRepo.last_query = query
        return [
            ShipmentSummary(
                code="AE-49270",
                email_count=2,
                latest_sent_at=datetime(2026, 11, 23, 10, 0, tzinfo=UTC),
                latest_subject=XSS,
            )
        ]

    def get_shipment_detail(self, code: str) -> ShipmentDetail | None:
        if code.upper() != "AE-49270":
            return None
        return ShipmentDetail(
            code="AE-49270",
            emails=[
                EmailView(
                    id=1,
                    subject=XSS,
                    from_addr="a@x.com",
                    to_addrs=["b@x.com"],
                    sent_at=None,
                    body_text=f"body {XSS} & <b>bold</b>",
                    attachments=[
                        AttachmentInfo(
                            id=5, filename="r.pdf", content_type="application/pdf", size_bytes=3
                        )
                    ],
                )
            ],
        )

    def get_attachment(self, attachment_id: int) -> StoredAttachment | None:
        return FakeRepo.attachments.get(attachment_id)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> TestClient:
    monkeypatch.setattr("falcon.tracking.web.app.TrackingRepository", FakeRepo)
    FakeRepo.attachments = {}
    FakeRepo.last_query = None
    return TestClient(create_app(cast("Any", FakePool()), data_dir))


def test_index_lists_and_escapes(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "/shipments/AE-49270" in resp.text
    assert XSS not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_index_passes_query(client: TestClient) -> None:
    client.get("/", params={"q": "492"})
    assert FakeRepo.last_query == "492"


def test_index_query_too_long_is_422(client: TestClient) -> None:
    assert client.get("/", params={"q": "x" * 65}).status_code == 422


def test_query_value_is_escaped(client: TestClient) -> None:
    resp = client.get("/", params={"q": '"><script>x</script>'})
    assert "<script>x</script>" not in resp.text


def test_detail_ok_and_body_escaped(client: TestClient) -> None:
    resp = client.get("/shipments/AE-49270")
    assert resp.status_code == 200
    assert "<script>" not in resp.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text
    assert "&lt;b&gt;bold&lt;/b&gt;" in resp.text
    assert 'href="/attachments/5"' in resp.text


def test_detail_unknown_is_404(client: TestClient) -> None:
    assert client.get("/shipments/AE-00000").status_code == 404


def test_attachment_download_headers(client: TestClient, data_dir: Path) -> None:
    (data_dir / "attachments").mkdir()
    (data_dir / "attachments" / SHA).write_bytes(b"pdfdata")
    FakeRepo.attachments = {7: StoredAttachment(filename='../ev"il.html', sha256=SHA)}

    resp = client.get("/attachments/7")

    assert resp.status_code == 200
    assert resp.content == b"pdfdata"
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert "/" not in disposition and "\\" not in disposition
    assert resp.headers["content-type"].startswith("application/octet-stream")
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_attachment_unknown_is_404(client: TestClient) -> None:
    assert client.get("/attachments/99").status_code == 404


def test_attachment_file_missing_is_404(client: TestClient) -> None:
    FakeRepo.attachments = {7: StoredAttachment(filename="a.pdf", sha256=SHA)}
    assert client.get("/attachments/7").status_code == 404


@pytest.mark.parametrize("value", ["0", "-1", str(2**63), "abc"])
def test_attachment_id_out_of_range_is_422(client: TestClient, value: str) -> None:
    assert client.get(f"/attachments/{value}").status_code == 422


def test_attachment_max_bigint_is_404_not_error(client: TestClient) -> None:
    assert client.get(f"/attachments/{2**63 - 1}").status_code == 404


def test_docs_disabled(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "_.._etc_passwd"),
        ('a"b\\c/d', "a_b_c_d"),
        ("x\r\ny\x00z", "x__y_z"),
        ("", "attachment"),
        ("  ..  ", "attachment"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected
