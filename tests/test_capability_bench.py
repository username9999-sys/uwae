"""E10 capability benchmark tests — bukti kapabilitas di level engine penuh.

Mandat INSTRUCTION.md: jangan klaim unggul tanpa hasil benchmark. Test ini
menjalankan benchmark E10 (5 skenario kapabilitas pasca-roadmap melalui
engine penuh) dan memverifikasi bahwa hasil ter-commit membuktikan:

- kelima skenario lulus dengan SEMUA checks benar (identifikasi file-first,
  cache hit jujur + integritas terjaga, discovery graph ber-provenance,
  reprocessing plugin eksternal ber-integrity sumber);
- hasil tersimpan di ``engine-results-e10.json`` (E9 tidak ditimpa).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.benchmark.capability_bench import (
    RESULTS_PATH_E10,
    main,
)

EXPECTED_SCENARIOS = {
    "e10_identification_no_ext",
    "e10_identification_wrong_mime",
    "e10_cache_hit",
    "e10_follow_links_provenance",
    "e10_reprocess_plugin",
}


class TestCapabilityBench:
    def test_all_scenarios_pass(self, tmp_path):
        # test menulis ke path temp — bukti ter-commit TIDAK ditimpa suite
        results_path = tmp_path / "e10.json"
        main(results_path=results_path)
        doc = json.loads(results_path.read_text(encoding="utf-8"))
        assert doc["summary"]["all_passed"] is True
        scenario_ids = {r["scenario_id"] for r in doc["scenarios"]}
        assert scenario_ids == EXPECTED_SCENARIOS
        # setiap skenario membawa checks yang semua benar — bukti, bukan klaim
        for r in doc["scenarios"]:
            assert all(r["checks"].values()), r["scenario_id"]

    def test_key_evidence_checks(self, tmp_path):
        results_path = tmp_path / "e10.json"
        main(results_path=results_path)
        doc = json.loads(results_path.read_text(encoding="utf-8"))
        by_id = {r["scenario_id"]: r for r in doc["scenarios"]}
        # cache: hit jujur + integritas byte terjaga lintas hit
        cache = by_id["e10_cache_hit"]["checks"]
        assert cache["second_fetch_from_cache"] is True
        assert cache["integrity_preserved_through_cache"] is True
        # discovery graph: provenance induk→anak terekam
        follow = by_id["e10_follow_links_provenance"]["checks"]
        assert follow["provenance_recorded"] is True
        # reprocess: plugin eksternal dengan lineage sha256 sumber
        reproc = by_id["e10_reprocess_plugin"]["checks"]
        assert reproc["external_plugin_ran"] is True
        assert reproc["source_integrity_lineage"] is True

    def test_committed_evidence_stable(self):
        # bukti ter-commit dibaca apa adanya — test TIDAK meregenerasinya
        # (main() menulis ke path temp; file ini tetap bukti dari run asli)
        doc = json.loads(RESULTS_PATH_E10.read_text(encoding="utf-8"))
        assert doc["summary"]["all_passed"] is True
        assert {r["scenario_id"] for r in doc["scenarios"]} == EXPECTED_SCENARIOS
