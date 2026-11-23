"""Chuyển `EmailMessage` thành `ParsedEmail` (hàm thuần, không I/O)."""

import hashlib
from datetime import UTC, datetime
from email.message import EmailMessage, Message
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

from falcon.tracking.models import ParsedAttachment, ParsedEmail

_SKIPPED_HTML_TAGS = frozenset({"script", "style"})


class _TextExtractor(HTMLParser):
    """Gom text của HTML, bỏ nội dung `<script>`/`<style>`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_HTML_TAGS:
            self._skip_depth += 1
        elif tag in {"br", "p", "div", "tr", "li"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_HTML_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks).strip()


def strip_html(html: str) -> str:
    """Bỏ tag HTML, chỉ giữ text.

    Args:
        html: Chuỗi HTML.

    Returns:
        Text thuần.

    """
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return extractor.text()


def _clean(value: str) -> str:
    # PostgreSQL từ chối ký tự NUL trong kiểu text.
    return value.replace("\x00", "")


def _header_text(message: Message, name: str) -> str:
    try:
        return _clean(str(message.get(name, "") or "").strip())
    except Exception:  # noqa: BLE001 - header hỏng không được làm hỏng cả mail
        return ""


def _addresses(message: Message, name: str) -> list[str]:
    try:
        values = [str(v) for v in message.get_all(name, [])]
    except Exception:  # noqa: BLE001
        return []
    return [_clean(addr) for _, addr in getaddresses(values) if addr]


def _parse_sent_at(message: Message) -> datetime | None:
    raw = _header_text(message, "Date")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except TypeError, ValueError, IndexError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _message_id(message: EmailMessage) -> str:
    header = _header_text(message, "Message-ID")
    if header:
        return header
    digest = hashlib.sha256(message.as_bytes()).hexdigest()
    return f"sha256:{digest}"


def _is_attachment(part: Message) -> bool:
    return part.get_content_disposition() == "attachment" or part.get_filename() is not None


def _decode_text_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:  # charset lạ
        return payload.decode("utf-8", errors="replace")


def _extract_body(message: EmailMessage) -> str:
    plain: str | None = None
    html: str | None = None
    for part in message.walk():
        if part.is_multipart() or _is_attachment(part):
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain" and plain is None:
            plain = _decode_text_part(part)
        elif content_type == "text/html" and html is None:
            html = _decode_text_part(part)
    if plain is not None:
        return _clean(plain)
    return _clean(strip_html(html)) if html is not None else ""


def _extract_attachments(message: EmailMessage) -> list[ParsedAttachment]:
    attachments: list[ParsedAttachment] = []
    for part in message.walk():
        if part.is_multipart() or not _is_attachment(part):
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        attachments.append(
            ParsedAttachment(
                filename=_clean(part.get_filename() or ""),
                content_type=part.get_content_type(),
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                content=payload,
            )
        )
    return attachments


def parse_email(message: EmailMessage) -> ParsedEmail:
    """Chuẩn hóa một email thô.

    Args:
        message: Email đã parse bằng `policy.default`.

    Returns:
        `ParsedEmail`. Header Date hỏng cho `sent_at=None`; thiếu Message-ID thì
        dùng `sha256:<hash nội dung>`; không có text/plain thì strip HTML.

    """
    from_addrs = _addresses(message, "From")
    return ParsedEmail(
        message_id=_message_id(message),
        subject=_header_text(message, "Subject"),
        from_addr=from_addrs[0] if from_addrs else "",
        to_addrs=_addresses(message, "To"),
        cc_addrs=_addresses(message, "Cc"),
        sent_at=_parse_sent_at(message),
        body_text=_extract_body(message),
        attachments=_extract_attachments(message),
    )
