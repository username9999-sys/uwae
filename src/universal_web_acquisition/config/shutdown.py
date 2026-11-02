"""Graceful shutdown handler (P8).

Menangani SIGTERM/SIGINT: finish current job, checkpoint, stop cleanly.
"""

import asyncio
import json
import logging
import signal
from contextlib import asynccontextmanager
from typing import Optional, Callable, Awaitable

from universal_web_acquisition.config.loader import ShutdownConfig

logger = logging.getLogger(__name__)


class ShutdownManager:
    """Mengelola graceful shutdown untuk long-running processes."""

    def __init__(
        self,
        config: ShutdownConfig,
        checkpoint_fn: Optional[Callable[[], Awaitable[None]]] = None,
        stop_event: Optional[asyncio.Event] = None,
    ):
        self.config = config
        self.checkpoint_fn = checkpoint_fn
        self.stop_event = stop_event or asyncio.Event()
        self._shutdown_requested = False
        self._current_job_id: Optional[str] = None
        self._handlers_installed = False

    def set_current_job(self, job_id: Optional[str]) -> None:
        """Dipanggil worker saat memulai/selesai job."""
        self._current_job_id = job_id

    def install_signal_handlers(self) -> None:
        """Pasang handler SIGTERM/SIGINT."""
        if self._handlers_installed:
            return
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(
                    sig, lambda s=sig: asyncio.create_task(self._handle_signal(s))
                )
            except NotImplementedError:
                # Windows tidak punya add_signal_handler
                pass
        self._handlers_installed = True

    async def _handle_signal(self, sig: signal.Signals) -> None:
        """Handler sinyal shutdown."""
        if self._shutdown_requested:
            logger.warning("Sinyal shutdown diterima lagi — force exit")
            import sys
            sys.exit(1)

        self._shutdown_requested = True
        sig_name = sig.name if hasattr(sig, "name") else str(sig)
        logger.info(
            "Sinyal %s diterima — memulai graceful shutdown (max wait %.1fs)",
            sig_name,
            self.config.max_wait_seconds,
        )

        # Jika ada job berjalan, tunggu selesai (dengan timeout)
        if self._current_job_id:
            logger.info(
                "Menunggu job %s selesai (timeout %.1fs)...",
                self._current_job_id,
                self.config.max_wait_seconds,
            )
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=self.config.max_wait_seconds,
                )
                logger.info("Job %s selesai sebelum shutdown", self._current_job_id)
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout menunggu job %s — shutdown paksa",
                    self._current_job_id,
                )

        # Checkpoint final
        if self.checkpoint_fn:
            logger.info("Menjalankan checkpoint final...")
            try:
                await self.checkpoint_fn()
                logger.info("Checkpoint final selesai")
            except Exception as exc:
                logger.exception("Checkpoint final gagal: %s", exc)

        self.stop_event.set()

    def is_shutdown_requested(self) -> bool:
        """Cek apakah shutdown sudah diminta."""
        return self._shutdown_requested

    @asynccontextmanager
    async def job_context(self, job_id: str):
        """Context manager untuk tracking job saat ini."""
        self.set_current_job(job_id)
        self.stop_event.clear()
        try:
            yield
        finally:
            self.set_current_job(None)
            self.stop_event.set()

    async def wait_for_shutdown(self) -> None:
        """Tunggu sampai shutdown diminta."""
        await self.stop_event.wait()


async def run_with_shutdown(
    config: ShutdownConfig,
    coro_fn: Callable[[], Awaitable[None]],
    checkpoint_fn: Optional[Callable[[], Awaitable[None]]] = None,
) -> None:
    """Jalankan coroutine dengan graceful shutdown handling.

    Usage:
        await run_with_shutdown(
            config.shutdown,
            my_main_loop,
            checkpoint_fn=my_checkpoint,
        )
    """
    manager = ShutdownManager(config, checkpoint_fn)
    manager.install_signal_handlers()

    try:
        await coro_fn()
    except asyncio.CancelledError:
        logger.info("Main loop dibatalkan — graceful shutdown")
        raise
    finally:
        # Trigger shutdown jika belum
        if not manager.is_shutdown_requested():
            await manager._handle_signal(signal.SIGTERM)


def setup_logging(log_level: str, log_format: str) -> None:
    """Konfigurasi logging UWAE.

    Dua hal yang WAJIB dijaga — keduanya ditemukan lewat regresi CLI:

    1. Handler dipasang pada logger ``universal_web_acquisition``, BUKAN root
       logger. Masangnya di root ikut menangkap log dari luar paket ini, dan
       yang lebih penting: menimpanya menghapus konfigurasi milik pemanggil
       (pytest, aplikasi host). Handler di logger induk tetap diteruskan ke
       logger anak lewat propagasi, jadi tidak ada log UWAE yang hilang.

    2. Keluaran ke **stderr**, bukan stdout. Stdout adalah KONTRAK: ``uwae
       acquire --json`` dan ``uwae stats --json`` menulis JSON ke sana, dan
       sukses/gagalnya diuji dengan mem-parse stdout. Log yang bercampur
       ke stdout merusak parse itu — 12 test CLI runtuh karena satu baris
       log ("Job ... succeeded") muncul sebelum JSON.
    """
    import sys

    level = getattr(logging, log_level.upper(), logging.INFO)

    if log_format == "json":

        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                log_data = {
                    "timestamp": self.formatTime(record),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                if record.exc_info:
                    log_data["exception"] = self.formatException(record.exc_info)
                return json.dumps(log_data, ensure_ascii=False)

        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    uwae_logger = logging.getLogger("universal_web_acquisition")
    uwae_logger.setLevel(level)
    uwae_logger.handlers = [handler]
    # Propagasi ke root dimatikan: kalau pemanggil (pytest, aplikasi host)
    # sudah memasang handler sendiri, log UWAE akan tercetak DUA kali.
    uwae_logger.propagate = False