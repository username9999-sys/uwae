"""Command-line interface for the Universal Web Acquisition Engine."""

import asyncio
import hashlib
import json
import logging
import os
import sys
import uuid
from typing import Optional
from urllib.parse import urlparse

import click

from universal_web_acquisition import __version__
from universal_web_acquisition.artifact.identification import IdentificationRegistry
from universal_web_acquisition.config.loader import load_config
from universal_web_acquisition.config.shutdown import setup_logging
from universal_web_acquisition.core.engine import AcquisitionEngine

logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="Path to configuration file (YAML)",
)
@click.pass_context
def cli(ctx: click.Context, config: Optional[str]) -> None:
    """Universal Web Acquisition Engine - A Python-first, CLI-first web acquisition engine."""
    ctx.ensure_object(dict)
    # P8: config loader — defaults -> YAML -> env vars -> CLI flags.
    #
    # ``load_config`` SENGAJA tidak punya efek samping. Menaruh
    # ``setup_logging`` di sini mengubah handler logging global untuk SETIAP
    # perintah, dan itu merusak kontrak output: ``uwae acquire --json``
    # menulis JSON ke stdout, sementara CliRunner menggabungkan stdout+stderr
    # jadi baris log apa pun ikut masuk ke ``result.output`` dan
    # ``json.loads`` gagal. Konfigurasi logging hanya dipasang oleh perintah
    # yang memang berjalan lama (``serve``) dan yang output-nya bukan kontrak
    # mesin-baca.
    ctx.obj["uwae_config"] = load_config(config_path=config)
    ctx.obj["config"] = config


@cli.command()
@click.argument("url")
@click.option(
    "--db",
    "db_path",
    default="jobs.db",
    show_default=True,
    help="Path ke database job SQLite (tabel jobs/attempts/job_events)",
)
@click.option(
    "--artifacts-dir",
    default="artifacts",
    show_default=True,
    help="Direktori penyimpanan artifact",
)
@click.option(
    "--max-retries",
    default=3,
    show_default=True,
    help="Anggaran retry per job (berbatas — ADR-011; tanpa loop tak berujung)",
)
@click.option(
    "--browser",
    is_flag=True,
    help="Aktifkan eskalasi browser CDP (keputusan USE_BROWSER planner)",
)
@click.option(
    "--session-login",
    help="Endpoint login RESMI untuk pemulihan sesi (A05); butuh --session-cookie",
)
@click.option(
    "--session-cookie",
    help="Nama cookie sesi yang diterbitkan endpoint login",
)
@click.option(
    "--extract",
    is_flag=True,
    help="Jalankan extractor terdaftar (ADR-006) atas artifact setelah sukses "
    "— hasil tercatat sebagai event audit 'extraction'",
)
@click.option(
    "--strict-soft404",
    is_flag=True,
    help="Aturan target per-situs (§3.1): soft-404 terkonfirmasi "
    "(artifact identik lintas path) → FAILED content_invalid, bukan ACCEPT",
)
@click.option(
    "--method",
    default="GET",
    show_default=True,
    help="Metode HTTP untuk akuisisi — GET (default) atau POST",
)
@click.option(
    "--data",
    default=None,
    help="Payload body untuk method non-GET (dikirim apa adanya sebagai bytes)",
)
@click.option(
    "--header",
    "header_pairs",
    multiple=True,
    help="Header request tambahan, format 'Nama: nilai' (boleh dipakai berulang)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON terstruktur (diagnosis + jejak bukti penuh)",
)
def acquire(
    url: str,
    db_path: str,
    artifacts_dir: str,
    max_retries: int,
    browser: bool,
    session_login: Optional[str],
    session_cookie: Optional[str],
    extract: bool,
    strict_soft404: bool,
    method: str,
    data: Optional[str],
    header_pairs: tuple,
    as_json: bool,
) -> None:
    """Akuisisi URL melalui siklus Access Control Plane penuh (Spec v2 §1).

    Setiap attempt: observasi → diagnosis (classifier) → keputusan (planner)
    → eksekusi; jejak bukti penuh (attempt, assessment, keputusan) dicatat ke
    database dan ditampilkan.

    Exit code: 0 sukses, 1 gagal, 2 perlu intervensi pengguna (NEEDS_USER).
    """
    from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
    from universal_web_acquisition.core.job_model import Job, JobStatus
    from universal_web_acquisition.core.job_repository import JobRepository
    from universal_web_acquisition.core.job_worker import JobWorker
    from universal_web_acquisition.http_transport.registry import RetryPolicy

    repo = JobRepository(db_path)
    storage = FilesystemArtifactStorage(base_path=artifacts_dir)

    session_manager = None
    if session_login or session_cookie:
        if not (session_login and session_cookie):
            raise click.UsageError(
                "--session-login dan --session-cookie harus dipakai bersamaan"
            )
        from universal_web_acquisition.session.manager import SessionRecoveryManager
        from universal_web_acquisition.session.providers import (
            HTTPSessionRecoveryProvider,
        )

        provider = HTTPSessionRecoveryProvider(
            origin=urlparse(url).netloc,
            login_url=session_login,
            protected_url=url,
            cookie_name=session_cookie,
        )
        session_manager = SessionRecoveryManager(provider=provider)

    browser_adapter = None
    if browser:
        from universal_web_acquisition.browser.adapter import CDPBrowserAdapter

        browser_adapter = CDPBrowserAdapter()

    extractors = None
    if extract:
        from universal_web_acquisition.extract.html_text import HTMLTextExtractor
        from universal_web_acquisition.plugins.registry import PluginRegistry

        extractors = PluginRegistry()
        extractors.register(HTMLTextExtractor())

    target_rules = None
    if strict_soft404:
        from universal_web_acquisition.access.target_rules import TargetRules

        target_rules = TargetRules()
        target_rules.register_soft404_invalid(urlparse(url).netloc)

    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=max_retries),
        browser_adapter=browser_adapter,
        session_manager=session_manager,
        extractors=extractors,
        target_rules=target_rules,
        identifier=IdentificationRegistry.with_builtins(),
    )

    job = Job(
        job_id=f"cli-{uuid.uuid4().hex[:12]}",
        url=url,
        method=method,
        body=data.encode("utf-8") if data is not None else None,
        headers=_parse_header_pairs(header_pairs) or None,
    )
    repo.save_job(job)
    asyncio.run(worker._execute_job(job))

    final = repo.get_job(job.job_id)
    result = _collect_evidence(repo, storage, final)

    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_human(result)

    if final.status == JobStatus.SUCCEEDED:
        sys.exit(0)
    if final.status == JobStatus.NEEDS_USER:
        sys.exit(2)
    sys.exit(1)


