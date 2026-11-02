"""E11 throughput tests — baseline sequential + skenario concurrent (E6).

Yang diverifikasi:
- keempat skenario (2 sequential + 2 concurrent) lulus dengan NOL kegagalan
  (baseline jujur — ada satu kegagalan = skenario gagal);
- metrik terukur dan konsisten (jobs_per_second > 0; p95 >= p50);
- test menulis ke path temp — bukti ter-commit TIDAK ditimpa suite;
- bukti ter-commit dibaca apa adanya (test_committed_evidence_stable).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.benchmark.throughput_bench import (
    RESULTS_PATH_E11,
    main,
)

EXPECTED_SCENARIOS = {
    "e11_sequential_small",
    "e11_sequential_medium",
    "e11_concurrent_t2_small",
    "e11_concurrent_t4_medium",
}


class TestThroughputBench:
    def test_all_scenarios_pass(self, tmp_path):
        # test menulis ke path temp — bukti ter-commit TIDAK ditimpa suite
        results_path = tmp_path / "e11.json"
        main(results_path=results_path)
        doc = json.loads(results_path.read_text(encoding="utf-8"))
        assert doc["summary"]["all_passed"] is True
        scenario_ids = {r["scenario_id"] for r in doc["scenarios"]}
        assert scenario_ids == EXPECTED_SCENARIOS
        for r in doc["scenarios"]:
            assert r["success"] is True
            assert r["failures"] == 0
            assert r["jobs_per_second"] > 0

    def test_key_baseline_metrics(self, tmp_path):
        results_path = tmp_path / "e11.json"
        main(results_path=results_path)
        doc = json.loads(results_path.read_text(encoding="utf-8"))
        for r in doc["scenarios"]:
            # p95 >= p50 — konsistensi statistik dasar
            assert r["latency_ms_p95"] >= r["latency_ms_p50"] > 0
            assert r["wall_time_s"] > 0

    def test_committed_evidence_stable(self):
        # bukti ter-commit dibaca apa adanya — test TIDAK meregenerasinya
        # (main() menulis ke path temp; file ini tetap bukti dari run asli)
        doc = json.loads(RESULTS_PATH_E11.read_text(encoding="utf-8"))
        assert doc["summary"]["all_passed"] is True
        assert {r["scenario_id"] for r in doc["scenarios"]} == EXPECTED_SCENARIOS
