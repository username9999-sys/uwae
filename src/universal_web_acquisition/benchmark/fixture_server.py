"""Deterministic fixture server for transport benchmarks (E5).

Serves fixed byte-for-byte content on localhost so differential
benchmarks are reproducible. Ground truths are exported so the
benchmark runner can verify responses exactly.
"""

import gzip
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from universal_web_acquisition.artifact.identification import PNG_1X1

HTML_BODY = (
    "<!DOCTYPE html>\n"
    "<html><head><title>UWAE Fixture</title></head>\n"
    "<body><h1 id=\"t\">fixture-ok</h1>\n"
    "<a href=\"/html\">self</a><a href=\"https://example.org/ext\">ext</a>\n"
    "</body></html>\n"
).encode("utf-8")

# ~1 MB deterministic payload (B01 large-file variant)
_LARGE_LINE = b"UWAE-large-fixture-line-%06d\n"
LARGE_BODY = b"".join(_LARGE_LINE % i for i in range(35000))

REDIRECT_FINAL_BODY = b"redirect-final-ok"

NOT_FOUND_BODY = b"fixture-404-not-found"

# B08: halaman yang merender konten via JavaScript (bukti eksekusi JS browser).
# Teks gate "please enable javascript" adalah marker js.required pada worker —
# script MENGGANTI teksnya, sehingga hasil render browser bebas marker gate.
JS_BODY = (
    "<!DOCTYPE html>\n"
    "<html><head><title>UWAE JS Fixture</title></head>\n"
    "<body><h1 id=\"t\">please enable javascript to view this page</h1>\n"
    "<script>document.getElementById('t').textContent = 'rendered-by-js';</script>\n"
    "</body></html>\n"
).encode("utf-8")

# Skenario diagnosis §6.1 (A04/A06/A07/A11) — ground truth deterministik untuk
# menguji KLASIFIKASI dan TINDAKAN, bukan hanya keberhasilan akuisisi.
LOGIN_BODY = (
    "<!DOCTYPE html>\n"
    "<html><head><title>Sign in — UWAE Fixture</title></head>\n"
    "<body><form action=\"/login\" method=\"post\">\n"
    "<input type=\"text\" name=\"user\">\n"
    "<input type=\"password\" name=\"pass\">\n"
    "<button>Sign in</button>\n"
    "</form></body></html>\n"
).encode("utf-8")

CHALLENGE_BODY = (
    "<!DOCTYPE html>\n"
    "<html><head><title>Just a moment...</title></head>\n"
    "<body>Checking your browser before accessing.</body></html>\n"
).encode("utf-8")

DENIED_BODY = b"access denied by policy"

RATE_LIMITED_BODY = b"rate limited - slow down"

# A11: body yang TIDAK dapat diurai sebagai HTML — sukses tidak boleh
# dilaporkan hanya karena status 200.
INVALID_HTML_BODY = b"\x00\x01\x02 binary garbage \xff\xfe not html at all"

# A05: resource terproteksi + jalur autentikasi resmi (cookie sesi)
PROTECTED_BODY = b"protected-content-ok"
SESSION_COOKIE = "uwae_session"
SESSION_TOKEN = "valid-token"

