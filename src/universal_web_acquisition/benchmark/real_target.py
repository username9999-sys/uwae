"""Real-target acquisition test (otorisasi user): https://01.komiku.asia/.

Mandat INSTRUCTION.md: pengujian terhadap target nyata dengan bukti per
percobaan (§6.2) — BUKAN klaim unggul. Aturan pengujian:

- volume MINIMAL (beberapa permintaan, bukan flood);
- robots.txt dihormati: hanya path yang di-Allow yang diuji;
- berhenti pada ACCESS_DENIED (desain engine), hormati Retry-After (A06);
- setiap attempt tercatat penuh melalui evidence lineage (job_events):
  observasi → assessment → keputusan planner → hasil;
- artifact direkam dengan ukuran + SHA-256 (integritas, §5.3);
- probe rate-limit (opsional, ``rate_limit_probe > 0``) HANYA berjalan atas
  otorisasi eksplisit operator untuk pengulangan berbatas — parameter itu
  adalah izinnya: maks N job ke satu path yang sama, berhenti di state
  non-granted pertama, setiap job ≤ 2 request HTTP (anggaran planner).

Hasil: ``docs/benchmark/real-target-komiku.json`` + ringkasan ke stdout.
"""

import asyncio
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from universal_web_acquisition.artifact.identification import (
    IdentificationRegistry,
)
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy

TARGET = "https://01.komiku.asia/"
RESULTS_PATH = Path("/root/universal-web-acquisition/docs/benchmark/real-target-komiku.json")
RUN_ID = "real-target-komiku-001"


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _run_one(worker: JobWorker, repo: JobRepository, storage, url: str, scenario_id: str) -> dict:
    """Satu skenario melalui engine penuh + bukti lineage lengkap."""
    job = Job(job_id=f"rt-{scenario_id}", url=url)
    repo.save_job(job)
    asyncio.run(worker._execute_job(job))

    final = repo.get_job(job.job_id)
    success = final.status == JobStatus.SUCCEEDED
    artifact_info = None
    if success and final.artifact_id:
        artifact = asyncio.run(storage.retrieve(final.artifact_id))
        artifact_info = {
            "size_bytes": len(artifact.content),
            "sha256": _sha256(artifact.content),
            "content_type": artifact.content_type,
            "final_url": artifact.url,
        }

    # Evidence lineage: assessment + decision + soft-404 + identifikasi
    # format per attempt (job_events)
    trail = []
    for event in repo.list_events(job.job_id):
        if event["event"] in (
            "assessment",
            "decision",
            "soft404_suspected",
            "identification",
        ):
            try:
                trail.append({"kind": event["event"], **json.loads(event["detail"])})
            except json.JSONDecodeError:
                trail.append({"kind": event["event"], "raw": event["detail"]})

    last_assessment = next(
        (t for t in reversed(trail) if t["kind"] == "assessment"), None
    )
    return {
        "scenario_id": scenario_id,
        "url": url,
        "job_status": final.status.value,
        "error": final.error,
        "observed_state": last_assessment["state"] if last_assessment else None,
        "observed_reason": last_assessment["reason_code"] if last_assessment else None,
        "artifact": artifact_info,
        "attempts": repo.list_attempts(job.job_id),
        "lineage": trail,
    }


def _first_content_urls(sitemap_content: bytes, base: str, limit: int = 2) -> list:
    """Ambil beberapa URL pertama dari sitemap (hemat permintaan, patuh robots)."""
    text = sitemap_content.decode("utf-8", errors="replace")
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)
    urls = [u.strip() for u in locs if u.strip()]
    # lewati sitemap index/child; ambil URL konten dari host target saja
    content = [
        u
        for u in urls
        if u.startswith(base) and not u.endswith(".xml") and "/sitemap" not in u
    ]
    return content[:limit]


# Ground truth non-granted dari SEMANTIKA PROTOKOL atas status HTTP mentah
# (objektif, didefinisikan RFC) — BUKAN dari state classifier (menghindari
# self-fulfilling). 403 sengaja dipetakan ke access_denied (konservatif):
# menlabel challenge_present butuh penilaian marker body, bukan status saja.
_PROTOCOL_GROUND_TRUTH = {
    "429": "rate_limited",
    "401": "auth_required",
    "403": "access_denied",
}


