"""Fixture server protokol POST untuk benchmark E20 (paritas kompetitif).

Modul INI BARU. ``fixture_server.py`` milik proyek tidak disentuh — file itu
milik pengguna dan tidak boleh diedit, distage, atau di-revert. Fixture POST
because endpoints POST tidak boleh disisipkan ke sana, dan menyisipkannya
justru berarti mencampur dua concern: fixture GET/umum (E5/E14/E18) dengan
fixture protokol POST (E20).

Prinsip yang dipegang modul ini
------------------------------
1. **Ground truth milik protokol fixture, bukan milik engine yang diuji.**
   Setiap endpoint punya satu protokolt yang eksplisit: method, content-type,
   header wajib, dan body. Respons "sukses" adalah body KONSTAN per skenario,
   bukan hasil perhitungan dari request. Jadi byte yang dibandingkan di
   benchmark adalah konstanta yang disebutkan di sini, bukan sesuatu yang
   berubah kalau engine berubah.

2. **Setiap pelanggaran protokol punya status + body sendiri.** Method bukan
   POST -> 405, content-type salah -> 415, header wajib hilang/salah -> 400,
   body tidak cocok -> 400. Engine yang diam-diam jatuh ke GET akan menerima
   405 dengan body yang berbeda dari ground truth, sehingga run-nya gagal
   sebagai run yang gagal — bukan lolos karena "responsnya 200 juga".

3. **User-Agent TIDAK ikut dalam ground truth.** Dua arm memakai library
   berbeda dengan User-Agent bawaan berbeda (curl_cffi meniru Chrome,
   requests bawaan Botasaurus memakai Firefox). Kalau UA ikut menentukan
   respons, perbandingan byte akan gagal karena alasan yang tidak berkaitan
   dengan kapabilitas POST. UA tetap DICATAT di log sisi server sebagai
   bukti kondisi device, tapi tidak pernah jadi bagian dari kriteria.

4. **Log sisi server adalah bukti, bukan klaim.** Setiap request yang benar
  -benar arrive dicatat: method, path, content-type, sha256 body, jumlah
   byte, dan vonis protokol. "Arm mengklaim mengirim POST" bukan bukti;
   apa yang arrive di socket adalah bukti.
"""

import hashlib
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Protokol POST — sumber kebenaran ground truth
# ---------------------------------------------------------------------------

#: Body konstan per skenario. Body ini TIDAK bergantung pada request: jadi
#: perbandingan byte-for-byte antar arm adalah perbandingan konstanta yang
#: sama, bukan perbandingan echo yang bisa ikut berubah bersama engine.
FORM_OK_BODY = b"post-form-ok\n"
JSON_OK_BODY = b"post-json-ok\n"
EMPTY_OK_BODY = b"post-empty-ok\n"
LARGE_OK_BODY = b"post-large-ok\n"
MULTIPART_OK_BODY = b"post-multipart-ok\n"
REDIRECT_OK_BODY = b"post-redirect-landed-ok\n"
FORM_PAGE_BODY = (
    b"<!doctype html><html><body>"
    b'<form id="f" method="post" action="/post/form-page-target">'
    b'<input name="name" value="uwae">'
    b'<input name="value" value="42">'
    b'<input type="submit" id="go" value="go">'
    b"</form></body></html>"
)

#: Body untuk pelanggaran protokol. Masing-masing BEDA dari body sukses, jadi
#: satu respons salah sudah cukup menggagalkan run.
METHOD_NOT_ALLOWED_BODY = b"post-method-not-allowed\n"
UNSUPPORTED_MEDIA_TYPE_BODY = b"post-unsupported-media-type\n"
HEADER_MISMATCH_BODY = b"post-header-mismatch\n"
PAYLOAD_MISMATCH_BODY = b"post-payload-mismatch\n"
NOT_FOUND_BODY = b"post-not-found\n"

