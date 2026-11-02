"""CDP-backed browser adapter (pasca-roadmap): executor untuk ``USE_BROWSER``.

Menjembatani keputusan planner (ADR-013: ``USE_BROWSER`` dengan
``target_transport="browser"``) ke jalur raw CDP yang disanksi ADR-011
decision 4 — tanpa Playwright, tanpa dependensi baru.

Bukti spike (roadmap step 7, ``tests/test_browser_cdp.py``): cold start
~5 s, render pertama ~2 s / warm ~0.4 s, chromium RSS ~166 MB, eksekusi JS
terverifikasi pada fixture /js. Adapter ini memakai satu siklus chromium per
``acquire`` — sederhana dan benar; reuse lifecycle ditunda sampai benchmark
menuntutnya (biaya terukur, bukan tersembunyi).

Pemetaan kegagalan (kosakata reason code berbatas):
- runtime tidak bisa dijalankan (binary hilang, CDP endpoint tidak muncul)
  → ``CAPABILITY_MISSING`` — kegagalan yang menjelaskan kemampuan yang kurang;
- kegagalan navigasi/DOM/CDP per halaman → ``CONNECTION_ERROR`` (retryable,
  ditangani planner seperti kegagalan jaringan lain — tetap berbatas).
"""

from typing import Optional

from universal_web_acquisition.access.model import ReasonCode
from universal_web_acquisition.artifact.model import Artifact
from universal_web_acquisition.artifact.storage import ArtifactStorage
from universal_web_acquisition.browser.cdp import (
    CHROMIUM_BIN,
    UA_OVERRIDE,
    BrowserError,
    CDPBrowser,
)
from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.http_transport.adapters import TransportFailure

BROWSER_NAME = "browser"
# Hindari bentrok port: spike manual 9333, E3 9222/9223, test spike 9341.
DEFAULT_BROWSER_PORT = 9351


class CDPBrowserAdapter:
    """Adapter browser dengan kontrak yang sama dengan adapter HTTP
    (``name``/``can_handle``/``acquire``) sehingga worker mengeksekusinya
    lewat jalur yang identik.

    Dua mode lifecycle (ADR-014):
    - ``keep_alive=False`` (default): satu siklus chromium per ``acquire`` —
      sederhana dan benar untuk pemakaian jarang;
    - ``keep_alive=True``: chromium persisten — lazy start pada acquire
      pertama, reuse untuk acquire berikutnya (hemat ~5 s cold start per
      attempt), **deteksi crash** (proses mati → restart otomatis pada
      acquire berikutnya, terhitung di ``restarts``), dan ``close()`` bersih.
    """

    name = BROWSER_NAME

    def __init__(
        self,
        executable: str = CHROMIUM_BIN,
        port: int = DEFAULT_BROWSER_PORT,
        render_timeout: float = 15.0,
        start_timeout: float = 20.0,
        keep_alive: bool = False,
    ):
        self._executable = executable
        self._port = port
        self._render_timeout = render_timeout
        self._start_timeout = start_timeout
        self._keep_alive = keep_alive
        self._browser: Optional[CDPBrowser] = None
        # Bukti lifecycle (terukur, bukan klaim): berapa kali chromium
        # diluncurkan dan berapa kali crash terdeteksi lalu di-restart.
        self.starts = 0
        self.restarts = 0
        # Bukti biaya browser (E4): RSS chromium (kB) hasil ukur render
        # terakhir — dipakai benchmark adaptive-scheduling untuk membandingkan
        # biaya memori lengan browser vs HTTP.
        self.last_rss_kb: Optional[int] = None

    def can_handle(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    def _ensure_started(self) -> CDPBrowser:
        """Browser hidup untuk mode persisten — lazy start + deteksi crash."""
        if self._browser is not None and self._browser.is_alive():
            return self._browser
        if self._browser is not None:
            # proses mati di antara acquire (crash/OOM) → restart terukur
            self._browser.stop()
            self.restarts += 1
        self._browser = CDPBrowser(
            executable=self._executable,
            port=self._port,
            start_timeout=self._start_timeout,
            render_timeout=self._render_timeout,
        )
        self._browser.start()
        self.starts += 1
        return self._browser

    def close(self) -> None:
        """Hentikan chromium persisten — dipanggil worker saat berhenti."""
        if self._browser is not None:
            self._browser.stop()
            self._browser = None

    async def acquire(
        self, job: Job, storage: ArtifactStorage, cookies=None
    ) -> Artifact:
        """Render ``job.url`` via raw CDP → simpan sebagai artifact.

        ``cookies`` (A05 di jalur browser): disuntikkan via
        ``Network.setCookie`` sebelum navigasi — sesi aktif mengalir ke
        render browser seperti ke adapter HTTP.

        Status 0 dari performance API (entry navigation tidak mengekspos
        responseStatus) dipetakan ke 200: DOM ``complete`` + konten terekstrak
        adalah bukti navigasi berhasil — jangan mengklasifikasi ulang kegagalan
        yang tidak terjadi.
        """
        if self._keep_alive:
            browser = self._ensure_started()
            try:
                result = await browser.render(job.url, cookies=cookies)
            except BrowserError as exc:
                raise TransportFailure(
                    ReasonCode.CONNECTION_ERROR,
                    f"render browser gagal: {exc}",
                ) from exc
        else:
            browser = CDPBrowser(
                executable=self._executable,
                port=self._port,
                start_timeout=self._start_timeout,
                render_timeout=self._render_timeout,
            )
            try:
                browser.start()
                self.starts += 1
            except BrowserError as exc:
                raise TransportFailure(
                    ReasonCode.CAPABILITY_MISSING,
                    f"browser runtime tidak tersedia: {exc}",
                ) from exc
            try:
                result = await browser.render(job.url, cookies=cookies)
            except BrowserError as exc:
                raise TransportFailure(
                    ReasonCode.CONNECTION_ERROR,
                    f"render browser gagal: {exc}",
                ) from exc
            finally:
                browser.stop()

        # Bukti biaya memori browser (E4): RSS chromium setelah render.
        self.last_rss_kb = result.chromium_rss_kb

        artifact = Artifact(
            job_id=job.job_id,
            url=result.final_url or job.url,
            content=result.content.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            status_code=result.status_code or 200,
            headers={"user-agent": UA_OVERRIDE},
        )
        return await storage.store(artifact)
