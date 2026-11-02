"""Cache respons HTTP dalam memori (dimensi kompetitif — TEXT.md matriks:
Botasaurus punya cache; UWAE tidak boleh klaim unggul tanpa kapabilitas ini).

Desain jujur:

- per-run, in-memory, berbatas (``max_entries`` LRU + ``max_body_bytes``) —
  tanpa persistensi, tanpa isu staleness lintas run;
- HANYA respons GET 200 dengan body ≤ ``max_body_bytes`` yang di-cache;
- sesi terautentikasi (cookies) TIDAK di-cache — varian per-sesi tidak boleh
  tertukar (kejujuran > hemat permintaan);
- hit TIDAK pernah disembunyikan: respons dari cache ditandai header
  ``X-Uwae-Cache: hit`` → observer merekam sinyal ``cache.hit`` sehingga
  evidence lineage tetap jujur;
- ``head``/``fetch_range`` tidak di-cache (unduhan resume butuh validasi
  server asli — §5.2);
- opt-in: hanya aktif bila operator memasangnya (``crawl --cache``).
"""

from collections import OrderedDict
from typing import Dict, Optional

from universal_web_acquisition.http_transport.adapters import (
    BaseHttpAdapter,
    RawResponse,
)
from universal_web_acquisition.http_transport.registry import (
    TransportCapability,
    TransportRegistry,
)

CACHE_HEADER = "X-Uwae-Cache"
CACHE_HIT_VALUE = "hit"


class ResponseCache:
    """Cache LRU berbatas untuk RawResponse — tanpa klaim tanpa batas."""

    def __init__(self, max_entries: int = 128, max_body_bytes: int = 1_048_576):
        self.max_entries = max_entries
        self.max_body_bytes = max_body_bytes
        self._entries: "OrderedDict[str, RawResponse]" = OrderedDict()

    def get(self, url: str) -> Optional[RawResponse]:
        resp = self._entries.get(url)
        if resp is None:
            return None
        self._entries.move_to_end(url)  # LRU: baru dipakai = paling awet
        return resp

    def put(self, url: str, response: RawResponse) -> None:
        # Hanya 200 + body dalam batas — sisanya tidak layak cache.
        if response.status_code != 200:
            return
        if len(response.content) > self.max_body_bytes:
            return
        self._entries[url] = response
        self._entries.move_to_end(url)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)


class CachingAdapter(BaseHttpAdapter):
    """Wrapper adapter dengan cache — bukti hit selalu tercatat di header."""

    def __init__(self, inner: BaseHttpAdapter, cache: Optional[ResponseCache] = None):
        self._inner = inner
        self.cache = cache if cache is not None else ResponseCache()
        self.name = inner.name
        self.timeout_seconds = inner.timeout_seconds
        self.user_agent = inner.user_agent

    @property
    def capabilities(self) -> TransportCapability:
        return self._inner.capabilities

    def can_handle(self, url: str) -> bool:
        return self._inner.can_handle(url)

    def fetch(
        self,
        url: str,
        cookies: Optional[Dict[str, str]] = None,
        *,
        method: str = "GET",
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> RawResponse:
        if cookies or method.upper() != "GET":
            # Sesi terautentikasi melewati cache sepenuhnya — lihat docstring.
            # Non-GEST juga: kunci cache adalah URL saja, jadi POST ke URL
            # yang sama dengan GET yang ter-cache akan dilayani dengan
            # respons GET. Itu jawaban yang salah untuk permintaan berbeda.
            return self._inner.fetch(
                url,
                cookies=cookies,
                method=method,
                body=body,
                headers=headers,
            )
        cached = self.cache.get(url)
        if cached is not None:
            return RawResponse(
                cached.status_code,
                cached.content,
                {**cached.headers, CACHE_HEADER: CACHE_HIT_VALUE},
                cached.final_url,
            )
        resp = self._inner.fetch(
            url, cookies=cookies, method=method, body=body, headers=headers
        )
        self.cache.put(url, resp)
        return resp

    def head(self, url: str, cookies: Optional[Dict[str, str]] = None) -> RawResponse:
        # §5.2: validasi server asli (Accept-Ranges/ETag) — tidak di-cache
        return self._inner.head(url, cookies=cookies)

    def fetch_range(
        self, url: str, start: int, end: int, cookies: Optional[Dict[str, str]] = None
    ) -> RawResponse:
        # §5.2: chunk resume selalu dari server — tidak di-cache
        return self._inner.fetch_range(url, start, end, cookies=cookies)


def build_caching_registry(cache: Optional[ResponseCache] = None) -> TransportRegistry:
    """Registry bawaan dengan seluruh adapter HTTP dibungkus CachingAdapter.

    Satu ``ResponseCache`` dibagi ke semua adapter — dan (di crawl) ke
    adapter discovery, sehingga seluruh run berbagi cache yang sama.
    """
    from universal_web_acquisition.http_transport.adapters import (
        build_default_registry,
    )

    shared = cache if cache is not None else ResponseCache()
    base = build_default_registry()
    registry = TransportRegistry()
    for name in base.ordered_names():
        adapter = base.get(name)
        registry.register(name, CachingAdapter(adapter, shared), adapter.capabilities)
    return registry