# A09: unduhan besar dengan dukungan Range (resume) — body deterministik agar
# sha256 artifact akhir dapat diverifikasi terhadap body sumber.
RANGE_TOTAL = 512 * 1024
RANGE_BODY = bytes(range(256)) * (RANGE_TOTAL // 256)
RANGE_ETAG = '"uwae-large-v1"'

GROUND_TRUTHS = {
    "b01_small_get": {"expect_status": 200, "body": HTML_BODY},
    "b01_large_get": {"expect_status": 200, "body": LARGE_BODY},
    "b04_redirect": {"expect_status": 200, "body": REDIRECT_FINAL_BODY},
    "b06_gzip": {"expect_status": 200, "body": HTML_BODY},
    "b06_brotli": {"expect_status": 200, "body": HTML_BODY},
    "b07_js_render": {"expect_status": 200, "body": JS_BODY},
    "e02_not_found": {"expect_status": 404, "body": NOT_FOUND_BODY},
    "a04_login": {"expect_status": 200, "body": LOGIN_BODY},
    "a06_rate_limited": {"expect_status": 429, "body": RATE_LIMITED_BODY},
    "a07_challenge": {"expect_status": 403, "body": CHALLENGE_BODY},
    "a07_denied": {"expect_status": 403, "body": DENIED_BODY},
    "a11_invalid_html": {"expect_status": 200, "body": INVALID_HTML_BODY},
    "a05_protected": {"expect_status": 200, "body": PROTECTED_BODY},
    "a09_large_download": {"expect_status": 200, "body": RANGE_BODY},
}

SCENARIOS = {
    "b01_small_get": "/html",
    "b01_large_get": "/large",
    "b04_redirect": "/redirect",
    "b06_gzip": "/gzip",
    "b06_brotli": "/brotli",
    "b07_js_render": "/js",
    "e02_not_found": "/missing",
    "a04_login": "/login",
    "a06_rate_limited": "/rate-limited",
    "a07_challenge": "/challenge",
    "a07_denied": "/denied",
    "a11_invalid_html": "/invalid-html",
    "a05_protected": "/protected",
    "a09_large_download": "/large-download",
}


class FixtureHandler(BaseHTTPRequestHandler):
    """Serves deterministic fixture endpoints."""

    # A09: penghitung chunk per sesi uji — koneksi diputus TEPAT SEKALI saat
    # count mencapai fail_after_chunks (simulasi interupsi di tengah unduhan).
    _range_served = {}

    def log_message(self, fmt, *args):  # keep benchmark output clean
        pass

    def _record_request(self, status: int) -> None:
        """Catat request yang benar-benar diterima server (opsional).

        Dibuat untuk benchmark lintas-implementasi: "arm mengklaim me-recovery"
        bukan bukti — yang bukti adalah log sisi server yang menunjukkan
        request apa yang benar-benar terjadi dan cookie apa yang dikirim.
        """
        if not getattr(self.server, "record_requests", False):
            return
        self.server.request_log.append(
            {
                "method": self.command,
                "path": self.path,
                "status": status,
                "cookie": self.headers.get("Cookie") or "",
            }
        )

    def _send(self, status: int, body: bytes, ctype: str, encoding: str = None, headers: dict = None):
        self._record_request(status)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if encoding:
            self.send_header("Content-Encoding", encoding)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        # A09: probe resume — header tanpa body (Accept-Ranges + validator)
        path = self.path.split("?")[0]
        if path == "/large-download":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", RANGE_ETAG)
            self.send_header("Content-Length", str(RANGE_TOTAL))
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/html":
            self._send(200, HTML_BODY, "text/html; charset=utf-8")
        elif path == "/large":
            self._send(200, LARGE_BODY, "application/octet-stream")
        elif path == "/redirect":
            # B04: 3-hop chain 301 -> 302 -> 307 -> final
            self.send_response(301)
            self.send_header("Location", "/hop1")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/hop1":
            self._redirect("/hop2")
        elif path == "/hop2":
            self.send_response(307)
            self.send_header("Location", "/final")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/final":
            self._send(200, REDIRECT_FINAL_BODY, "text/plain")
        elif path == "/gzip":
            self._send(200, gzip.compress(HTML_BODY), "text/html; charset=utf-8", encoding="gzip")
        elif path == "/brotli":
            import brotli
            self._send(200, brotli.compress(HTML_BODY), "text/html; charset=utf-8", encoding="br")
        elif path == "/js":
            self._send(200, JS_BODY, "text/html; charset=utf-8")
        elif path == "/login":
            self._send(200, LOGIN_BODY, "text/html; charset=utf-8")
        elif path == "/rate-limited":
            # A06: 429 + Retry-After — worker wajib menghormati waktu tunggu server
            self._send(429, RATE_LIMITED_BODY, "text/plain", headers={"Retry-After": "1"})
        elif path == "/denied":
            # A07 pasangan ground-truth: 403 polos TANPA marker challenge
            self._send(403, DENIED_BODY, "text/plain")
        elif path == "/challenge":
            # A07: interstitial challenge (403 + signature di body)
            self._send(403, CHALLENGE_BODY, "text/html; charset=utf-8")
        elif path == "/invalid-html":
            # A11: 200 dengan body yang bukan HTML valid
            self._send(200, INVALID_HTML_BODY, "text/html; charset=utf-8")
        elif path == "/hang":
            # Fault injection (TEXT.md E5 — failure isolation): server tidak
            # merespons dalam waktu klien → memicu timeout. Durasi dibatasi
            # agar benchmark tidak menggantung lama.
            from urllib.parse import parse_qs, urlsplit

            query = parse_qs(urlsplit(self.path).query)
            seconds = float((query.get("seconds") or ["5"])[0])
            time.sleep(min(seconds, 30.0))
            self._send(200, HTML_BODY, "text/html; charset=utf-8")
        elif path == "/protected":
            # A05: resource yang memerlukan sesi sah — 401 tanpa cookie valid.
            # Token aktif hidup di state server (bukan konstanta) supaya
            # benchmark dapat mencabut sesi sisi server lewat rotasi token
            # tanpa menambah endpoint HTTP baru.
            cookie = self.headers.get("Cookie") or ""
            active = getattr(self.server, "session_token", SESSION_TOKEN)
            if f"{SESSION_COOKIE}={active}" in cookie:
                self._send(200, PROTECTED_BODY, "text/plain")
            else:
                self._send(401, b"unauthorized: session required", "text/plain")
        elif path == "/session-login":
            # A05: jalur autentikasi resmi — menerbitkan cookie sesi
            active = getattr(self.server, "session_token", SESSION_TOKEN)
            self._send(
                200,
                b"login-ok",
                "text/plain",
                headers={"Set-Cookie": f"{SESSION_COOKIE}={active}; Path=/"},
            )
        elif path == "/file-no-ext":
            # E2: file tanpa ekstensi — identifikasi harus dari signature
            self._send(
                200,
                PNG_1X1,
                "application/octet-stream",
                headers={"Content-Disposition": 'attachment; filename="download"'},
            )
        elif path == "/file-wrong-mime":
            # E2: MIME salah — signature PNG menang + konflik tercatat
            self._send(200, PNG_1X1, "text/plain")
        elif path == "/page1":
            # Discovery graph: tautan internal (/page2), self dengan fragmen,
            # eksternal, dan mailto — bahan uji extract_links + follow-links
            host = self.headers.get("Host") or "127.0.0.1"
            body = (
                "<!DOCTYPE html>\n"
                "<html><body>"
                '<a href="/page2">next</a>'
                f'<a href="http://{host}/page1#top">self</a>'
                '<a href="https://example.org/out">ext</a>'
                '<a href="mailto:x@y.z">mail</a>'
                "</body></html>\n"
            ).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")
        elif path == "/page2":
            host = self.headers.get("Host") or "127.0.0.1"
            body = (
                "<!DOCTYPE html>\n"
                "<html><body>"
                f'<a href="http://{host}/page1">back</a>'
                "</body></html>\n"
            ).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")
        elif path == "/large-download":
            # A09: unduhan besar dengan dukungan Range; hook uji
            # ?session=X&fail_after_chunks=N memutus koneksi TEPAT SEKALI pada
            # chunk ke-N (simulasi unduhan terputus di tengah jalan).
            from urllib.parse import parse_qs, urlsplit

            query = parse_qs(urlsplit(self.path).query)
            session = (query.get("session") or [None])[0]
            fail_after = (query.get("fail_after_chunks") or [None])[0]
            range_header = self.headers.get("Range") or ""
            if range_header.startswith("bytes="):
                served = self._range_served.get(session, 0) + 1
                self._range_served[session] = served
                if fail_after and session and served == int(fail_after):
                    # putus mentah — klien melaporkan kegagalan jaringan
                    self.close_connection = True
                    try:
                        self.connection.close()
                    except Exception:
                        pass
                    return
                spec = range_header.split("=", 1)[1]
                start_s, _, end_s = spec.partition("-")
                start = int(start_s)
                end = min(int(end_s), RANGE_TOTAL - 1) if end_s else RANGE_TOTAL - 1
                end = min(end, RANGE_TOTAL - 1)
                self.send_response(206)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header(
                    "Content-Range", f"bytes {start}-{end}/{RANGE_TOTAL}"
                )
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("ETag", RANGE_ETAG)
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                self.wfile.write(RANGE_BODY[start : end + 1])
            else:
                self._send(
                    200,
                    RANGE_BODY,
                    "application/octet-stream",
                    headers={
                        "Accept-Ranges": "bytes",
                        "ETag": RANGE_ETAG,
                    },
                )
        elif path == "/no-range":
            # A09 pasangan ground-truth: server TANPA dukungan resume —
            # strategi yang benar adalah unduh penuh, bukan gabung spekulatif
            self._send(200, RANGE_BODY, "application/octet-stream")
        elif path == "/robots.txt":
            # Discovery: robots dengan satu Disallow + satu Sitemap (URL
            # absolut dibangun dari Host header agar deterministik per run)
            host = self.headers.get("Host") or "127.0.0.1"
            robots = (
                "User-agent: *\n"
                "Allow: /\n"
                "Disallow: /private\n"
                f"Sitemap: http://{host}/sitemap-index.xml\n"
            )
            self._send(200, robots.encode("utf-8"), "text/plain")
        elif path == "/sitemap-index.xml":
            host = self.headers.get("Host") or "127.0.0.1"
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"<sitemap><loc>http://{host}/sitemap-child.xml</loc></sitemap>\n"
                "</sitemapindex>\n"
            )
            self._send(200, body.encode("utf-8"), "application/xml")
        elif path == "/sitemap-child.xml":
            host = self.headers.get("Host") or "127.0.0.1"
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"<url><loc>http://{host}/html</loc></url>\n"
                f"<url><loc>http://{host}/private/secret</loc></url>\n"
                f"<url><loc>http://{host}/sitemap-child.xml</loc></url>\n"
                "<url><loc>https://external.example.com/page</loc></url>\n"
                "</urlset>\n"
            )
            self._send(200, body.encode("utf-8"), "application/xml")
        elif path == "/alt/sitemap.xml":
            # Discovery: fallback tanpa robots — origin + /sitemap.xml
            host = self.headers.get("Host") or "127.0.0.1"
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"<url><loc>http://{host}/html</loc></url>\n"
                "</urlset>\n"
            )
            self._send(200, body.encode("utf-8"), "application/xml")
        elif path.startswith("/mirror/"):
            # Soft-404 test: path apa pun di bawah /mirror mengembalikan body
            # identik — dua path berbeda, SHA-256 sama (bukti deteksi lintas-path)
            self._send(200, HTML_BODY, "text/html; charset=utf-8")
        else:
            self._send(404, NOT_FOUND_BODY, "text/plain")


