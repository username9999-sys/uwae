"""Rate-limit probe berbatas di real-target runner (butuh otorisasi eksplisit).

Probe = pengulangan berbatas ke satu path untuk mencoba memicu
429/challenge/denial — parameter ``rate_limit_probe > 0`` ADALAH izinnya.
Yang diverifikasi terhadap fixture lokal (tanpa target internet):
- probe berhenti di state non-granted pertama (429 tertangkap di job 1);
- ground truth per skenario probe diturunkan dari semantika protokol atas
  status HTTP mentah (bukan dari state classifier — hindari self-fulfilling);
- probe mati by default; batas keras 20 job ditegakkan.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.benchmark.real_target import run_benchmark


class TestRateLimitProbe:
    def test_probe_stops_at_first_rate_limit(self):
        with FixtureServer() as base:
            results = Path(tempfile.mkdtemp(prefix="uwae-probe-")) / "probe.json"
            run_benchmark(
                target=base + "/",
                results_path=results,
                benchmark_id="probe-test-001",
                rate_limit_probe=3,
                rate_limit_probe_path="/rate-limited",
            )
            doc = json.loads(results.read_text(encoding="utf-8"))
        probes = [
            s for s in doc["scenarios"]
            if s["scenario_id"].startswith("rate_limit_probe_")
        ]
        assert len(probes) == 1  # berhenti di probe pertama (429 tertangkap)
        assert probes[0]["observed_state"] == "rate_limited"
        assert probes[0]["job_status"] == "failed"
        # ground truth dari status mentah 429 (protokol), bukan classifier
        assert probes[0]["ground_truth_state"] == "rate_limited"
        assert doc["rate_limit_probe"]["stopped"] == "non_granted_at_probe_1"
        assert doc["rate_limit_probe"]["jobs_run"] == 1

    def test_probe_disabled_by_default(self):
        with FixtureServer() as base:
            results = Path(tempfile.mkdtemp(prefix="uwae-probe-")) / "probe.json"
            run_benchmark(
                target=base + "/",
                results_path=results,
                benchmark_id="probe-test-002",
            )
            doc = json.loads(results.read_text(encoding="utf-8"))
        assert doc["rate_limit_probe"] is None
        assert not any(
            s["scenario_id"].startswith("rate_limit_probe_")
            for s in doc["scenarios"]
        )

    def test_probe_hard_cap_twenty_jobs(self):
        with FixtureServer() as base:
            results = Path(tempfile.mkdtemp(prefix="uwae-probe-")) / "probe.json"
            run_benchmark(
                target=base + "/",
                results_path=results,
                benchmark_id="probe-test-003",
                rate_limit_probe=25,
                rate_limit_probe_path="/html",
            )
            doc = json.loads(results.read_text(encoding="utf-8"))
        probes = [
            s for s in doc["scenarios"]
            if s["scenario_id"].startswith("rate_limit_probe_")
        ]
        assert doc["rate_limit_probe"]["max_jobs"] == 20  # batas keras keamanan
        assert len(probes) == 20
        assert doc["rate_limit_probe"]["stopped"] == "cap_reached"
        # semua granted → tanpa label non-granted (ground truth tetap None)
        assert all(s["ground_truth_state"] is None for s in probes)
