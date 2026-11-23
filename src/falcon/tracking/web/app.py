"""FastAPI app chỉ đọc: danh sách shipment, chi tiết shipment, tải file đính kèm."""

import re
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from psycopg import Connection
from psycopg.rows import DictRow
from psycopg_pool import ConnectionPool

from falcon.tracking.repository import TrackingRepository
from falcon.tracking.storage import attachment_path

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f/\\"]')
_MAX_BIGINT = 2**63 - 1


def sanitize_filename(filename: str) -> str:
    """Làm sạch tên file gửi kèm Content-Disposition.

    Args:
        filename: Tên file do người gửi đặt (không tin cậy).

    Returns:
        Tên không chứa dấu phân cách đường dẫn, dấu nháy hay ký tự điều khiển;
        `attachment` nếu rỗng.

    """
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", filename).strip(" .")
    return cleaned or "attachment"


def create_app(pool: ConnectionPool[Connection[DictRow]], data_dir: Path) -> FastAPI:
    """Tạo app web.

    Args:
        pool: Pool kết nối (autocommit, row dict) đã mở; người gọi quản lý vòng đời.
        data_dir: Thư mục gốc `DATA_DIR`.

    Returns:
        App FastAPI với 3 route GET đồng bộ.

    """
    app = FastAPI(title="falcon tracking", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)

    @app.get("/", response_class=HTMLResponse)
    def list_shipments(request: Request, q: str = Query(default="", max_length=64)) -> HTMLResponse:
        with pool.connection() as conn:
            shipments = TrackingRepository(conn).list_shipments(q)
        return templates.TemplateResponse(
            request, "shipments.html", {"shipments": shipments, "q": q}
        )

    @app.get("/shipments/{code}", response_class=HTMLResponse)
    def shipment_detail(request: Request, code: str) -> HTMLResponse:
        with pool.connection() as conn:
            detail = TrackingRepository(conn).get_shipment_detail(code)
        if detail is None:
            raise HTTPException(status_code=404, detail="Không có shipment này")
        return templates.TemplateResponse(request, "shipment_detail.html", {"shipment": detail})

    @app.get("/attachments/{attachment_id}")
    def download_attachment(
        attachment_id: Annotated[int, PathParam(ge=1, le=_MAX_BIGINT)],
    ) -> FileResponse:
        with pool.connection() as conn:
            stored = TrackingRepository(conn).get_attachment(attachment_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Không có file đính kèm")
        path = attachment_path(data_dir, stored.sha256)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File đính kèm không còn trên đĩa")
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=sanitize_filename(stored.filename),
            content_disposition_type="attachment",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    return app