#: Payload besar deterministik (ASCII) — menguji integritas body POST pada
#: ukuran yang jauh melampaui buffer kecil, bukan cuma payload pendek.
_LARGE_LINE = b"uwae-post-large-fixture-line-%06d\n"
LARGE_POST_BODY = b"".join(_LARGE_LINE % i for i in range(7000))

#: Boundary multipart deterministik — bagian dari protokol, jadi ground truth
#: bisa membandingkan body mentah yang benar-benar arrive (termasuk boundary).
MULTIPART_BOUNDARY = b"----uwae-post-fixture-boundary-7d1a"
#: Field file deterministik: nama, nama file, content-type bagian, dan isi.
#: Di-encode manual supaya body yang dibandingkan byte-for-byte adalah
#: konstanta yang sama untuk kedua arm — library mana pun yang dipakai,
#: body yang benar harus identik dengan konstanta ini.
MULTIPART_FILE_NAME = b"report.txt"
MULTIPART_FILE_CONTENT = b"uwae multipart fixture payload\nline two\n"
MULTIPART_TEXT_FIELD = b"note"
MULTIPART_TEXT_VALUE = b"hello from uwae"
MULTIPART_BODY = (
    b"--" + MULTIPART_BOUNDARY + b"\r\n"
    b'Content-Disposition: form-data; name="' + MULTIPART_TEXT_FIELD + b'"\r\n'
    b"\r\n"
    + MULTIPART_TEXT_VALUE + b"\r\n"
    b"--" + MULTIPART_BOUNDARY + b"\r\n"
    b'Content-Disposition: form-data; name="file"; filename="' + MULTIPART_FILE_NAME + b'"\r\n'
    b"Content-Type: text/plain\r\n"
    b"\r\n"
    + MULTIPART_FILE_CONTENT + b"\r\n"
    b"--" + MULTIPART_BOUNDARY + b"--\r\n"
)

#: Protokol per path. ``content_type=None`` berarti tidak ada content-type
#: yang diwajibkan (body kosong tidak perlu tipe). Parameter ``; charset=..``
#: diabaikan saat pencocokan — beberapa library menambahkannya sendiri.
#: ``content_type_prefix=True`` berarti pencocokan hanya pada prefix sebelum
#: ``;`` (dipakai multipart karena boundary ikut di header).
POST_PROTOCOL: Dict[str, Dict] = {
    "/post/form": {
        "method": "POST",
        "content_type": "application/x-www-form-urlencoded",
        "headers": {"X-Uwae-Protocol": "p01-post-form"},
        "body": b"name=uwae&value=42",
        "ok_body": FORM_OK_BODY,
    },
    "/post/json": {
        "method": "POST",
        "content_type": "application/json",
        "headers": {"X-Uwae-Protocol": "p02-post-json"},
        "body": b'{"name":"uwae","value":42}',
        "ok_body": JSON_OK_BODY,
    },
    "/post/empty": {
        "method": "POST",
        "content_type": None,
        "headers": {"X-Uwae-Protocol": "p03-post-empty"},
        "body": b"",
        "ok_body": EMPTY_OK_BODY,
    },
    "/post/large": {
        "method": "POST",
        "content_type": "application/octet-stream",
        "headers": {"X-Uwae-Protocol": "p04-post-large-body"},
        "body": LARGE_POST_BODY,
        "ok_body": LARGE_OK_BODY,
    },
    # E21: multipart/form-data — body dibandingkan byte-for-byte terhadap
    # konstanta MULTIPART_BODY, jadi boundary dan urutan field ikut diuji.
    "/post/multipart": {
        "method": "POST",
        "content_type": "multipart/form-data",
        "content_type_prefix": True,
        "headers": {"X-Uwae-Protocol": "p05-post-multipart"},
        "body": MULTIPART_BODY,
        "ok_body": MULTIPART_OK_BODY,
        "expect_boundary": MULTIPART_BOUNDARY.decode("ascii"),
    },
    # E21: redirect 307 — Location menuju /post/redirect-target. Yang diukur
    # di sini adalah apakah METHOD dan BODY dipertahankan setelah redirect
    # (307 mensyaratkan itu); ground truth ada di target, bukan di 307 itu
    # sendiri, jadi path ini tidak masuk POST_PROTOCOL.
    "/post/redirect307": {
        "method": "POST",
        # Content-Type dipakai supaya klien yang mengikuti 307 dengan benar
        # (mempertahankan method+body+header) juga mengirimnya ke target;
        # path redirect sendiri tidak memvalidasi content_type.
        "content_type": "application/x-www-form-urlencoded",
        "redirect": {"status": 307, "location": "/post/redirect-target"},
        "headers": {"X-Uwae-Protocol": "p06-post-redirect307"},
        "body": b"redirect-payload=42",
    },
    "/post/redirect-target": {
        "method": "POST",
        "content_type": "application/x-www-form-urlencoded",
        "headers": {"X-Uwae-Protocol": "p06-post-redirect307"},
        "body": b"redirect-payload=42",
        "ok_body": REDIRECT_OK_BODY,
    },
    # E22: halaman form untuk arm browser — GET biasa yang mengembalikan
    # FORM_PAGE_BODY; browser mengisi dan submit form itu sendiri.
    "/post/form-page": {
        "method": "GET",
        "content_type": "text/html",
        "headers": {},
        "body": b"",
        "ok_body": FORM_PAGE_BODY,
        "is_page": True,
    },
    # Target submit form browser — sama dengan /post/form tapi tanpa header
    # protokol wajib (browser tidak bisa mengirim header kustom), jadi
    # protokolnya longgar: hanya method + body yang dicocokkan.
    "/post/form-page-target": {
        "method": "POST",
        "content_type": "application/x-www-form-urlencoded",
        "headers": {},
        "body": b"name=uwae&value=42",
        "ok_body": FORM_OK_BODY,
        "lenient_headers": True,
    },
}