def _parse_header_pairs(pairs) -> dict:
    """Parse flag ``--header 'Nama: nilai'`` menjadi dict header.

    Format yang salah ditolak eksplisit: header yang diam-diam terpotong
    akan menghasilkan request yang berbeda dari yang dimaksud pengguna.
    """
    headers = {}
    for pair in pairs or ():
        name, sep, value = pair.partition(":")
        if not sep or not name.strip():
            raise click.UsageError(
                f"--header harus format 'Nama: nilai', bukan {pair!r}"
            )
        headers[name.strip()] = value.strip()
    return headers


def _collect_evidence(repo, storage, job) -> dict:
    """Kumpulkan diagnosis + jejak bukti satu job (evidence lineage ACP)."""
    artifact_info = None
    if job.artifact_id:
        try:
            artifact = asyncio.run(storage.retrieve(job.artifact_id))
            artifact_info = {
                "artifact_id": artifact.artifact_id,
                "size_bytes": len(artifact.content),
                "sha256": hashlib.sha256(artifact.content).hexdigest(),
                "content_type": artifact.content_type,
            }
        except Exception:
            # artifact hilang dari disk — bukti lain tetap disajikan
            # (degradasi jujur; integritas tidak dipalsukan)
            artifact_info = None

    lineage = []
    for event in repo.list_events(job.job_id):
        if event["event"] in (
            "assessment",
            "decision",
            "session_recovery",
            "extraction",
            "extraction_error",
            "soft404_suspected",
            "identification",
            "discovered_via",
        ):
            try:
                lineage.append({"kind": event["event"], **json.loads(event["detail"])})
            except json.JSONDecodeError:
                lineage.append({"kind": event["event"], "raw": event["detail"]})

    assessments = [t for t in lineage if t["kind"] == "assessment"]
    last = assessments[-1] if assessments else {}
    return {
        "job_id": job.job_id,
        "url": job.url,
        "job_status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "error": job.error,
        "observed_state": last.get("state"),
        "observed_reason": last.get("reason_code"),
        "artifact": artifact_info,
        "attempts": repo.list_attempts(job.job_id),
        "lineage": lineage,
    }


def _print_human(result: dict) -> None:
    click.echo(f"URL     : {result['url']}")
    click.echo(f"Status  : {result['job_status']}")
    click.echo(
        f"Diagnosis: {result['observed_state'] or '—'} "
        f"({result['observed_reason'] or '—'})"
    )
    if result["artifact"]:
        art = result["artifact"]
        click.echo(
            f"Artifact: {art['artifact_id']} ({art['size_bytes']} B, "
            f"sha256:{art['sha256'][:16]})"
        )
    if result["error"]:
        click.echo(f"Error   : {result['error']}")
    click.echo(f"Attempts: {len(result['attempts'])}")
    for attempt in result["attempts"]:
        click.echo(
            f"  - {attempt['attempt_id']} [{attempt['transport']}] "
            f"{attempt['status']}"
        )
    for item in result["lineage"]:
        if item["kind"] == "assessment":
            click.echo(
                f"  assessment: state={item.get('state')} "
                f"reason={item.get('reason_code')} "
                f"signals={'; '.join(item.get('signals', []))}"
            )
        elif item["kind"] == "decision":
            click.echo(
                f"  decision  : action={item.get('action')} "
                f"reason={item.get('reason_code')} — {item.get('rationale')}"
            )
        elif item["kind"] == "session_recovery":
            click.echo(
                f"  recovery  : outcome={item.get('outcome')} "
                f"generation={item.get('generation')}"
            )
        elif item["kind"] == "extraction":
            click.echo(
                f"  extraction: {item.get('extractor')} format={item.get('format')} "
                f"sha256:{str(item.get('source_sha256'))[:12]}"
            )
        elif item["kind"] == "extraction_error":
            click.echo(
                f"  extraction_error: {item.get('extractor')} — {item.get('error')}"
            )
        elif item["kind"] == "soft404_suspected":
            click.echo(
                f"  soft404    : {item.get('url')} identik dengan "
                f"{item.get('first_seen_url')} (sha256:{str(item.get('sha256'))[:12]})"
            )
        elif item["kind"] == "identification":
            conflict = (
                " — KONFLIK dengan signature" if item.get("mime_conflict") else ""
            )
            click.echo(
                f"  identifikasi: format={item.get('format')} "
                f"({item.get('confidence')}) mime={item.get('mime')}{conflict}"
            )
        elif item["kind"] == "discovered_via":
            click.echo(
                f"  ditemukan-via: {item.get('source')} — induk {item.get('parent')}"
            )


