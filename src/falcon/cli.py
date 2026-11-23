"""CLI Typer: `falcon db migrate | sync [--loop] | web`."""

import logging
import sys
import time
from typing import cast

import typer
import uvicorn
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from falcon.config import DatabaseConfig, ImapConfig, SyncConfig
from falcon.email import ImapClient
from falcon.tracking.repository import (
    TrackingRepository,
    apply_migrations,
    make_dict_connection,
)
from falcon.tracking.sync import FolderSyncResult, run_sync
from falcon.tracking.web.app import create_app

logger = logging.getLogger("falcon")

app = typer.Typer(help="Falcon: tracking email shipment.", no_args_is_help=True)
db_app = typer.Typer(help="Lệnh cơ sở dữ liệu.", no_args_is_help=True)
app.add_typer(db_app, name="db")


@app.callback()
def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@db_app.command("migrate")
def db_migrate() -> None:
    """Tạo/cập nhật schema PostgreSQL (chạy lại an toàn)."""
    with make_dict_connection(DatabaseConfig.from_env().database_url) as conn:
        applied = apply_migrations(conn)
    typer.echo(f"Đã áp dụng migration: {applied}" if applied else "Schema đã cập nhật.")


def _sync_once(database: DatabaseConfig, imap: ImapConfig, sync: SyncConfig) -> bool:
    """Chạy một lượt sync; trả True nếu thành công hoàn toàn."""
    with make_dict_connection(database.database_url) as conn:
        results = run_sync(
            TrackingRepository(conn), lambda: ImapClient(imap), sync.folders, sync.data_dir
        )
    if results is None:
        return True
    _report(results)
    return all(result.ok for result in results)


def _report(results: list[FolderSyncResult]) -> None:
    for r in results:
        status = "OK" if r.ok else f"LỖI tại UID {r.failed_uid}"
        typer.echo(
            f"{r.folder}: {status} | mới {r.stored}, đã có {r.already_present}, "
            f"bỏ qua {r.skipped_no_code}"
        )


@app.command("sync")
def sync(
    loop: bool = typer.Option(False, "--loop", help="Lặp theo SYNC_INTERVAL_SECONDS."),
) -> None:
    """Kéo mail mới từ IMAP vào PostgreSQL."""
    database, imap, config = DatabaseConfig.from_env(), ImapConfig.from_env(), SyncConfig.from_env()
    if not loop:
        # Lỗi IMAP/DB ném ra làm Typer thoát mã khác 0 (không in mật khẩu: repr đã ẩn).
        raise typer.Exit(0 if _sync_once(database, imap, config) else 1)
    while True:
        try:
            _sync_once(database, imap, config)
        except Exception as exc:  # noqa: BLE001 - loop phải sống qua lỗi tạm thời
            logger.error("Lượt sync thất bại: %s", type(exc).__name__)
        time.sleep(config.interval_seconds)


@app.command("web")
def web(
    port: int = typer.Option(8000, help="Cổng lắng nghe (luôn bind 127.0.0.1)."),
) -> None:
    """Chạy web UI chỉ đọc."""
    database, config = DatabaseConfig.from_env(), SyncConfig.from_env()
    raw_pool = ConnectionPool(
        database.database_url,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=True,
    )
    pool = cast("ConnectionPool[Connection[DictRow]]", raw_pool)
    with raw_pool:
        uvicorn.run(create_app(pool, config.data_dir), host="127.0.0.1", port=port)


if __name__ == "__main__":
    sys.exit(app())