#: Skenario benchmark -> path fixture. Identik untuk kedua arm.
POST_SCENARIOS: Dict[str, str] = {
    "p01_post_form": "/post/form",
    "p02_post_json": "/post/json",
    "p03_post_empty": "/post/empty",
    "p04_post_large_body": "/post/large",
}

#: Skenario E21/E22 (ekstensi POST) — dipisah supaya E20 lama tidak berubah
#: fingerprint-nya; slot baru memakai perluasan ini saja.
POST_EXT_SCENARIOS: Dict[str, str] = {
    "p05_post_multipart": "/post/multipart",
    "p06_post_redirect307": "/post/redirect307",
    "p07_post_browser_form": "/post/form-page",
}


def request_headers(scenario_id: str) -> Dict[str, str]:
    """Header lengkap yang harus dikirim untuk satu skenario.

    ``Content-Type`` adalah bagian dari protokol dan WAJIB dikirim eksplisit.
    Kalau tidak, tiap library memakai default-nya sendiri: curl_cffi menebak
    ``application/octet-stream`` untuk data binary, sedangkan requests tidak
    memasang apa pun untuk ``data=bytes``. Perbandingan byte lalu mengukur
    tebakan library -- bukan kapabilitas POST. Karena itu Content-Type
    dikirim sebagai header eksplisit oleh kedua arm, persis sama.
    """
    spec = POST_PROTOCOL[POST_SCENARIOS[scenario_id]]
    headers = dict(spec["headers"])
    if spec["content_type"] is not None:
        headers["Content-Type"] = spec["content_type"]
    return headers


#: Ground truth per skenario — diturunkan dari protokol di atas.
POST_GROUND_TRUTHS: Dict[str, Dict] = {
    sid: {
        "expect_status": 200,
        "body": POST_PROTOCOL[path]["ok_body"],
        "expect_content_type": POST_PROTOCOL[path]["content_type"],
        "expect_headers": request_headers(sid),
        "expect_body_sha256": hashlib.sha256(POST_PROTOCOL[path]["body"]).hexdigest(),
        "expect_body_bytes": len(POST_PROTOCOL[path]["body"]),
    }
    for sid, path in POST_SCENARIOS.items()
}