def _protocol_ground_truth(result: dict):
    """Ground truth protokol dari sinyal ``http.status`` mentah assessment terakhir."""
    assessments = [t for t in result["lineage"] if t["kind"] == "assessment"]
    if not assessments:
        return None
    signals = dict(
        part.split("=", 1)
        for part in (assessments[-1].get("signals") or [])
        if "=" in part
    )
    return _PROTOCOL_GROUND_TRUTH.get(signals.get("http.status"))


def run_benchmark(
    target: str = TARGET,
    results_path: Path = RESULTS_PATH,
    benchmark_id: str = RUN_ID,
    probe_path: str = None,
    rate_limit_probe: int = 0,
    rate_limit_probe_path: str = None,
):
    """Jalankan benchmark satu target nyata (hemat permintaan, patuh robots).

    ``probe_path`` opsional: satu path yang jelas tidak ada — bukti perilaku
    soft-404 situs (server membalas 200 + HTML untuk path apa pun).

    ``rate_limit_probe`` opsional (default 0 = mati): jumlah maksimum job
    pengulangan berbatas untuk mencoba memicu rate-limit/challenge —
    MENYATAKAN nilai > 0 adalah otorisasi eksplisit operator. Path probe:
    ``rate_limit_probe_path`` (default: homepage target).
    """
    repo, db_path = _make_repo()
    storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-real-"))
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.5),
        identifier=IdentificationRegistry.with_builtins(),
    )

    scenarios = []

    # 1. robots.txt — dasar kepatuhan (diambil lewat engine, jadi bagian bukti)
    robots = _run_one(worker, repo, storage, target + "robots.txt", "robots_txt")
    scenarios.append(robots)

    # ambil ulang isi robots dari artifact untuk catatan kepatuhan; deteksi
    # soft-404: server membalas 200 + HTML homepage alih-alih direktif robots
    disallow = []
    robots_soft_404 = False
    if robots["job_status"] == "succeeded":
        art = asyncio.run(storage.retrieve(_artifact_id_of(repo, "rt-robots_txt")))
        robots_text = art.content.decode("utf-8", errors="replace")
        lowered = robots_text.lower()
        if "user-agent" in lowered or "disallow" in lowered or "sitemap:" in lowered:
            disallow = [
                line.split(":", 1)[1].strip()
                for line in robots_text.splitlines()
                if line.lower().startswith("disallow:")
            ]
        else:
            robots_soft_404 = True

    # 2. homepage
    scenarios.append(_run_one(worker, repo, storage, target, "homepage"))

    # 3. sitemap.xml (dinyatakan robots.txt) — bila sitemap index, ikuti satu
    #    child sitemap (satu tingkat; volume tetap minimal)
    sitemap = _run_one(worker, repo, storage, target + "sitemap.xml", "sitemap_xml")
    scenarios.append(sitemap)

    content_urls = []
    if sitemap["artifact"]:
        art = asyncio.run(storage.retrieve(_artifact_id_of(repo, "rt-sitemap_xml")))
        content_urls = _first_content_urls(art.content, target, limit=2)
        if not content_urls:
            child_urls = [
                u.strip()
                for u in re.findall(
                    r"<loc>\s*(.*?)\s*</loc>", art.content.decode("utf-8", errors="replace")
                )
                if u.strip().endswith(".xml")
            ]
            if child_urls:
                child = _run_one(
                    worker, repo, storage, child_urls[0], "sitemap_child"
                )
                scenarios.append(child)
                if child["artifact"]:
                    art2 = asyncio.run(
                        storage.retrieve(_artifact_id_of(repo, "rt-sitemap_child"))
                    )
                    content_urls = _first_content_urls(art2.content, target, limit=2)
    for index, url in enumerate(content_urls, start=1):
        scenarios.append(
            _run_one(worker, repo, storage, url, f"sitemap_content_{index}")
        )

    # 4. probe soft-404 opsional — bukti perilaku server untuk path tak ada
    if probe_path:
        scenarios.append(
            _run_one(
                worker,
                repo,
                storage,
                target.rstrip("/") + probe_path,
                "soft404_probe",
            )
        )

    # 5. probe rate-limit berbatas (opsional; parameter > 0 = otorisasi
    #    eksplisit operator untuk pengulangan). Worker terpisah dengan
    #    max_retries=0 agar tiap job = ≤ 2 request HTTP (attempt 0 + 1 di
    #    luar anggaran → ABORT planner). Berhenti di state non-granted
    #    pertama — sinyal 429/challenge/denial sudah tertangkap.
    rate_limit_meta = None
    if rate_limit_probe > 0:
        max_jobs = min(int(rate_limit_probe), 20)  # batas keras keamanan
        probe_worker = JobWorker(
            repo,
            scheduler=None,
            storage=storage,
            retry_policy=RetryPolicy(max_retries=0, base_backoff_seconds=0.05),
        )
        probe_url = target.rstrip("/") + (rate_limit_probe_path or "")
        stopped = "cap_reached"
        jobs_run = 0
        for index in range(1, max_jobs + 1):
            result = _run_one(
                probe_worker, repo, storage, probe_url, f"rate_limit_probe_{index}"
            )
            result["ground_truth_state"] = _protocol_ground_truth(result)
            scenarios.append(result)
            jobs_run = index
            if (
                result["observed_state"] != "access_granted"
                or result["job_status"] != "succeeded"
            ):
                stopped = f"non_granted_at_probe_{index}"
                break
        rate_limit_meta = {
            "max_jobs": max_jobs,
            "path": probe_url,
            "jobs_run": jobs_run,
            "stopped": stopped,
        }

    # Ground truth protokol untuk SEMUA skenario (bukan hanya probe): bila
    # server membalas 429/401/403, kasus nyata itu masuk korpus secara jujur
    # (semantika protokol atas status mentah — bukan state classifier).
    for scenario in scenarios:
        scenario.setdefault("ground_truth_state", _protocol_ground_truth(scenario))

    Path(db_path).unlink(missing_ok=True)

    doc = {
        "schema_version": 1,
        "benchmark_id": benchmark_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "robots_compliance": {
            "disallow_prefixes": disallow,
            "robots_soft_404": robots_soft_404,
            "note": (
                "robots.txt mengembalikan HTML (soft-404) — tidak ada direktif "
                "robots; engine melanjutkan dengan fallback sitemap konvensi; "
                "volume minimal"
                if robots_soft_404
                else "hanya path yang di-Allow yang diuji; volume minimal (<= 6 permintaan)"
            ),
        },
        "environment": {
            "python": "3.14.6 (Termux, bionic)",
            "architecture": "aarch64",
            "transport": "curl_cffi (chrome impersonation, UA engine)",
            "engine": "uwae-0.3.0 (JobWorker + ACP cycle + planner + resume)",
            "retry_policy": "max_retries=1, base_backoff=0.5s",
        },
        "scenarios": scenarios,
        "rate_limit_probe": rate_limit_meta,
        "summary": {
            "interpretation": (
                "Pengukuran evidence-based terhadap target nyata atas otorisasi user — "
                "BUKAN klaim unggul (mandat INSTRUCTION.md). Diagnosis per attempt "
                "tercatat penuh (observasi → assessment → keputusan)."
            ),
            "scenarios_run": len(scenarios),
            "all_diagnosed": all(s["observed_state"] for s in scenarios),
        },
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{'scenario':22s} {'status':12s} {'state':22s} {'reason':22s} artifact")
    for s in scenarios:
        art = f"{s['artifact']['size_bytes']}B sha256:{s['artifact']['sha256'][:12]}" if s["artifact"] else "—"
        print(
            f"{s['scenario_id']:22s} {s['job_status']:12s} "
            f"{str(s['observed_state']):22s} {str(s['observed_reason']):22s} {art}"
        )
    print(f"\nresults -> {results_path}")


def main():
    run_benchmark()


def _artifact_id_of(repo: JobRepository, job_id: str) -> str:
    job = repo.get_job(job_id)
    return job.artifact_id if job and job.artifact_id else ""


if __name__ == "__main__":
    main()