@cli.command()
@click.argument("origin")
@click.option(
    "--max-urls",
    default=50,
    show_default=True,
    help="Batas jumlah URL hasil discovery (volume berbatas)",
)
@click.option(
    "--max-children",
    default=5,
    show_default=True,
    help="Batas child sitemap yang diikuti dari sitemap index",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON terstruktur",
)
def discover(origin: str, max_urls: int, max_children: int, as_json: bool) -> None:
    """Discovery URL via robots.txt → sitemap (ADR-002).

    Patuh robots.txt (prefix Disallow grup ``*`` dicocokkan terhadap path
    URL per RFC 9309); hanya host origin; sitemap (.xml) bukan konten;
    sitemap index diikuti satu tingkat; robots 404 → fallback
    ``origin + /sitemap.xml``.
    """
    from universal_web_acquisition.discovery.sources import SitemapDiscoverySource
    from universal_web_acquisition.http_transport.adapters import CurlCffiAdapter

    adapter = CurlCffiAdapter()

    def fetch(url: str):
        resp = adapter.fetch(url)
        return None if resp.status_code >= 400 else resp.content

    source = SitemapDiscoverySource(
        origin, fetch=fetch, max_urls=max_urls, max_children=max_children
    )
    jobs = asyncio.run(source.discover())

    if as_json:
        click.echo(
            json.dumps(
                {
                    "origin": origin,
                    "count": len(jobs),
                    "robots_compliant": True,
                    "urls": [job.url for job in jobs],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        click.echo(f"Origin  : {origin}")
        click.echo(f"Ditemukan: {len(jobs)} URL (patuh robots.txt, volume berbatas)")
        for job in jobs:
            click.echo(f"  - {job.url}")


@cli.command()
@click.option(
    "--min-samples",
    default=10,
    show_default=True,
    help="Ambang sampel per bucket sebelum confidence dianggap terkalibrasi (§3.2)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON terstruktur",
)
def calibrate(min_samples: int, as_json: bool) -> None:
    """Status kalibrasi confidence dari korpus berlabel (Spec v2 §3.2).

    Bucket = state prediksi; akurasi = precision dari korpus. Bucket dengan
    sampel di bawah ambang tetap memakai konstanta kategorial — jujur
    terhadap mandat: jangan memalsukan probabilitas tanpa dasar statistik.
    """
    from universal_web_acquisition.access.classifier import (
        CONFIDENCE_HIGH,
        CONFIDENCE_LOW,
        CONFIDENCE_MEDIUM,
    )
    from universal_web_acquisition.benchmark.classifier_eval import (
        build_calibration_table,
    )
    from universal_web_acquisition.benchmark.corpus_real import load_real_cases

    table = build_calibration_table(min_samples=min_samples)
    real_cases = load_real_cases()
    # Konstanta kategorial per state (nilai utama classifier-1.0.0)
    defaults = {
        "access_granted": CONFIDENCE_HIGH,
        "rate_limited": CONFIDENCE_HIGH,
        "challenge_present": CONFIDENCE_HIGH,
        "network_failure": CONFIDENCE_HIGH,
        "auth_required": CONFIDENCE_MEDIUM,
        "access_denied": CONFIDENCE_MEDIUM,
        "javascript_required": CONFIDENCE_MEDIUM,
        "content_invalid": CONFIDENCE_MEDIUM,
        "unknown": CONFIDENCE_LOW,
    }
    rows = []
    for state, default in defaults.items():
        samples = table.sample_count(state)
        rows.append(
            {
                "state": state,
                "samples": samples,
                "confidence": round(table.confidence_for(state, default), 4),
                "source": (
                    "calibrated" if samples >= min_samples else "categorical-default"
                ),
            }
        )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "min_samples": min_samples,
                    "real_cases": len(real_cases),
                    "states": rows,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        click.echo(f"Kalibrasi confidence (min_samples={min_samples}):")
        click.echo(
            f"  Korpus: sintetis 24 + nyata {len(real_cases)} kasus (run terotorisasi)"
        )
        for row in rows:
            click.echo(
                f"  {row['state']:22s} n={row['samples']:>3d}  "
                f"confidence={row['confidence']:.2f}  ({row['source']})"
            )


@cli.command()
@click.argument("origin")
@click.option(
    "--db",
    "db_path",
    default="jobs.db",
    show_default=True,
    help="Path ke database job SQLite",
)
@click.option(
    "--artifacts-dir",
    default="artifacts",
    show_default=True,
    help="Direktori penyimpanan artifact",
)
@click.option(
    "--max-urls",
    default=10,
    show_default=True,
    help="Batas jumlah URL hasil discovery (volume berbatas)",
)
@click.option(
    "--max-children",
    default=5,
    show_default=True,
    help="Batas child sitemap yang diikuti dari sitemap index",
)
@click.option(
    "--max-retries",
    default=3,
    show_default=True,
    help="Anggaran retry per job (berbatas — ADR-011)",
)
@click.option(
    "--extract",
    is_flag=True,
    help="Jalankan extractor terdaftar (ADR-006) atas artifact setelah sukses",
)
@click.option(
    "--strict-soft404",
    is_flag=True,
    help="Aturan target per-situs (§3.1): soft-404 terkonfirmasi "
    "(artifact identik lintas path) → FAILED content_invalid, bukan ACCEPT",
)
@click.option(
    "--follow-links",
    is_flag=True,
    help="Discovery graph: panen tautan dari halaman sukses (hanya origin "
    "sama, dedup, volume tetap diikat --max-urls)",
)
@click.option(
    "--cache",
    "use_cache",
    is_flag=True,
    help="Cache respons dalam memori untuk run ini — hit selalu tercatat "
    "sebagai sinyal cache.hit di evidence lineage",
)
@click.option(
    "--concurrency",
    default=1,
    show_default=True,
    help="Jumlah thread eksekusi paralel (1 = sequential; >1 via "
    "ConcurrentJobRunner — worker+adapter per-thread, berbatas maks 16)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON terstruktur (hasil per job + ringkasan)",
)
def crawl(
    origin: str,
    db_path: str,
    artifacts_dir: str,
    max_urls: int,
    max_children: int,
    max_retries: int,
    extract: bool,
    strict_soft404: bool,
    follow_links: bool,
    use_cache: bool,
    concurrency: int,
    as_json: bool,
) -> None:
    """Discovery → enqueue → execute untuk satu origin (pipeline penuh).

    Patuh robots.txt (RFC 9309); volume berbatas; setiap job dieksekusi
    melalui siklus ACP penuh dengan evidence lineage. Job di-enqueue ke
    database SEBELUM eksekusi — terlihat meski proses terputus (G6).

    ``--follow-links``: discovery graph minimal — setiap halaman sukses
    dipanen tautannya (hanya origin sama, dedup, self-link dan skema
    non-HTTP dilewati) dan di-enqueue sebagai job baru; volume tetap
    diikat ``--max-urls``.

    Exit code: 0 semua sukses, 1 ada kegagalan, 2 ada NEEDS_USER (tanpa kegagalan).
    """
    from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
    from universal_web_acquisition.core.concurrent_runner import ConcurrentJobRunner
    from universal_web_acquisition.core.job_model import Job, JobStatus
    from universal_web_acquisition.core.job_repository import JobRepository
    from universal_web_acquisition.core.job_worker import JobWorker
    from universal_web_acquisition.discovery.link_extractor import extract_links
    from universal_web_acquisition.discovery.sources import SitemapDiscoverySource
    from universal_web_acquisition.http_transport.adapters import CurlCffiAdapter
    from universal_web_acquisition.http_transport.cache import (
        CachingAdapter,
        ResponseCache,
        build_caching_registry,
    )
    from universal_web_acquisition.http_transport.registry import RetryPolicy

    # Cache opt-in (--cache): satu ResponseCache dibagi ke adapter discovery
    # DAN seluruh adapter worker — hit selalu tercatat sebagai sinyal
    # cache.hit di evidence lineage (transparansi, bukan penghematan sembunyi).
    shared_cache = ResponseCache() if use_cache else None
    adapter = CurlCffiAdapter()
    if use_cache:
        adapter = CachingAdapter(adapter, shared_cache)

    def fetch(url: str):
        resp = adapter.fetch(url)
        return None if resp.status_code >= 400 else resp.content

    source = SitemapDiscoverySource(
        origin, fetch=fetch, max_urls=max_urls, max_children=max_children
    )
    jobs = asyncio.run(source.discover())

    if not jobs:
        if as_json:
            click.echo(
                json.dumps(
                    {"origin": origin, "discovered": 0, "results": []},
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            click.echo(f"Origin  : {origin}")
            click.echo("Ditemukan: 0 URL — tidak ada yang dieksekusi")
        return

    # Pola yang sama dengan acquire: set atribut + inisialisasi skema ulang.
    repo = JobRepository(db_path)
    storage = FilesystemArtifactStorage(base_path=artifacts_dir)

    extractors = None
    if extract:
        from universal_web_acquisition.extract.html_text import HTMLTextExtractor
        from universal_web_acquisition.plugins.registry import PluginRegistry

        extractors = PluginRegistry()
        extractors.register(HTMLTextExtractor())

    target_rules = None
    if strict_soft404:
        from universal_web_acquisition.access.target_rules import TargetRules

        target_rules = TargetRules()
        parsed = urlparse(origin if "://" in origin else f"https://{origin}")
        target_rules.register_soft404_invalid(parsed.netloc)

    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=max_retries),
        extractors=extractors,
        target_rules=target_rules,
        identifier=IdentificationRegistry.with_builtins(),
        registry=build_caching_registry(shared_cache) if use_cache else None,
    )

    queue = list(jobs)
    executed_urls = set()
    results = []

    def _harvest_links(final):
        """Panen tautan dari artifact sukses — best-effort; child → antrean.

        Kegagalan panen tidak pernah mengubah status job. Setiap tautan baru
        di-enqueue SEKARANG (G6) dan membawa provenance — edge induk→anak
        (kontrak DiscoveryResult: sumber penemuan + URL induk).
        """
        if not (
            follow_links and final.status == JobStatus.SUCCEEDED and final.artifact_id
        ):
            return
        try:
            artifact = asyncio.run(storage.retrieve(final.artifact_id))
            base = artifact.url or final.url
            for link in extract_links(artifact.content, base):
                if link in executed_urls or any(j.url == link for j in queue):
                    continue
                if len(results) + len(queue) >= max_urls:
                    break
                child = Job(
                    job_id=f"discovery-{hashlib.sha1(link.encode()).hexdigest()[:12]}",
                    url=link,
                )
                repo.save_job(child)
                repo.record_event(
                    child.job_id,
                    "discovered_via",
                    json.dumps(
                        {"url": link, "parent": base, "source": "follow_links"},
                        ensure_ascii=False,
                    ),
                )
                queue.append(child)
        except Exception:
            pass

    if concurrency > 1:
        # Paralel per-level (E6): worker+adapter per-thread dengan wiring
        # lengkap yang sama dengan sequential (extractors/target_rules/
        # identifier/cache) — G6 di dalam runner (enqueue sebelum eksekusi).
        def _worker_factory():
            return JobWorker(
                JobRepository(db_path),
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=max_retries),
                extractors=extractors,
                target_rules=target_rules,
                identifier=IdentificationRegistry.with_builtins(),
                registry=build_caching_registry(shared_cache) if use_cache else None,
            )

        runner = ConcurrentJobRunner(
            db_path, storage, n_threads=concurrency, worker_factory=_worker_factory
        )
        while queue and len(results) < max_urls:
            batch = []
            while queue and len(results) + len(batch) < max_urls:
                job = queue.pop(0)
                if job.url in executed_urls:
                    continue
                executed_urls.add(job.url)
                batch.append(job)
            if not batch:
                break
            for final in runner.run(batch, repo=repo):
                results.append(_collect_evidence(repo, storage, final))
                _harvest_links(final)
    else:
        # Jalur sequential — perilaku persis seperti sebelumnya (regresi aman).
        while queue and len(results) < max_urls:
            job = queue.pop(0)
            if job.url in executed_urls:
                continue
            executed_urls.add(job.url)
            repo.save_job(job)  # enqueue — terlihat di DB meski eksekusi terputus
            asyncio.run(worker._execute_job(job))
            final = repo.get_job(job.job_id)
            results.append(_collect_evidence(repo, storage, final))
            _harvest_links(final)

    succeeded = sum(1 for r in results if r["job_status"] == "succeeded")
    failed = sum(1 for r in results if r["job_status"] == "failed")
    needs_user = sum(1 for r in results if r["job_status"] == "needs_user")

    if as_json:
        click.echo(
            json.dumps(
                {
                    "origin": origin,
                    "discovered": len(results),
                    "summary": {
                        "succeeded": succeeded,
                        "failed": failed,
                        "needs_user": needs_user,
                    },
                    "results": results,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        click.echo(f"Origin  : {origin}")
        click.echo(
            f"Ringkasan: {len(results)} URL — {succeeded} sukses, "
            f"{failed} gagal, {needs_user} needs-user"
        )
        for result in results:
            click.echo(
                f"  - {result['url']} [{result['job_status']}] "
                f"diagnosis={result['observed_state'] or '—'}"
            )

    if failed:
        sys.exit(1)
    if needs_user:
        sys.exit(2)
    sys.exit(0)


@cli.command()
@click.argument("url")
@click.option(
    "--job-id",
    "-j",
    help="Custom job ID (optional)",
)
@click.option(
    "--wait",
    "-w",
    is_flag=True,
    help="Wait for job completion before exiting",
)
@click.pass_context
def submit(ctx: click.Context, url: str, job_id: Optional[str], wait: bool) -> None:
    """Submit a URL for acquisition."""
    engine = AcquisitionEngine(ctx.obj.get("config"))
    
    # Submit the job
    job_id_result = engine.submit_job(url=url, job_id=job_id)
    click.echo(f"Job submitted with ID: {job_id_result}")
    
    if wait:
        # Wait for completion
        result = engine.wait_for_job(job_id_result)
        if result.success:
            click.echo("Job completed successfully!")
            click.echo(f"Artifact ID: {result.artifact_id}")
        else:
            click.echo(f"Job failed: {result.error}", err=True)
            sys.exit(1)


@cli.command(name="list")
@click.option(
    "--db",
    "db_path",
    default="jobs.db",
    show_default=True,
    help="Path ke database job SQLite",
)
@click.option(
    "--limit",
    "-l",
    default=10,
    show_default=True,
    help="Jumlah job terbaru",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON terstruktur",
)
def list_jobs(db_path: str, limit: int, as_json: bool) -> None:
    """Daftar job terbaru dengan diagnosis (evidence trail ACP, §5.1)."""
    from universal_web_acquisition.core.job_repository import JobRepository

    # Pola yang sama dengan acquire: set atribut + inisialisasi skema ulang.
    repo = JobRepository(db_path)

    entries = []
    for job in repo.list_jobs(limit=limit):
        observed = None
        reason = None
        for event in reversed(repo.list_events(job.job_id)):
            if event["event"] == "assessment":
                detail = json.loads(event["detail"])
                observed = detail.get("state")
                reason = detail.get("reason_code")
                break
        entries.append(
            {
                "job_id": job.job_id,
                "url": job.url,
                "job_status": (
                    job.status.value if hasattr(job.status, "value") else str(job.status)
                ),
                "observed_state": observed,
                "observed_reason": reason,
            }
        )

    if as_json:
        click.echo(
            json.dumps(
                {"count": len(entries), "jobs": entries},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        if not entries:
            click.echo("Tidak ada job.")
            return
        for entry in entries:
            click.echo(
                f"[{entry['job_id']}] {entry['job_status']:12s} "
                f"diagnosis={entry['observed_state'] or '—'} {entry['url']}"
            )


@cli.command()
@click.argument("job_id")
@click.option(
    "--db",
    "db_path",
    default="jobs.db",
    show_default=True,
    help="Path ke database job SQLite",
)
@click.option(
    "--artifacts-dir",
    default="artifacts",
    show_default=True,
    help="Direktori penyimpanan artifact (untuk SHA-256)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON terstruktur (bukti penuh)",
)
def show(job_id: str, db_path: str, artifacts_dir: str, as_json: bool) -> None:
    """Bukti penuh satu job: attempt, lineage, artifact (ACP §5.1)."""
    from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
    from universal_web_acquisition.core.job_repository import JobRepository

    # Pola yang sama dengan acquire: set atribut + inisialisasi skema ulang.
    repo = JobRepository(db_path)
    job = repo.get_job(job_id)

    if not job:
        click.echo(f"Job {job_id} tidak ditemukan.", err=True)
        sys.exit(1)

    storage = FilesystemArtifactStorage(base_path=artifacts_dir)
    evidence = _collect_evidence(repo, storage, job)

    if as_json:
        click.echo(json.dumps(evidence, indent=2, ensure_ascii=False))
    else:
        _print_human(evidence)


@cli.command()
@click.argument("job_id")
@click.pass_context
def cancel(ctx: click.Context, job_id: str) -> None:
    """Cancel a job."""
    engine = AcquisitionEngine(ctx.obj.get("config"))
    if engine.cancel_job(job_id):
        click.echo(f"Job {job_id} cancelled.")
    else:
        click.echo(f"Failed to cancel job {job_id}.", err=True)
        sys.exit(1)


@cli.group()
def benchmark() -> None:
    """Run benchmarks."""
    pass


@benchmark.command()
@click.argument("scenario_name")
@click.option(
    "--engine",
    "-e",
    type=click.Choice(["uwae", "botasaurus"]),
    default="uwae",
    help="Which engine to benchmark",
)
@click.pass_context
def run(ctx: click.Context, scenario_name: str, engine: str) -> None:
    """Run a benchmark scenario."""
    from universal_web_acquisition.benchmark.runner import BenchmarkRunner
    
    runner = BenchmarkRunner(ctx.obj.get("config"))
    result = runner.run_scenario(scenario_name, engine)
    
    click.echo(f"Benchmark completed for {engine}:")
    click.echo(f"  Scenario: {scenario_name}")
    click.echo(f"  Success: {result.success}")
    click.echo(f"  Duration: {result.duration_ms:.2f}ms")
    click.echo(f"  Memory: {result.memory_bytes / 1024:.2f} KB")
    
    if not result.success:
        click.echo(f"  Error: {result.error}", err=True)


@cli.command()
@click.argument("job_id")
@click.option(
    "--db",
    "db_path",
    default="jobs.db",
    show_default=True,
    help="Path ke database job SQLite",
)
@click.option(
    "--artifacts-dir",
    default="artifacts",
    show_default=True,
    help="Direktori penyimpanan artifact",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON terstruktur (diagnosis + jejak bukti penuh)",
)
@click.option(
    "--plugin",
    "plugin_paths",
    multiple=True,
    help="File .py plugin eksternal (bisa diulang) — KODE DI DALAMNYA "
    "DIJALANKAN: kontrak instance get_metadata() + extract(), lewat "
    "variabel PLUGIN/PLUGINS atau kelas tanpa argumen",
)
def reprocess(
    job_id: str,
    db_path: str,
    artifacts_dir: str,
    plugin_paths: tuple,
    as_json: bool,
) -> None:
    """Proses ulang artifact tersimpan dengan extractor terdaftar (E3).

    Tanpa transfer ulang: artifact diambil dari storage lokal — bukti
    integritas sumber tetap wajib pada setiap hasil ekstraksi; hasil
    tercatat sebagai event audit extraction/extraction_error (lineage yang
    sama dengan worker). ``--plugin`` memuat plugin eksternal dari file
    .py — kompatibilitas versi tetap divalidasi registry (ADR-006).
    """
    from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
    from universal_web_acquisition.core.job_model import JobStatus
    from universal_web_acquisition.core.job_repository import JobRepository
    from universal_web_acquisition.core.job_worker import run_extraction_plugins
    from universal_web_acquisition.extract.html_text import HTMLTextExtractor
    from universal_web_acquisition.plugins.base import PluginError
    from universal_web_acquisition.plugins.loader import load_plugins_from_path
    from universal_web_acquisition.plugins.registry import PluginRegistry

    repo = JobRepository(db_path)
    job = repo.get_job(job_id)
    if job is None:
        click.echo(f"Job {job_id} tidak ditemukan")
        sys.exit(1)
    if job.status != JobStatus.SUCCEEDED or not job.artifact_id:
        click.echo(
            f"Job {job_id} tidak punya artifact untuk diproses ulang "
            f"(status={job.status.value})"
        )
        sys.exit(1)

    storage = FilesystemArtifactStorage(base_path=artifacts_dir)
    try:
        artifact = asyncio.run(storage.retrieve(job.artifact_id))
    except Exception:
        artifact = None
    if artifact is None:
        # artifact hilang dari disk (retrieve → None / error) — degradasi
        # jujur: tidak ada ekstraksi palsu
        click.echo(f"Artifact {job.artifact_id} tidak dapat dimuat dari disk")
        sys.exit(1)

    extractors = PluginRegistry()
    extractors.register(HTMLTextExtractor())
    for plugin_path in plugin_paths:
        try:
            plugins = load_plugins_from_path(plugin_path)
        except PluginError as exc:
            click.echo(f"Plugin {plugin_path} ditolak: {exc}")
            sys.exit(1)
        for plugin in plugins:
            try:
                extractors.register(plugin)
            except PluginError as exc:
                # kompatibilitas versi / duplikat — DITOLAK registry (ADR-006)
                click.echo(f"Plugin {plugin_path} ditolak: {exc}")
                sys.exit(1)
    run_extraction_plugins(repo, job.job_id, artifact, extractors)

    result = _collect_evidence(repo, storage, job)
    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_human(result)
    sys.exit(0)


@cli.command("export")
@click.argument("job_id")
@click.option(
    "--db",
    "db_path",
    default="jobs.db",
    show_default=True,
    help="Path ke database job SQLite",
)
@click.option(
    "--format",
    "export_format",
    type=click.Choice(["json", "csv"]),
    default="json",
    show_default=True,
    help="Format file hasil export",
)
@click.option("--output", "output_path", required=True, help="Path file hasil export")
def export_cmd(
    job_id: str, db_path: str, export_format: str, output_path: str
) -> None:
    """Export hasil ekstraksi job ke file JSON/CSV (lapisan Knowledge).

    Sumber data = event audit ``extraction`` yang SUDAH tercatat — jalankan
    ``acquire --extract`` atau ``uwae reprocess`` dahulu bila belum ada.
    Tanpa event ekstraksi → ditolak jujur, tanpa file kosong palsu.
    """
    from universal_web_acquisition.core.job_repository import JobRepository
    from universal_web_acquisition.export.adapters import (
        get_exporter,
        rows_from_events,
    )

    repo = JobRepository(db_path)
    job = repo.get_job(job_id)
    if job is None:
        click.echo(f"Job {job_id} tidak ditemukan")
        sys.exit(1)

    events = [e for e in repo.list_events(job_id) if e["event"] == "extraction"]
    if not events:
        click.echo(
            f"Job {job_id} tidak punya hasil ekstraksi — jalankan "
            "acquire --extract atau uwae reprocess dahulu"
        )
        sys.exit(1)

    rows = rows_from_events(events)
    try:
        exporter = get_exporter(export_format)
        count = exporter.export(rows, output_path)
    except ValueError as exc:
        click.echo(str(exc))
        sys.exit(1)

    click.echo(f"Export {count} hasil ekstraksi -> {output_path}")
    sys.exit(0)


def _collect_stats(repo) -> dict:
    """Agregasi evidence seluruh job — satu sumber kebenaran: job_events.

    Jujur: diagnosis dihitung dari assessment TERAKHIR per job (job tanpa
    assessment tidak dihitung); ``hit_rate`` None bila tidak ada job
    ter-fetch (bukan 0 palsu); database kosong → nol.
    """
    jobs = repo.list_jobs(limit=1_000_000)
    by_status: dict = {}
    diagnoses: dict = {}
    ident_formats: dict = {}
    mime_conflicts = 0
    extraction_ok = 0
    extraction_errors = 0
    discovered_via = 0
    fetched = 0
    cache_hits = 0

    for job in jobs:
        status = job.status.value if hasattr(job.status, "value") else str(job.status)
        by_status[status] = by_status.get(status, 0) + 1
        last_assessment = None
        for event in repo.list_events(job.job_id):
            name = event["event"]
            if name == "assessment":
                last_assessment = event
            elif name == "identification":
                try:
                    detail = json.loads(event["detail"])
                except (json.JSONDecodeError, TypeError):
                    continue
                fmt = detail.get("format")
                if fmt:
                    ident_formats[fmt] = ident_formats.get(fmt, 0) + 1
                if detail.get("mime_conflict"):
                    mime_conflicts += 1
            elif name == "extraction":
                extraction_ok += 1
            elif name == "extraction_error":
                extraction_errors += 1
            elif name == "discovered_via":
                discovered_via += 1
        if last_assessment is not None:
            try:
                detail = json.loads(last_assessment["detail"])
            except (json.JSONDecodeError, TypeError):
                detail = {}
            signals = detail.get("signals") or []
            if any(s.startswith("http.status=") for s in signals):
                fetched += 1
            if any(s.startswith("cache.hit=") for s in signals):
                cache_hits += 1
            state = detail.get("state")
            if state:
                diagnoses[state] = diagnoses.get(state, 0) + 1

    return {
        "total_jobs": len(jobs),
        "by_status": dict(sorted(by_status.items())),
        "diagnoses": dict(sorted(diagnoses.items())),
        "cache": {
            "fetched_jobs": fetched,
            "cache_hits": cache_hits,
            "hit_rate": round(cache_hits / fetched, 3) if fetched else None,
        },
        "identification": {
            "formats": dict(sorted(ident_formats.items())),
            "mime_conflicts": mime_conflicts,
        },
        "extraction": {"success": extraction_ok, "errors": extraction_errors},
        "discovery": {"discovered_via": discovered_via},
    }


@cli.command("stats")
@click.option(
    "--db",
    "db_path",
    default="jobs.db",
    show_default=True,
    help="Path ke database job SQLite",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON terstruktur",
)
def stats_cmd(db_path: str, as_json: bool) -> None:
    """Ringkasan agregat evidence seluruh job (observability — TEXT.md).

    Satu sumber kebenaran: job_events — diagnosis (assessment terakhir per
    job), cache hit rate (None bila tak ada job ter-fetch), distribusi
    format identifikasi, ekstraksi, dan provenance discovery. Database
    kosong → nol, tanpa angka palsu.
    """
    from universal_web_acquisition.core.job_repository import JobRepository

    repo = JobRepository(db_path)
    stats = _collect_stats(repo)
    if as_json:
        click.echo(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        click.echo(f"Job total     : {stats['total_jobs']}")
        for status, count in stats["by_status"].items():
            click.echo(f"  {status:12s}: {count}")
        click.echo("Diagnosis (assessment terakhir per job):")
        for state, count in stats["diagnoses"].items():
            click.echo(f"  {state:20s}: {count}")
        cache = stats["cache"]
        rate = cache["hit_rate"]
        rate_text = (
            f"{rate:.1%}" if rate is not None else "n/a (tidak ada job ter-fetch)"
        )
        click.echo(
            f"Cache         : {cache['cache_hits']}/{cache['fetched_jobs']} hit "
            f"({rate_text})"
        )
        formats = stats["identification"]["formats"]
        if formats:
            fmt_text = ", ".join(f"{k}={v}" for k, v in formats.items())
            click.echo(
                f"Identifikasi  : {fmt_text} — konflik MIME: "
                f"{stats['identification']['mime_conflicts']}"
            )
        click.echo(
            f"Ekstraksi     : {stats['extraction']['success']} sukses, "
            f"{stats['extraction']['errors']} error"
        )
        click.echo(
            f"Discovery     : {stats['discovery']['discovered_via']} tautan ditemukan"
        )
    sys.exit(0)


@cli.command("serve")
@click.option(
    "--db",
    "db_path",
    default="jobs.db",
    show_default=True,
    help="Path ke database job SQLite",
)
@click.option(
    "--artifacts-dir",
    default="artifacts",
    show_default=True,
    help="Direktori penyimpanan artifact",
)
@click.option(
    "--poll-interval",
    default=1.0,
    show_default=True,
    help="Jeda antar polling antrian QUEUED (detik)",
)
@click.pass_obj
def serve_cmd(
    obj: dict,
    db_path: str,
    artifacts_dir: str,
    poll_interval: float,
) -> None:
    """Jalankan worker persisten: eksekusi job QUEUED sampai dihentikan.

    Mode daemon: SIGTERM/SIGINT menyelesaikan job yang sedang berjalan lalu
    berhenti bersih (P8). Pemulihan job terputus tetap jalan saat start.
    """
    from universal_web_acquisition.config.loader import ShutdownConfig
    from universal_web_acquisition.config.shutdown import ShutdownManager
    from universal_web_acquisition.core.job_repository import JobRepository

    uwae_config = obj.get("uwae_config")
    shutdown_config = uwae_config.shutdown if uwae_config is not None else ShutdownConfig()

    repo = JobRepository(db_path)
    recovered = repo.recover_interrupted()

    stop_event = asyncio.Event()
    manager = ShutdownManager(shutdown_config, stop_event=stop_event)

    async def _loop() -> None:
        manager.install_signal_handlers()
        if recovered:
            click.echo(
                f"recover_interrupted: {len(recovered)} job diproses "
                f"({', '.join(recovered[:5])}{'...' if len(recovered) > 5 else ''})",
                err=True,
            )
        else:
            click.echo("recover_interrupted: tidak ada job terputus", err=True)

        while not manager.is_shutdown_requested():
            job = _next_queued_job(repo)
            if job is None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    continue  # masih polling — daemon tetap hidup
                break  # stop_event diset (shutdown diminta)
            manager.set_current_job(job.job_id)
            click.echo(f"eksekusi {job.job_id} ({job.url})", err=True)
            try:
                await _serve_execute(repo, artifacts_dir, job)
            except Exception:  # kegagalan satu job tidak menghentikan daemon
                logger.exception("job %s gagal", job.job_id)
            finally:
                manager.set_current_job(None)

    try:
        asyncio.run(_loop())
    except KeyboardInterrupt:
        click.echo("dihentikan (KeyboardInterrupt)", err=True)
    click.echo("serve berhenti bersih", err=True)
    sys.exit(0)


def _next_queued_job(repo):
    """Ambil satu job QUEUED tertuas sebagai RUNNING, atau ``None``.

    Tanda RUNNING ditulis SEBELUM dikembalikan supaya dua proses serve
    (kalau-kalau dijalankan berganda) tidak mengambil job yang sama
    — klaimnya atomic di SQLite lewat UPDATE ... WHERE job_id = ? AND
    status = 'queued'.
    """
    import datetime
    import sqlite3

    from universal_web_acquisition.core.job_model import JobStatus

    conn = sqlite3.connect(repo.db_path)
    try:
        now = datetime.datetime.now().isoformat()
        row = conn.execute(
            "SELECT job_id FROM jobs WHERE status = ? "
            "ORDER BY created_at ASC, rowid ASC LIMIT 1",
            (JobStatus.QUEUED.value,),
        ).fetchone()
        if row is None:
            return None
        job_id = row[0]
        claimed = conn.execute(
            "UPDATE jobs SET status = ?, started_at = ?, updated_at = ? "
            "WHERE job_id = ? AND status = ?",
            (
                JobStatus.RUNNING.value,
                now,
                now,
                job_id,
                JobStatus.QUEUED.value,
            ),
        )
        conn.commit()
        if claimed.rowcount != 1:
            return None  # di-claim proses lain — coba job berikutnya
        return repo.get_job(job_id)
    finally:
        conn.close()


async def _serve_execute(repo, artifacts_dir: str, job) -> None:
    """Eksekusi satu job lewat JobWorker (jalur yang sama dengan ``acquire``)."""
    from universal_web_acquisition.artifact.storage import (
        FilesystemArtifactStorage,
    )
    from universal_web_acquisition.core.job_model import JobStatus
    from universal_web_acquisition.core.job_worker import JobWorker
    from universal_web_acquisition.http_transport.registry import RetryPolicy

    storage = FilesystemArtifactStorage(base_path=artifacts_dir)
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(),
        identifier=IdentificationRegistry.with_builtins(),
    )
    job.status = JobStatus.RUNNING
    repo.save_job(job)
    await worker._execute_job(job)


@cli.command("shutdown")
@click.argument("pid", type=int)
def shutdown_cmd(pid: int) -> None:
    """Kirim SIGTERM ke proses ``uwae serve`` (PID)."""
    import signal as _signal

    try:
        os.kill(pid, _signal.SIGTERM)
    except ProcessLookupError:
        raise click.ClickException(f"Tidak ada proses dengan PID {pid}")
    except PermissionError:
        raise click.ClickException(
            f"Tidak diizinkan menghentikan PID {pid} (bukan pemilik proses?)"
        )
    click.echo(f"SIGTERM dikirim ke {pid}")
    sys.exit(0)


def main() -> None:
    """Main entry point for the CLI."""
    cli(auto_envvar_prefix="UWAE")


if __name__ == "__main__":
    main()