def ext_request_headers(scenario_id: str) -> Dict[str, str]:
    """Header untuk skenario ekstensi (E21/E22).

    Sama seperti ``request_headers`` tapi untuk ``POST_EXT_SCENARIOS``.
    Untuk multipart, boundary dikirim sebagai bagian dari Content-Type
    (``multipart/form-data; boundary=...``) — boundary adalah bagian dari
    ground truth body, jadi ia juga bagian dari header yang dibandingkan.
    """
    spec = POST_PROTOCOL[POST_EXT_SCENARIOS[scenario_id]]
    headers = dict(spec["headers"])
    # Path redirect (p06) memang tidak punya content_type — body-nya hanya
    # dicek di target redirect. ``.get`` dipakai supaya path itu tidak crash
    # saat ground truth dibangun.
    content_type = spec.get("content_type")
    if content_type is not None:
        if spec.get("content_type_prefix") and spec.get("expect_boundary"):
            headers["Content-Type"] = (
                f"{content_type}; boundary={spec['expect_boundary']}"
            )
        else:
            headers["Content-Type"] = content_type
    return headers


#: Ground truth untuk skenario ekstensi (E21/E22).
#: - p05 multipart: body mentah dibandingkan byte-for-byte (boundary ikut).
#: - p06 redirect307: ground truth adalah respons AKHIR setelah redirect
#:   (status 200 + REDIRECT_OK_BODY); observasi server membuktikan dua hop:
#:   POST /post/redirect307 (307) lalu POST /post/redirect-target (200).
#: - p07 browser form: ground truth adalah FORM_OK_BODY dari target submit;
#:   halaman form sendiri adalah GET yang mengembalikan FORM_PAGE_BODY.
POST_EXT_GROUND_TRUTHS: Dict[str, Dict] = {
    "p05_post_multipart": {
        "expect_status": 200,
        "body": MULTIPART_OK_BODY,
        "expect_content_type": "multipart/form-data",
        "expect_headers": ext_request_headers("p05_post_multipart"),
        "expect_body_sha256": hashlib.sha256(MULTIPART_BODY).hexdigest(),
        "expect_body_bytes": len(MULTIPART_BODY),
        "expect_boundary": MULTIPART_BOUNDARY.decode("ascii"),
    },
    "p06_post_redirect307": {
        "expect_status": 200,
        "body": REDIRECT_OK_BODY,
        "expect_content_type": "application/x-www-form-urlencoded",
        "expect_headers": ext_request_headers("p06_post_redirect307"),
        "expect_body_sha256": hashlib.sha256(b"redirect-payload=42").hexdigest(),
        "expect_body_bytes": len(b"redirect-payload=42"),
        "redirect_chain": [
            {"path": "/post/redirect307", "status": 307},
            {"path": "/post/redirect-target", "status": 200},
        ],
    },
    "p07_post_browser_form": {
        "expect_status": 200,
        "body": FORM_OK_BODY,
        "expect_content_type": "application/x-www-form-urlencoded",
        "expect_headers": {},
        "expect_body_sha256": hashlib.sha256(b"name=uwae&value=42").hexdigest(),
        "expect_body_bytes": len(b"name=uwae&value=42"),
        "page_path": "/post/form-page",
        "target_path": "/post/form-page-target",
    },
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    """Baca body request sesuai framing HTTP.

    Dua framing yang mungkin muncul: ``Content-Length`` (dipakai kedua arm)
    dan ``chunked`` (dipakai klien lain). Tanpa dukungan chunked, request
    chunked akan terbaca sebagai body kosong dan menghasilkan vonis
    "payload_mismatch" yang PALSU — bukti yang salah lebih berbahaya daripada
    tidak ada bukti.
    """
    raw_length = handler.headers.get("Content-Length")
    if raw_length is not None:
        try:
            length = int(raw_length)
        except ValueError:
            length = 0
        return handler.rfile.read(length) if length > 0 else b""
    encoding = (handler.headers.get("Transfer-Encoding") or "").strip().lower()
    if encoding == "chunked":
        chunks: List[bytes] = []
        while True:
            line = handler.rfile.readline()
            if not line:
                break
            try:
                size = int(line.split(b";")[0].strip(), 16)
            except ValueError:
                break
            if size == 0:
                handler.rfile.readline()
                break
            chunks.append(handler.rfile.read(size))
            handler.rfile.readline()
        return b"".join(chunks)
    return b""


def _evaluate_protocol(
    spec: Dict, headers, body: bytes
) -> Tuple[int, bytes, str]:
    """Cek request terhadap protokol; kembalikan (status, body, vonis).

    Urutan pemeriksaan ditetapkan di sini, bukan di engine mana pun, supaya
    kedua arm menerima vonis yang sama persis untuk request yang sama.
    """
    # Content-Type request hanya divalidasi untuk request yang MEMANG
    # membawa body (POST). Browser mengirim GET tanpa Content-Type, jadi
    # route halaman (is_page) tidak boleh divalidasi content_type request —
    # kalau divalidasi, GET browser akan menerima 415.
    if spec["content_type"] is not None and not spec.get("is_page"):
        actual = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if spec.get("content_type_prefix"):
            # multipart: boundary ikut di parameter header, jadi yang
            # dicocokkan hanya prefix sebelum ';'.
            if actual != spec["content_type"]:
                return 415, UNSUPPORTED_MEDIA_TYPE_BODY, "content_type_mismatch"
        elif actual != spec["content_type"]:
            return 415, UNSUPPORTED_MEDIA_TYPE_BODY, "content_type_mismatch"
    for name, value in spec["headers"].items():
        if headers.get(name) != value:
            return 400, HEADER_MISMATCH_BODY, "header_mismatch"
    if body != spec["body"]:
        return 400, PAYLOAD_MISMATCH_BODY, "payload_mismatch"
    return 200, spec["ok_body"], "ok"


class PostFixtureHandler(BaseHTTPRequestHandler):
    """Melayani protokol POST deterministik dan mencatat apa yang arrive."""

    def log_message(self, fmt, *args):  # keep benchmark output clean
        pass

    def _send(self, status: int, body: bytes, extra_headers=None, content_type=None) -> None:
        self.send_response(status)
        # Halaman form WAJIB disajikan sebagai text/html — kalau text/plain,
        # chromium tidak merender elemen <form> dan submit tidak bisa diuji.
        self.send_header("Content-Type", content_type or "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _record(
        self, path: str, body: bytes, status: int, verdict: str
    ) -> None:
        log = getattr(self.server, "request_log", None)
        if log is None:
            return
        log.append(
            {
                "at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                # Epoch float dipakai harness untuk memetakan observasi ke run
                # yang tepat. String ISO bisa menyesatkan kalau microsecond-nya
                # kebetulan nol (isoformat() lalu menghilangkan bagian itu),
                # jadi perbandingan numerik dipakai untuk pemetaan.
                "at_epoch": time.time(),
                "method": self.command,
                "path": path,
                "status": status,
                "protocol_verdict": verdict,
                "content_type": self.headers.get("Content-Type"),
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "body_bytes": len(body),
                "user_agent": self.headers.get("User-Agent"),
            }
        )

    def _handle(self) -> None:
        path = self.path.split("?")[0]
        spec = POST_PROTOCOL.get(path)
        body = _read_body(self)
        if spec is None:
            status, payload, verdict = 404, NOT_FOUND_BODY, "unknown_path"
        elif self.command != spec["method"]:
            status, payload, verdict = 405, METHOD_NOT_ALLOWED_BODY, "method_not_allowed"
        elif "redirect" in spec:
            # 307: body WAJIB dibaca dulu (koneksi bisa ditutup kalau tidak),
            # lalu redirect dengan Location absolut. Ground truth ada di
            # target — path ini hanya pengarah.
            redir = spec["redirect"]
            location = "http://%s%s" % (self.headers.get("Host", "127.0.0.1"), redir["location"])
            self._record(path, body, redir["status"], "redirect_issued")
            self._send(
                redir["status"],
                b"",
                extra_headers={"Location": location},
            )
            return
        else:
            status, payload, verdict = _evaluate_protocol(spec, self.headers, body)
        self._record(path, body, status, verdict)
        # Content-Type respons diambil dari protokol (text/html untuk halaman
        # form, text/plain untuk yang lain) — halaman form dengan text/plain
        # tidak akan dirender chromium sebagai form. ``spec`` bisa None untuk
        # path tak dikenal (mis. /favicon.ico yang diminta browser otomatis),
        # jadi guard dulu.
        resp_ct = spec.get("content_type") if (spec is not None and spec.get("is_page")) else None
        self._send(status, payload, content_type=resp_ct)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle


class PostFixtureServer:
    """Context-managed fixture protokol POST di localhost.

    Port default 0 (dipilih OS) supaya harness ini tidak pernah bentrok
    dengan fixture umum di port 8765 — dua pytest paralel adalah kondisi
    yang sudah pernah melukai repo ini.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        record_requests: bool = True,
    ):
        self.host = host
        self.port = port
        self._httpd = None
        self._thread = None
        self._record_requests = record_requests
        self.request_log: List[dict] = []

    def __enter__(self) -> str:
        self._httpd = ThreadingHTTPServer((self.host, self.port), PostFixtureHandler)
        self._httpd.daemon_threads = True
        self._httpd.request_log = self.request_log
        self._httpd.record_requests = self._record_requests
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()
        return f"http://{self.host}:{self.port}"

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        return False

    def observations(self) -> List[dict]:
        """Salinan log request — pemanggil tidak boleh mengubah log asli."""
        return list(self.request_log)

    def observations_between(self, start: str, end: str) -> List[dict]:
        """Observasi yang timestamp-nya berada di dalam [start, end] (ISO UTC).

        Dipakai harness untuk memisahkan observasi milik satu arm dari arm
        lain tanpa MELUBAH request yang dikirim — memisahkan lewat header
        khusus akan membuat request kedua arm berbeda dari yang pertama dan
        merusak syarat "targets identik".
        """
        return [
            entry
            for entry in self.request_log
            if start <= entry["at"] <= end
        ]


def protocol_summary(entries: List[dict]) -> Dict[str, object]:
    """Ringkasan observasi sisi server untuk publish ke evidence.

    Dipakai untuk menjawab pertanyaan "apa yang benar-benar arrive", bukan
    "apa yangDiklaim arm".
    """
    methods: Dict[str, int] = {}
    verdicts: Dict[str, int] = {}
    for entry in entries:
        methods[entry["method"]] = methods.get(entry["method"], 0) + 1
        verdicts[entry["protocol_verdict"]] = (
            verdicts.get(entry["protocol_verdict"], 0) + 1
        )
    return {
        "observations": len(entries),
        "methods_observed": methods,
        "protocol_verdicts": verdicts,
        "distinct_user_agents": sorted(
            {entry["user_agent"] for entry in entries if entry.get("user_agent")}
        ),
    }


def expected_observation(scenario_id: str) -> Optional[Dict[str, object]]:
    """Observasi server-side yang diharapkan untuk satu skenario.

    Dipakai harness sebagai pembanding: run yang arm-nya melaporkan sukses
    TAPI server tidak melihat POST dengan body yang benar adalah bukti yang
    saling bertentangan, dan harus dipublikasikan sebagai such.
    """
    path = POST_SCENARIOS.get(scenario_id)
    if path is None:
        return None
    spec = POST_PROTOCOL[path]
    return {
        "method": spec["method"],
        "path": path,
        "content_type": spec["content_type"],
        "body_sha256": hashlib.sha256(spec["body"]).hexdigest(),
        "body_bytes": len(spec["body"]),
        "protocol_verdict": "ok",
    }
