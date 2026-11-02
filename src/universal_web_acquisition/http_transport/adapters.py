"""Concrete transport adapters (Fase 2 implementation, ADR-011).

curl_cffi is the primary transport (only verified TLS-fingerprint layer on this
platform); httpx and requests are fallbacks. Every adapter:

- implements the ADR-003 contract (``acquire``/``can_handle``),
- publishes ``TransportCapability`` metadata,
- classifies failures into bounded ``ReasonCode`` values (never generic),
- overrides the User-Agent (E2 finding: default UAs leak platform details).
"""

import abc
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx

from universal_web_acquisition.access.model import ReasonCode
from universal_web_acquisition.artifact.model import Artifact
from universal_web_acquisition.artifact.storage import ArtifactStorage
from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.http_transport.adapter import TransportAdapter
from universal_web_acquisition.http_transport.contracts import RequestSpec
from universal_web_acquisition.http_transport.registry import (
    TransportCapability,
    TransportRegistry,
)

DEFAULT_USER_AGENT = "UniversalWebAcquisitionEngine/0.2.0"


class TransportFailure(Exception):
    """Kegagalan transport dengan reason code berbatas — bukan exception generik.

    ``headers``/``body`` (dipotong ``_FAILURE_BODY_LIMIT``) ikut dibawa agar
    diagnosis A06/A07 dapat membedakan 429+Retry-After, 403 polos, dan
    interstitial challenge — bukan sekadar "HTTP error".
    """

    def __init__(
        self,
        reason_code: ReasonCode,
        message: str,
        status_code: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
    ):
        super().__init__(message)
        self.reason_code = reason_code
        self.status_code = status_code
        self.headers = headers or {}
        self.body = body


@dataclass(frozen=True)
class RawResponse:
    status_code: int
    content: bytes
    headers: Dict[str, str]
    final_url: str


