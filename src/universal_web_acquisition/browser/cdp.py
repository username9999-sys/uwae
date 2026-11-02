"""Raw CDP browser client (roadmap step 7, ADR-011 browser path).

Minimal Chromium DevTools Protocol client over websockets — zero new
dependencies (websockets verified in G0-3). Implements the browser path
sanctioned by ADR-011 decision 4: raw CDP from Termux Python driving the
PRoot chromium binary as a subprocess.

Spike mandate (INSTRUCTION.md, Rencana v1 §7 item 7): measure cold start,
render success, and memory consumption — recorded as evidence, not claims.
"""

import asyncio
import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

import websockets

CHROMIUM_BIN = "/usr/bin/chromium"
DEFAULT_PORT = 9333
# ADR-011 decision 7: UA override wajib (chromium build ini melaporkan x86_64 di aarch64)
UA_OVERRIDE = "UniversalWebAcquisitionEngine/0.2.0"


class BrowserError(Exception):
    """Kegagalan jalur browser dengan pesan yang menjelaskan penyebabnya."""


@dataclass(frozen=True)
class RenderResult:
    """Hasil satu render, lengkap dengan metrik bukti."""

    url: str
    final_url: str
    status_code: int
    content: str  # document.documentElement.outerHTML (setelah JS dieksekusi)
    title: str
    cold_start_ms: float  # launch → CDP endpoint siap
    render_ms: float  # navigate → DOM siap
    chromium_rss_kb: Optional[int]  # VmRSS proses chromium setelah render (/proc)


class CDPBrowser:
    """Satu instance chromium headless; konteks-managed; render per halaman."""

    def __init__(
        self,
        executable: str = CHROMIUM_BIN,
        port: int = DEFAULT_PORT,
        start_timeout: float = 20.0,
        render_timeout: float = 10.0,
    ):
        self.executable = executable
        self.port = port
        self.start_timeout = start_timeout
        self.render_timeout = render_timeout
        self._proc: Optional[subprocess.Popen] = None
        self.cold_start_ms = 0.0

    # -- lifecycle (sinkron) -------------------------------------------------

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def start(self) -> float:
        """Launch chromium headless + tunggu CDP endpoint. Return cold start ms."""
        t0 = time.perf_counter()
        self._proc = subprocess.Popen(
            [
                self.executable,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                f"--remote-debugging-port={self.port}",
                f"--user-agent={UA_OVERRIDE}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = t0 + self.start_timeout
        while time.perf_counter() < deadline:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/version", timeout=1
                )
                self.cold_start_ms = (time.perf_counter() - t0) * 1000
                return self.cold_start_ms
            except Exception:
                time.sleep(0.2)
        self.stop()
        raise BrowserError(f"CDP endpoint tidak muncul dalam {self.start_timeout}s")

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def is_alive(self) -> bool:
        """True bila proses chromium masih hidup (deteksi crash lifecycle persisten)."""
        return self._proc is not None and self._proc.poll() is None

    # -- internal ------------------------------------------------------------

    def _page_target(self) -> Dict[str, Any]:
        targets = json.load(
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=3)
        )
        pages = [t for t in targets if t.get("type") == "page"]
        if not pages:
            raise BrowserError("tidak ada page target di CDP endpoint")
        return pages[0]

    def _chromium_rss_kb(self) -> Optional[int]:
        if self._proc is None:
            return None
        try:
            with open(f"/proc/{self._proc.pid}/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])  # kB
        except OSError:
            pass
        return None

    @staticmethod
    async def _send(ws: Any, msg_id: int, method: str, params: Optional[Dict] = None) -> Dict:
        await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise BrowserError(f"CDP error pada {method}: {msg['error']}")
                return msg.get("result", {})
            # event CDP (mis. Page.loadEventFired) diabaikan

    # -- operasi (async) -----------------------------------------------------

    async def evaluate(self, expression: str) -> Any:
        """Evaluasi satu ekspresi JS pada page target aktif."""
        target = self._page_target()
        async with websockets.connect(
            target["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024
        ) as ws:
            result = await self._send(
                ws, 1, "Runtime.evaluate", {"expression": expression, "returnByValue": True}
            )
            return result.get("result", {}).get("value")

    async def render(self, url: str, cookies: Optional[Dict[str, str]] = None) -> RenderResult:
        """Navigasi + tunggu DOM siap + ekstrak outerHTML/title/status + metrik.

        ``cookies`` opsional (A05 di jalur browser): disuntikkan via
        ``Network.setCookie`` (domain diambil dari URL navigasi) SEBELUM
        navigasi — sesi aktif mengalir ke render browser seperti ke adapter
        HTTP.
        """
        target = self._page_target()
        t0 = time.perf_counter()
        async with websockets.connect(
            target["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024
        ) as ws:
            # ID pesan unik per koneksi — counter, bukan literal, agar aman
            # terhadap penambahan perintah (mis. Network.setCookie).
            msg_id = 0

            def _next_id() -> int:
                nonlocal msg_id
                msg_id += 1
                return msg_id

            if cookies:
                await self._send(ws, _next_id(), "Network.enable")
                from urllib.parse import urlsplit

                origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
                for name, value in cookies.items():
                    await self._send(
                        ws,
                        _next_id(),
                        "Network.setCookie",
                        {"name": name, "value": value, "url": origin},
                    )

            await self._send(ws, _next_id(), "Page.enable")
            nav = await self._send(ws, _next_id(), "Page.navigate", {"url": url})
            if nav.get("errorText"):
                raise BrowserError(f"navigasi gagal: {nav['errorText']}")

            # tunggu document.readyState === 'complete' (polling deterministik)
            deadline = t0 + self.render_timeout
            ready = False
            while time.perf_counter() < deadline:
                ready_state = await self._send(
                    ws, _next_id(), "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True},
                )
                if ready_state.get("result", {}).get("value") == "complete":
                    ready = True
                    break
                await asyncio.sleep(0.1)
            if not ready:
                raise BrowserError(f"DOM tidak siap dalam {self.render_timeout}s")

            content = (
                await self._send(
                    ws, _next_id(), "Runtime.evaluate",
                    {"expression": "document.documentElement.outerHTML", "returnByValue": True},
                )
            )["result"]["value"]
            title = (
                await self._send(
                    ws, _next_id(), "Runtime.evaluate",
                    {"expression": "document.title", "returnByValue": True},
                )
            )["result"]["value"]
            final_url = (
                await self._send(
                    ws, _next_id(), "Runtime.evaluate",
                    {"expression": "location.href", "returnByValue": True},
                )
            )["result"]["value"]
            status = (
                await self._send(
                    ws, _next_id(), "Runtime.evaluate",
                    {
                        "expression": "(performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0",
                        "returnByValue": True,
                    },
                )
            )["result"]["value"]

        render_ms = (time.perf_counter() - t0) * 1000
        return RenderResult(
            url=url,
            final_url=final_url,
            status_code=int(status or 0),
            content=content,
            title=title,
            cold_start_ms=self.cold_start_ms,
            render_ms=render_ms,
            chromium_rss_kb=self._chromium_rss_kb(),
        )
