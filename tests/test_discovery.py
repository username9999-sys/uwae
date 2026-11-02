"""Discovery tests: SitemapDiscoverySource (ADR-002, robots compliance).

Yang diverifikasi:
- robots.txt dihormati: URL yang cocok prefix Disallow dibuang (kriteria
  penerimaan Phase 1);
- sitemap index diikuti SATU tingkat → URL konten dari child sitemap;
- hanya host origin; sitemap (.xml) bukan konten;
- volume berbatas (max_urls); job_id deterministik (discovery ulang tidak
  menduplikasi);
- robots 404 → fallback origin + /sitemap.xml;
- registry lookup "sitemap".
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.discovery.sources import (
    DISCOVERY_SOURCE_REGISTRY,
    SitemapDiscoverySource,
    get_discovery_source,
)
from universal_web_acquisition.http_transport.adapters import CurlCffiAdapter


def _fetch_factory(adapter):
    """Suntikkan transport via callable — None bila gagal / status >= 400."""

    def fetch(url):
        resp = adapter.fetch(url)
        if resp.status_code >= 400:
            return None
        return resp.content

    return fetch


def _source(base, path="", **kwargs):
    adapter = CurlCffiAdapter()
    return SitemapDiscoverySource(
        base + path, fetch=_fetch_factory(adapter), **kwargs
    )


class TestRobotsCompliance:
    def test_disallow_prefix_filtered(self):
        with FixtureServer() as base:
            source = _source(base)
            jobs = asyncio.run(source.discover())
        urls = [job.url for job in jobs]
        assert urls, "discovery kosong"
        assert not any("/private" in u for u in urls)

    def test_sitemap_index_followed_one_level(self):
        with FixtureServer() as base:
            source = _source(base)
            jobs = asyncio.run(source.discover())
        urls = [job.url for job in jobs]
        assert any(u.endswith("/html") for u in urls)


class TestUrlFiltering:
    def test_external_urls_dropped(self):
        with FixtureServer() as base:
            source = _source(base)
            jobs = asyncio.run(source.discover())
        assert not any("external.example.com" in job.url for job in jobs)

    def test_sitemap_files_not_content(self):
        with FixtureServer() as base:
            source = _source(base)
            jobs = asyncio.run(source.discover())
        assert not any(job.url.endswith(".xml") for job in jobs)

    def test_max_urls_bounded(self):
        with FixtureServer() as base:
            source = _source(base, max_urls=1)
            jobs = asyncio.run(source.discover())
        assert len(jobs) == 1


class TestDeterminism:
    def test_job_ids_deterministic(self):
        with FixtureServer() as base:
            first = asyncio.run(_source(base).discover())
            second = asyncio.run(_source(base).discover())
        assert [j.job_id for j in first] == [j.job_id for j in second]
        assert all(j.job_id.startswith("discovery-") for j in first)

    def test_can_handle_origin_only(self):
        with FixtureServer() as base:
            source = _source(base)
        assert source.can_handle(base + "/html") is True
        assert source.can_handle("https://other.example.com/x") is False


class TestFallback:
    def test_robots_missing_falls_back_to_sitemap_xml(self):
        # Server tanpa robots.txt (fetch None untuk robots) → fallback
        # origin + /sitemap.xml. Catatan: robots secara protokol (RFC 9309)
        # selalu di root host — maka simulasi lewat fetch, bukan path origin.
        adapter = CurlCffiAdapter()

        def fetch_no_robots(url):
            if url.endswith("/robots.txt"):
                return None
            resp = adapter.fetch(url)
            return None if resp.status_code >= 400 else resp.content

        with FixtureServer() as base:
            source = SitemapDiscoverySource(base + "/alt", fetch=fetch_no_robots)
            jobs = asyncio.run(source.discover())
        urls = [job.url for job in jobs]
        assert any(u.endswith("/html") for u in urls)
        assert len(urls) == 1


class TestRegistry:
    def test_sitemap_registered(self):
        assert "sitemap" in DISCOVERY_SOURCE_REGISTRY
        source = get_discovery_source(
            "sitemap", origin_url="http://example.com", fetch=lambda url: None
        )
        assert isinstance(source, SitemapDiscoverySource)

    def test_unknown_source_returns_none(self):
        assert get_discovery_source("nonexistent") is None