class BaseHttpAdapter(TransportAdapter):
    """Fondasi adapter HTTP: fetch → klasifikasi → Artifact → storage."""

    name: str = "base"
    timeout_seconds: float = 30.0
    user_agent: str = DEFAULT_USER_AGENT

    @property
    @abc.abstractmethod
    def capabilities(self) -> TransportCapability:
        """Metadata kapabilitas yang diiklankan (ADR-011)."""

    @abc.abstractmethod
    def fetch(
        self,
        url: str,
        cookies: Optional[Dict[str, str]] = None,
        *,
        method: str = "GET",
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> RawResponse:
        """Satu permintaan HTTP sinkron; raise pada kegagalan jaringan.

        ``method``/``body``/``headers`` adalah parameter keyword-only dengan
        default ``GET``, jadi setiap call site lama (yang hanya punya URL dan
        cookies) tetap berjalan tanpa perubahan — jalur GET yang sudah
        terukur E18/E19 tidak tersentuh oleh penambahan POST.
        """

    def can_handle(self, url: str) -> bool:
        return urlparse(url).scheme in ("http", "https")

    # -- klasifikasi ke ReasonCode berbatas --

    def classify_status(self, status_code: int) -> Optional[ReasonCode]:
        if 200 <= status_code < 300:
            return None
        if status_code == 429:
            return ReasonCode.HTTP_429
        if 400 <= status_code < 500:
            return ReasonCode.HTTP_4XX
        if 500 <= status_code < 600:
            return ReasonCode.HTTP_5XX
        return ReasonCode.HTTP_4XX

    def classify_exception(self, exc: Exception) -> ReasonCode:
        msg = str(exc).lower()
        if isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg:
            return ReasonCode.TIMEOUT
        if (
            "getaddrinfo" in msg
            or "name or service not known" in msg
            or "nodename nor servname" in msg
            or ("lookup" in msg and "no such host" in msg)
            or "could not resolve host" in msg
            or "failed to resolve" in msg
            or "temporary failure in name resolution" in msg
        ):
            return ReasonCode.DNS_FAILURE
        if "ssl" in msg or "certificate" in msg or "tls" in msg:
            return ReasonCode.TLS_ERROR
        return ReasonCode.CONNECTION_ERROR

    # -- kontrak ADR-003 --

    async def acquire(
        self,
        job: Job,
        storage: ArtifactStorage,
        cookies: Optional[Dict[str, str]] = None,
    ) -> Artifact:
        # RequestSpec = deklarasi satu percobaan HTTP yang dapat diaudit.
        # Job (method/body/headers) diterjemahkan ke sini sebelum wire, jadi
        # kontrak ini bukan lagi dekorasi — dia yang mendeskripsikan request.
        spec = RequestSpec(
            url=job.url,
            method=job.method,
            headers=dict(job.headers or {}),
            cookies=dict(cookies or {}),
            body=job.body,
        )
        try:
            resp = self.fetch(
                spec.url,
                cookies=spec.cookies or None,
                method=spec.method,
                body=spec.body,
                headers=spec.headers or None,
            )
        except Exception as exc:
            raise TransportFailure(
                self.classify_exception(exc), f"{type(exc).__name__}: {exc}"
            ) from exc

        reason = self.classify_status(resp.status_code)
        if reason is not None:
            raise TransportFailure(
                reason,
                f"HTTP {resp.status_code} untuk {job.url}",
                status_code=resp.status_code,
                headers=resp.headers,
                body=resp.content[:4096],
            )

        artifact = Artifact(
            job_id=job.job_id,
            url=resp.final_url,
            content=resp.content,
            content_type=resp.headers.get("content-type", "application/octet-stream"),
            status_code=resp.status_code,
            headers=resp.headers,
        )
        return await storage.store(artifact)


class CurlCffiAdapter(BaseHttpAdapter):
    """Primary transport (ADR-011): satu-satunya lapisan TLS fingerprint terverifikasi."""

    name = "curl_cffi"

    @property
    def capabilities(self) -> TransportCapability:
        return TransportCapability(tls_fingerprint=True, http2=True, brotli=True)

    def fetch(
        self,
        url: str,
        cookies: Optional[Dict[str, str]] = None,
        *,
        method: str = "GET",
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> RawResponse:
        from curl_cffi import requests as cr

        r = cr.request(
            method.upper(),
            url,
            timeout=self.timeout_seconds,
            impersonate="chrome",
            headers={"User-Agent": self.user_agent, **(headers or {})},
            cookies=cookies,
            data=body,
        )
        return RawResponse(r.status_code, r.content, dict(r.headers), str(r.url))

    def head(self, url: str, cookies: Optional[Dict[str, str]] = None) -> RawResponse:
        from curl_cffi import requests as cr

        r = cr.head(
            url,
            timeout=self.timeout_seconds,
            impersonate="chrome",
            headers={"User-Agent": self.user_agent},
            cookies=cookies,
        )
        return RawResponse(r.status_code, b"", dict(r.headers), str(r.url))

    def fetch_range(
        self, url: str, start: int, end: int, cookies: Optional[Dict[str, str]] = None
    ) -> RawResponse:
        from curl_cffi import requests as cr

        r = cr.get(
            url,
            timeout=self.timeout_seconds,
            impersonate="chrome",
            headers={"User-Agent": self.user_agent, "Range": f"bytes={start}-{end}"},
            cookies=cookies,
        )
        return RawResponse(r.status_code, r.content, dict(r.headers), str(r.url))


class HttpxAdapter(BaseHttpAdapter):
    """Fallback: async + HTTP/2 (h2 terverifikasi terpasang, G0-3)."""

    name = "httpx"

    @property
    def capabilities(self) -> TransportCapability:
        return TransportCapability(http2=True, brotli=True)

    def fetch(
        self,
        url: str,
        cookies: Optional[Dict[str, str]] = None,
        *,
        method: str = "GET",
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> RawResponse:
        r = httpx.request(
            method.upper(),
            url,
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent, **(headers or {})},
            cookies=cookies,
            content=body,
        )
        return RawResponse(r.status_code, r.content, dict(r.headers), str(r.url))

    def head(self, url: str, cookies: Optional[Dict[str, str]] = None) -> RawResponse:
        r = httpx.head(
            url,
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
            cookies=cookies,
        )
        return RawResponse(r.status_code, b"", dict(r.headers), str(r.url))

    def fetch_range(
        self, url: str, start: int, end: int, cookies: Optional[Dict[str, str]] = None
    ) -> RawResponse:
        r = httpx.get(
            url,
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent, "Range": f"bytes={start}-{end}"},
            cookies=cookies,
        )
        return RawResponse(r.status_code, r.content, dict(r.headers), str(r.url))


class RequestsAdapter(BaseHttpAdapter):
    """Fallback: kompatibilitas ekosistem."""

    name = "requests"

    @property
    def capabilities(self) -> TransportCapability:
        return TransportCapability(brotli=True)

    def fetch(
        self,
        url: str,
        cookies: Optional[Dict[str, str]] = None,
        *,
        method: str = "GET",
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> RawResponse:
        import requests

        r = requests.request(
            method.upper(),
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent, **(headers or {})},
            cookies=cookies,
            data=body,
        )
        return RawResponse(r.status_code, r.content, dict(r.headers), r.url)

    def head(self, url: str, cookies: Optional[Dict[str, str]] = None) -> RawResponse:
        import requests

        r = requests.head(
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent},
            cookies=cookies,
            allow_redirects=True,
        )
        return RawResponse(r.status_code, b"", dict(r.headers), r.url)

    def fetch_range(
        self, url: str, start: int, end: int, cookies: Optional[Dict[str, str]] = None
    ) -> RawResponse:
        import requests

        r = requests.get(
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent, "Range": f"bytes={start}-{end}"},
            cookies=cookies,
        )
        return RawResponse(r.status_code, r.content, dict(r.headers), r.url)


def build_default_registry() -> TransportRegistry:
    """Registry default sesuai prioritas ADR-011: curl_cffi → httpx → requests."""
    registry = TransportRegistry()
    for cls in (CurlCffiAdapter, HttpxAdapter, RequestsAdapter):
        adapter = cls()
        registry.register(adapter.name, adapter, adapter.capabilities)
    return registry