class FixtureServer:
    """Context-managed deterministic fixture server on localhost."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        record_requests: bool = False,
    ):
        self.host = host
        self.port = port
        self._httpd = None
        self._thread = None
        self._record_requests = record_requests
        self.request_log: List[dict] = []

    def __enter__(self):
        self._httpd = ThreadingHTTPServer((self.host, self.port), FixtureHandler)
        self._httpd.daemon_threads = True
        self._httpd.session_token = SESSION_TOKEN
        self._httpd.session_generation = 0
        # Handler membaca flag ini dari objek server, BUKAN dari FixtureServer
        # — tanpa ini log request tetap kosong dan bukti sisi server hilang.
        self._httpd.record_requests = self._record_requests
        # Log harus berupa LIST YANG SAMA dengan yang dibaca parent; tanpa
        # rujukan ini handler raises AttributeError sebelum respons terkirim
        # dan klien melihat EOF.
        self._httpd.request_log = self.request_log
        # port=0 berarti OS memilih port bebas; tanpa ini base URL yang
        # dikembalikan menunjuk port 0 dan tidak bisa dipakai.
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return f"http://{self.host}:{self.port}"

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        return False

    @property
    def active_session_token(self) -> str:
        """Token sesi yang saat ini valid di sisi server."""
        return getattr(self._httpd, "session_token", SESSION_TOKEN)

    def reset_session(self) -> None:
        """Kembalikan state sesi ke kondisi awal.

        Dipanggil benchmark sebelum tiap arm run supaya kedua implementasi
        mulai dari kondisi yang benar-benar identik — tanpa ini, arm pertama
        yang me-recovery akan mewarisi token baru milik arm sebelumnya.
        """
        self._httpd.session_token = SESSION_TOKEN
        self._httpd.session_generation = 0

    def expire_session(self) -> str:
        """Cabut sesi aktif di sisi server (rotasi token).

        Klien yang masih memegang cookie lama menerima 401 meskipun cookie-nya
        sendiri secara sintaksis masih valid — persis situasi "sesi kedaluwarsa
        di server sementara klien tidak tahu". Token baru yang diterbitkan
        endpoint login berikutnya adalah token yang aktif.

        Returns:
            Token sesi yang baru aktif.
        """
        generation = getattr(self._httpd, "session_generation", 0) + 1
        self._httpd.session_generation = generation
        self._httpd.session_token = f"{SESSION_TOKEN}-v{generation + 1}"
        return self._httpd.session_token
