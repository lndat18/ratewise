"""Model dữ liệu của package tracking (email đã parse và dữ liệu đọc từ DB)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ParsedAttachment(BaseModel):
    """File đính kèm đã tách khỏi email."""

    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    content: bytes = Field(repr=False)


class ParsedEmail(BaseModel):
    """Email đã chuẩn hóa, sẵn sàng ghi DB."""

    message_id: str
    subject: str
    from_addr: str
    to_addrs: list[str]
    cc_addrs: list[str]
    sent_at: datetime | None
    body_text: str = Field(repr=False)
    attachments: list[ParsedAttachment]


class FolderSyncState(BaseModel):
    """Con trỏ đồng bộ đã lưu của một folder."""

    uidvalidity: int
    last_uid: int


class ShipmentSummary(BaseModel):
    """Một hàng ở trang danh sách shipment."""

    code: str
    email_count: int
    latest_sent_at: datetime | None
    latest_subject: str


class AttachmentInfo(BaseModel):
    """Metadata file đính kèm hiển thị trên web."""

    id: int
    filename: str
    content_type: str
    size_bytes: int


class StoredAttachment(BaseModel):
    """Bản ghi attachment dùng để phục vụ tải file."""

    filename: str
    sha256: str


class EmailView(BaseModel):
    """Một email trong trang chi tiết shipment."""

    model_config = ConfigDict(frozen=True)

    id: int
    subject: str
    from_addr: str
    to_addrs: list[str]
    sent_at: datetime | None
    body_text: str
    attachments: list[AttachmentInfo]


class ShipmentDetail(BaseModel):
    """Shipment kèm toàn bộ email của nó."""

    code: str
    emails: list[EmailView]
