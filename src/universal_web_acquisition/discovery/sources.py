"""Discovery sources for the Universal Web Acquisition Engine."""

import abc
import hashlib
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from universal_web_acquisition.core.job_model import Job, JobStatus


class DiscoverySource(abc.ABC):
    """Abstract base class for discovery sources."""
    
    @abc.abstractmethod
    async def discover(self) -> List[Job]:
        """Discover new URLs to acquire.
        
        Returns:
            List of discovery jobs
        """
        pass
    
    @abc.abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this source can handle a URL.
        
        Args:
            url: The URL to check
            
        Returns:
            True if this source can handle the URL
        """
        pass


class SeedUrlDiscoverySource(DiscoverySource):
    """Discovery source that uses a predefined list of seed URLs."""
    
    def __init__(self, seed_urls: List[str]):
        """Initialize the seed URL discovery source.
        
        Args:
            seed_urls: List of seed URLs to discover from
        """
        self.seed_urls = seed_urls
        
    async def discover(self) -> List[Job]:
        """Discover new URLs from the seed list.
        
        Returns:
            List of discovery jobs
        """
        jobs = []
        for url in self.seed_urls:
            job = Job(
                job_id=f"discovery-{hash(url)}",
                url=url,
                status=JobStatus.QUEUED
            )
            jobs.append(job)
        return jobs
    
    def can_handle(self, url: str) -> bool:
        """Check if this source can handle a URL.
        
        Args:
            url: The URL to check
            
        Returns:
            True if this source can handle the URL
        """
        return url in self.seed_urls


class HtmlLinkDiscoverySource(DiscoverySource):
    """Discovery source that extracts links from HTML content."""
    
    def __init__(self, base_url: str, html_content: str):
        """Initialize the HTML link discovery source.
        
        Args:
            base_url: The base URL for resolving relative links
            html_content: The HTML content to parse for links
        """
        self.base_url = base_url
        self.html_content = html_content
        
    async def discover(self) -> List[Job]:
        """Discover new URLs by extracting links from HTML.
        
        Returns:
            List of discovery jobs
        """
        # Simple regex-based link extraction (in a real implementation,
        # we would use a proper HTML parser like BeautifulSoup)
        urls = re.findall(r'href=["\']([^"\']*)["\']', self.html_content, re.IGNORECASE)
        
        jobs = []
        for url in urls:
            # Resolve relative URLs
            absolute_url = urljoin(self.base_url, url)
            
            # Only include HTTP(S) URLs
            parsed = urlparse(absolute_url)
            if parsed.scheme in ("http", "https"):
                job = Job(
                    job_id=f"discovery-{hash(absolute_url)}",
                    url=absolute_url,
                    status=JobStatus.QUEUED
                )
                jobs.append(job)
                
        return jobs
    
    def can_handle(self, url: str) -> bool:
        """Check if this source can handle a URL.
        
        Args:
            url: The URL to check
            
        Returns:
            True if this source can handle the URL
        """
        # This source is initialized with specific content, so it doesn't
        # handle arbitrary URLs in the same way as other sources
        return False


class SitemapDiscoverySource(DiscoverySource):
    """Discovery via robots.txt → sitemap → (index → child) → URL konten.

    Menaturalisasi pola yang terverifikasi pada target nyata (komiku.asia,
    `benchmark/real_target.py`) menjadi komponen engine (ADR-002).

    Aturan mandat:
    - robots.txt dihormati: URL hasil discovery yang cocok prefix ``Disallow``
      grup ``User-agent: *`` dibuang (kriteria penerimaan Phase 1: "Engine
      respects basic robots.txt disallow rules");
    - volume berbatas (``max_urls`` / ``max_children``) — discovery bukan
      rayapan tak berujung;
    - sitemap index diikuti SATU tingkat (child sitemap);
    - hanya URL dari host origin yang diambil; sitemap (.xml) bukan konten;
    - ``job_id`` deterministik (sha1 URL) — discovery ulang tidak menduplikasi.

    ``fetch`` disuntik (callable ``url -> Optional[bytes]``; ``None`` bila
    gagal atau status >= 400) sehingga transport tetap dipilih via registry
    (ADR-011), bukan hardcode di modul ini.
    """

    def __init__(
        self,
        origin_url: str,
        fetch: Callable[[str], Optional[bytes]],
        max_urls: int = 50,
        max_children: int = 5,
    ):
        self.origin_url = origin_url.rstrip("/")
        self._fetch = fetch
        self.max_urls = max_urls
        self.max_children = max_children

    def _get(self, url: str) -> Optional[bytes]:
        try:
            return self._fetch(url)
        except Exception:
            return None

    def _parse_robots(self, body: bytes) -> Tuple[List[str], List[str]]:
        """Parser robots.txt sederhana: prefix Disallow grup ``*`` + Sitemap."""
        disallow: List[str] = []
        sitemaps: List[str] = []
        in_star_group = False
        for raw in body.decode("utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                in_star_group = value == "*"
            elif in_star_group and key == "disallow" and value:
                disallow.append(value)
            elif key == "sitemap" and value:
                sitemaps.append(value)
        return disallow, sitemaps

    def _parse_sitemap(self, body: bytes) -> Tuple[List[str], bool]:
        text = body.decode("utf-8", errors="replace")
        locs = [
            u.strip()
            for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", text)
            if u.strip()
        ]
        return locs, "<sitemapindex" in text.lower()

    def _allowed(self, url: str, disallow: List[str]) -> bool:
        # Prefix Disallow dicocokkan terhadap PATH URL (RFC 9309) — bukan URL
        # penuh: "/private" harus memblokir "http://host/private/secret".
        path = urlparse(url).path or "/"
        return not any(prefix and path.startswith(prefix) for prefix in disallow)

    async def discover(self) -> List[Job]:
        origin = urlparse(self.origin_url)
        base = f"{origin.scheme}://{origin.netloc}"

        disallow: List[str] = []
        sitemap_urls: List[str] = []
        robots_body = self._get(base + "/robots.txt")
        if robots_body is not None:
            disallow, sitemap_urls = self._parse_robots(robots_body)
        if not sitemap_urls:
            # Konvensi umum bila robots tak menyebut (atau robots 404).
            sitemap_urls = [self.origin_url + "/sitemap.xml"]

        seen = set()
        urls: List[str] = []
        for sm_url in sitemap_urls[: self.max_children]:
            body = self._get(sm_url)
            if body is None:
                continue
            locs, is_index = self._parse_sitemap(body)
            if is_index:
                children = [
                    u
                    for u in locs
                    if urlparse(u).netloc == origin.netloc
                ][: self.max_children]
                for child in children:
                    child_body = self._get(child)
                    if child_body is None:
                        continue
                    child_locs, _ = self._parse_sitemap(child_body)
                    for u in child_locs:
                        if u not in seen:
                            seen.add(u)
                            urls.append(u)
            else:
                for u in locs:
                    if u not in seen:
                        seen.add(u)
                        urls.append(u)

        jobs: List[Job] = []
        for url in urls:
            if urlparse(url).netloc != origin.netloc:
                continue  # hanya host origin
            if not self._allowed(url, disallow):
                continue  # robots Disallow (basic prefix match)
            if url.endswith(".xml"):
                continue  # sitemap bukan konten
            jobs.append(
                Job(
                    job_id=f"discovery-{hashlib.sha1(url.encode()).hexdigest()[:12]}",
                    url=url,
                    status=JobStatus.QUEUED,
                )
            )
            if len(jobs) >= self.max_urls:
                break
        return jobs

    def can_handle(self, url: str) -> bool:
        return urlparse(url).netloc == urlparse(self.origin_url).netloc


# Registry of available discovery sources
DISCOVERY_SOURCE_REGISTRY = {
    "seed_url": SeedUrlDiscoverySource,
    "html_link": HtmlLinkDiscoverySource,
    "sitemap": SitemapDiscoverySource,
}


def get_discovery_source(source_type: str, **kwargs) -> Optional[DiscoverySource]:
    """Get a discovery source instance.
    
    Args:
        source_type: The type of discovery source
        **kwargs: Arguments to pass to the discovery source constructor
        
    Returns:
        A discovery source instance or None if source type is unknown
    """
    if source_type in DISCOVERY_SOURCE_REGISTRY:
        source_class = DISCOVERY_SOURCE_REGISTRY[source_type]
        return source_class(**kwargs)
    return None
