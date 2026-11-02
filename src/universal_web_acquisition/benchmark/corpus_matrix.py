"""E17 -- matriks korpus vonis UWAE vs Botasaurus (Tahap G).

TEXT.md:1427 (Tahap G) meminta: "Publikasikan hasil menang, seri, kalah, dan
belum teruji secara terpisah." Setiap benchmark lintas-implementasi sudah
mempublikasikan vonisnya sendiri, tapi belum ada SATU artefak yang
menggabungkan semuanya di level korpus. E17 itu artefaknya, dan sekaligus
menutup gerbang TEXT.md §9 #7 ("Di skenario mana mesin baru mengungguli
baseline, sama, atau justru gagal?").

Modul ini TIDAK menjalankan benchmark. Ia membaca evidence yang SUDAH
dipublikasikan dan menyusunnya. Ground truth tetap milik fixture: modul ini
tidak menilai capability, hanya merangkum vonis yang sudah dihitung harness
dengan kriteria yang sama.

Aturan vonis
------------
Aturan ini disalin dari ``browser_diff_bench._comparison_outcome`` (E16) yang
sudah terverifikasi, dan diterapkan SERAGAM ke semua slot:

- Batas 1 -- tingkat sukses atas run yang DIEVALUASI.
- Batas 2 -- tingkat sukses atas SELURUH attempt.
- Kedua batas memberi urutan sama  -> vonis pasti (uwae / baseline / tie).
- Kedua batas memberi urutan BERBEDA -> ``not_comparable``: bukti yang ada
  tidak cukup untuk memilih, jadi TIDAK diberikan ke lengan mana pun.
- Salah satu sisi tanpa run yang bisa dinilai -> ``no_evaluable_runs``.

Run yang tidak bisa dinilai (runtime failure, atau lengan melaporkan error
tanpa body maupun status) dikeluarkan dari penyebut kapabilitas dan
dipublikasikan TERPISAH sebagai ``untested_runs`` -- tidak pernah dihitung
sebagai kegagalan engine.

Yang TIDAK boleh terjadi di sini
--------------------------------
- Menarang vonis yang tidak ada di evidence. Slot E16 memuat vonis eksplisit;
  slot E14 dan E15 tidak, jadi vonisnya DITURUNKAN di sini dengan aturan di
  atas dan ditandai ``verdict_source: "derived"`` -- dan setiap sel
  mencantumkan angka yang dipakainya supaya bisa diaudit ulang.
- Menjumlahkan perbandingan lintas slot jadi satu angka tunggal tanpa
  qualifier. Slot yang sama bisa mengukur skenario yang sama dengan lengan
  dan kriteria berbeda, jadi jumlah di korpus adalah jumlah INSTANSI
  perbandingan, bukan jumlah skenario unik.
- Mengarang closure celah. Celah yang ditutup dicatat eksplisit dengan
  rujukan ke slot yang menutupnya.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BENCHMARK_ID = "e17-corpus-verdict-matrix-001"
RESULTS_PATH = Path(
    "/root/universal-web-acquisition/docs/benchmark/engine-results-e17.json"
)
REPORT_PATH = Path(
    "/root/universal-web-acquisition/docs/benchmark/corpus-verdict-matrix.md"
)
BENCHMARK_DIR = Path("/root/universal-web-acquisition/docs/benchmark")

# Slot yang di-rangkum, dipetakan ke dimensinya. "Dimensi" adalah axis yang
# diukur -- membandingkan slot berbeda dimensi tanpa qualifier akan menyesatkan.
SLOT_DIMENSIONS = {
    "engine-results-e14.json": "http-transport",
    "engine-results-e15.json": "session-flow",
    "engine-results-e16.json": "browser-arm",
    # Backfill §6.3 (n=30). Slot E18/E19 mengukur skenario dan dimensi yang
    # SAMA seperti slot lama, hanya dengan jumlah run lebih besar. Keduanya
    # men-supersede slot lamanya (lihat `supersedes` di dalam file evidence),
    # jadi hanya satu dari pasangan itu yang dihitung.
    "engine-results-e18.json": "http-transport",
    "engine-results-e19.json": "session-flow",
    # E20: dimensi BARU (http-post) — tidak menggantikan E18. E20 mengukur
    # kapabilitas POST HTTP yang sama sekali tidak terukur di E14/E18 (hanya
    # GET/HEAD/Range). Dimensi ini menambah aspek perbandingan, bukan
    # menggantikan; E18 tetap aktif dan tetap dihitung korpus.
    "engine-results-e20.json": "http-post",
    # E21/E22: ekstensi dimensi http-post — menutup celah yang dideklarasikan
    # E20 (multipart, redirect 307, POST via browser). Dimensi sama, jadi
    # tetap dihitung sebagai bagian http-post, bukan dimensi baru.
    "engine-results-e21.json": "http-post",
    "engine-results-e22.json": "http-post",
}

# Celah yang dideklarasikan oleh sebuah slot, dan slot yang menutupnya.
# Dipublikasikan eksplisit -- closure TIDAK ditebak dari kemiripan nama
# skenario, karena ID skenario di slot berbeda memang berbeda (E14
# ``a05_protected`` diukur E15 sebagai ``session_valid``/``session_expired``).
DECLARED_GAP_CLOSURES = {
    "a05_protected": {
        # E15 (n=5) digantikan oleh E19 (n=30) pada dimensi yang sama.
        # Closure menunjuk slot AKTIF: slot yang sudah digantikan tidak lagi
        # dihitung korpus, jadi menunjuknya akan menggagalkan validasi closure
        # (dan memang tidak boleh — closure harus berdiri di atas bukti yang
        # sedang dihitung).
        "closed_by": "E19",
        "evidence": "docs/benchmark/engine-results-e19.json",
        "note": (
            "Slot http-transport menyatakan alur sesi terautentikasi belum "
            "diukur. Slot session-flow mengukurnya pada fixture yang mendukung: "
            "cookie login -> akses terproteksi, dengan pencabutan sesi di sisi "
            "server. Setelah backfill §6.3, slot session-flow yang dihitung "
            "adalah E19 (n=30), bukan E15 (n=5) yang digantikannya."
        ),
    },
    "js_rendering_browser_arm": {
        "closed_by": "E16",
        "evidence": "docs/benchmark/engine-results-e16.json",
        "note": (
            "Slot http-transport menyatakan kedua arm-nya arm HTTP sehingga "
            "rendering JavaScript tak terukur. E16 menjalankan kedua "
            "implementasi browser di device yang sama dan mengukur gerbang JS "
            "lewat skenario b07_js_render."
        ),
    },
    # Celah yang dideklarasikan E20 (POST) — ditutup E21 (HTTP: multipart +
    # redirect 307) dan E22 (browser form POST).
    "post_multipart_form_data": {
        "closed_by": "E21",
        "evidence": "docs/benchmark/engine-results-e21.json",
        "note": (
            "E20 hanya mengukur urlencoded/JSON/empty/octet-stream. E21 mengukur "
            "multipart/form-data byte-for-byte terhadap konstanta MULTIPART_BODY "
            "(boundary ikut diuji) pada n=30 per arm."
        ),
    },
    "post_redirect_307_preserves_method": {
        "closed_by": "E21",
        "evidence": "docs/benchmark/engine-results-e21.json",
        "note": (
            "E20 tidak punya route redirect. E21 mengukur apakah method dan body "
            "POST dipertahankan setelah redirect 307 — ground truth respons akhir "
            "200, dan observasi server membuktikan dua hop (307 lalu 200 ok)."
        ),
    },
    "post_browser_arm": {
        "closed_by": "E22",
        "evidence": "docs/benchmark/engine-results-e22.json",
        "note": (
            "E20 hanya arm HTTP. E22 mengukur POST yang dieksekusi lewat submit "
            "form HTML oleh kedua mesin browser (chromium headless) pada device "
            "yang sama, n=30 per arm, dengan JS submit identik untuk kedua arm."
        ),
    },
}

VERDICT_RULE = (
    "Vonis dihitung pada DUA batas: tingkat sukses atas run yang dievaluasi "
    "dan tingkat sukses atas seluruh attempt. Kalau kedua batas memberi "
    "urutan sama, vonisnya pasti (uwae / baseline / tie). Kalau berbeda, "
    "bukti tidak cukup memilih -> not_comparable. Kalau salah satu sisi "
    "tidak punya run yang bisa dinilai -> no_evaluable_runs. Run yang tidak "
    "bisa dinilai dikeluarkan dari penyebut kapabilitas dan dipublikasikan "
    "terpisah sebagai untested_runs."
)


# ---------------------------------------------------------------------------
# Aturan vonis (identik dengan E16)
# ---------------------------------------------------------------------------


def comparison_outcome(uwae: Dict, baseline: Dict) -> str:
    """Vonis perbandingan, diuji pada dua batas. Salinan semantik E16."""
    if uwae["evaluated_runs"] == 0 or baseline["evaluated_runs"] == 0:
        return "no_evaluable_runs"

    def order(left: Dict, right: Dict, denominator: str) -> int:
        left_den = left[denominator]
        right_den = right[denominator]
        if not left_den or not right_den:
            return 0
        left_rate = left["primary_success_runs"] / left_den
        right_rate = right["primary_success_runs"] / right_den
        if abs(left_rate - right_rate) < 1e-12:
            return 0
        return 1 if left_rate > right_rate else -1

    by_evaluated = order(uwae, baseline, "evaluated_runs")
    by_all_attempts = order(uwae, baseline, "runs")
    if by_evaluated != by_all_attempts:
        return "not_comparable"
    if by_evaluated > 0:
        return "uwae"
    if by_evaluated < 0:
        return "baseline"
    return "tie"


def row_is_untested(row: Dict) -> bool:
    """Run yang tidak bisa dinilai.

    Tiga sumber (identik dengan E16):
    1. runtime failure -- harness tidak bisa mengeksekusi lengan;
    2. lengan melaporkan error tanpa menghasilkan body maupun status;
    3. outcome kosong.
    """
    if not row:
        return True
    if row.get("runtime_failure"):
        return True
    if (
        row.get("error")
        and not row.get("body_sha256")
        and row.get("status_code") is None
    ):
        return True
    return False


def _cell(runs: int, evaluated_runs: int, successes: int) -> Dict:
    return {
        "runs": runs,
        "evaluated_runs": evaluated_runs,
        "primary_success_runs": successes,
        "untested_runs": runs - evaluated_runs,
    }


def _empty_totals() -> Dict:
    return {
        "uwae_wins": 0,
        "ties": 0,
        "baseline_wins": 0,
        "not_comparable": 0,
        "no_evaluable_runs": 0,
        "untested_runs_total": 0,
    }


def _tally(totals: Dict, outcome: str, uwae: Dict, baseline: Dict) -> None:
    if outcome == "uwae":
        totals["uwae_wins"] += 1
    elif outcome == "baseline":
        totals["baseline_wins"] += 1
    elif outcome == "tie":
        totals["ties"] += 1
    elif outcome == "not_comparable":
        totals["not_comparable"] += 1
    else:
        totals["no_evaluable_runs"] += 1
    totals["untested_runs_total"] += uwae["untested_runs"] + baseline["untested_runs"]


# ---------------------------------------------------------------------------
# Adapter per skema evidence
# ---------------------------------------------------------------------------


def _is_uwae_arm(arm_id: str) -> bool:
    return arm_id.startswith("uwae")


def _slot_from_e14_like(doc: Dict, slot: str, source: str) -> Dict:
    """E14: ``engines`` + ``scenarios[].results[engine_id]`` (agregat).

    Evidence E14 tidak memisahkan run yang belum bisa dinilai, jadi
    ``evaluated_runs`` diambil sama dengan ``runs`` dandasar's itu dicatat
    lewat ``evaluated_basis`` -- pembaca tahu angka itu tidak dipisah.
    """
    engines = doc.get("engines") or []
    uwae_engines = [e for e in engines if not e.get("is_baseline")]
    baseline_engines = [e for e in engines if e.get("is_baseline")]
    if len(uwae_engines) != 1 or not baseline_engines:
        raise ValueError(
            "Slot %s: evidence harus menyebut tepat satu engine UWAE dan "
            "setidaknya satu baseline; ditemukan %d / %d"
            % (slot, len(uwae_engines), len(baseline_engines))
        )
    uwae_id = uwae_engines[0]["engine_id"]

    comparisons: List[Dict] = []
    totals = _empty_totals()
    for scenario in doc.get("scenarios") or []:
        results = scenario.get("results") or {}
        if uwae_id not in results:
            continue
        for baseline in baseline_engines:
            baseline_id = baseline["engine_id"]
            if baseline_id not in results:
                continue
            uwae_cell = results[uwae_id]
            baseline_cell = results[baseline_id]
            uwae = _cell(
                int(uwae_cell.get("runs") or 0),
                int(uwae_cell.get("runs") or 0),
                int(uwae_cell.get("primary_successes") or 0),
            )
            baseline = _cell(
                int(baseline_cell.get("runs") or 0),
                int(baseline_cell.get("runs") or 0),
                int(baseline_cell.get("primary_successes") or 0),
            )
            outcome = comparison_outcome(uwae, baseline)
            comparisons.append(
                {
                    "scenario_id": scenario.get("scenario_id"),
                    "criterion": scenario.get("primary_criterion"),
                    "uwae_arm": uwae_id,
                    "baseline_arm": baseline_id,
                    "uwae": uwae,
                    "baseline": baseline,
                    "verdict": outcome,
                    "verdict_source": "derived",
                    "evaluated_basis": "published_runs_only",
                    "note": (
                        "Slot ini tidak memisahkan run yang belum bisa dinilai, "
                        "jadi evaluated_runs = runs. Bandingkan dengan slot "
                        "berikutnya yang menyimpan row kasar."
                    ),
                }
            )
            _tally(totals, outcome, uwae, baseline)

    return {
        "slot": slot,
        "source": source,
        "benchmark_id": doc.get("benchmark_id"),
        "dimension": SLOT_DIMENSIONS.get(source, "unknown"),
        "schema": "e14_like",
        "comparisons": comparisons,
        "totals": totals,
        "declared_gaps": doc.get("unsupported_scenarios") or [],
    }


def _slot_from_e15_like(doc: Dict, slot: str, source: str) -> Dict:
    """E15: ``scenarios[].arms[arm_id].runs[]`` (row kasar)."""
    arms = doc.get("arms") or {}
    uwae_arms = [arm_id for arm_id in arms if _is_uwae_arm(arm_id)]
    baseline_arms = [arm_id for arm_id in arms if not _is_uwae_arm(arm_id)]
    if len(uwae_arms) != 1 or not baseline_arms:
        raise ValueError(
            "Slot %s: evidence harus menyebut tepat satu arm UWAE dan "
            "setidaknya satu arm baseline; ditemukan %d / %d"
            % (slot, len(uwae_arms), len(baseline_arms))
        )
    uwae_id = uwae_arms[0]

    comparisons: List[Dict] = []
    totals = _empty_totals()
    for scenario in doc.get("scenarios") or []:
        scenario_arms = scenario.get("arms") or {}
        if uwae_id not in scenario_arms:
            continue
        for baseline_id in baseline_arms:
            if baseline_id not in scenario_arms:
                continue
            uwae_rows = scenario_arms[uwae_id].get("runs") or []
            baseline_rows = scenario_arms[baseline_id].get("runs") or []
            uwae = _summarise_rows(uwae_rows)
            baseline = _summarise_rows(baseline_rows)
            outcome = comparison_outcome(uwae, baseline)
            comparisons.append(
                {
                    "scenario_id": scenario.get("scenario_id"),
                    "criterion": "content_acquired",
                    "uwae_arm": uwae_id,
                    "baseline_arm": baseline_id,
                    "uwae": uwae,
                    "baseline": baseline,
                    "verdict": outcome,
                    "verdict_source": "derived",
                    "evaluated_basis": "raw_rows",
                    "note": (
                        "Kriteria primer E15: resource terproteksi benar-benar "
                        "terambil dengan body yang cocok (status 200 + sha256 "
                        "body). Run dengan error tanpa body maupun status "
                        "dihitung belum teruji, bukan gagal."
                    ),
                }
            )
            _tally(totals, outcome, uwae, baseline)

    return {
        "slot": slot,
        "source": source,
        "benchmark_id": doc.get("benchmark_id"),
        "dimension": SLOT_DIMENSIONS.get(source, "unknown"),
        "schema": "e15_like",
        "comparisons": comparisons,
        "totals": totals,
        "declared_gaps": doc.get("unsupported_scenarios") or [],
    }


def _summarise_rows(rows: List[Dict]) -> Dict:
    """Ringkas run mentah jadi sel yang bisa dibandingkan."""
    evaluated = [row for row in rows if not row_is_untested(row)]
    successes = sum(1 for row in evaluated if row.get("reached_protected"))
    return _cell(len(rows), len(evaluated), successes)


def _slot_from_e16_like(doc: Dict, slot: str, source: str) -> Dict:
    """E16: vonis EKSPLISIT di ``summary.comparisons``."""
    comparisons: List[Dict] = []
    totals = _empty_totals()
    for entry in doc.get("summary", {}).get("comparisons") or []:
        uwae = _cell(
            int(entry.get("runs") or 0),
            int(entry.get("uwae_evaluated_runs") or 0),
            int(entry.get("uwae_successes") or 0),
        )
        baseline = _cell(
            int(entry.get("runs") or 0),
            int(entry.get("baseline_evaluated_runs") or 0),
            int(entry.get("baseline_successes") or 0),
        )
        outcome = entry.get("outcome") or comparison_outcome(uwae, baseline)
        comparisons.append(
            {
                "scenario_id": entry.get("scenario_id"),
                "criterion": entry.get("criterion"),
                "uwae_arm": entry.get("uwae_arm"),
                "baseline_arm": entry.get("baseline_arm"),
                "uwae": uwae,
                "baseline": baseline,
                "verdict": outcome,
                "verdict_source": "explicit",
                "evaluated_basis": "raw_rows",
                "note": "Vonis diambil apa adanya dari evidence slot ini.",
            }
        )
        _tally(totals, outcome, uwae, baseline)

    return {
        "slot": slot,
        "source": source,
        "benchmark_id": doc.get("benchmark_id"),
        "dimension": SLOT_DIMENSIONS.get(source, "unknown"),
        "schema": "e16_like",
        "comparisons": comparisons,
        "totals": totals,
        "declared_gaps": doc.get("unsupported_scenarios") or [],
    }


def _detect_schema(doc: Dict) -> Optional[str]:
    """Skema evidence lintas-implementasi, atau ``None`` kalau bukan.

    Syaratnya disengaja ketat: sebuah slot hanya masuk korpus kalau ia
    benar-benar mengukur UWAE lawAN baseline Botasaurus. Evidence E9/E10/
    E11/E12/E13 bukan begitu -- E9 misalnya punya key ``engines`` tapi
    membandingkan engine UWAE dengan transport-nya sendiri, tanpa baseline
    Botasaurus, jadi VONISNYA tidak bisa masuk matriks korpus.
    """
    summary = doc.get("summary")
    if isinstance(summary, dict) and "comparisons" in summary:
        return "e16_like"
    engines = doc.get("engines")
    if isinstance(engines, list) and any(
        isinstance(engine, dict) and engine.get("is_baseline") for engine in engines
    ):
        return "e14_like"
    arms = doc.get("arms")
    if isinstance(arms, dict) and any(
        str(arm_id).startswith("botasaurus") for arm_id in arms
    ):
        return "e15_like"
    return None


# ---------------------------------------------------------------------------
# Celah yang dideklarasikan
# ---------------------------------------------------------------------------


def _collect_gaps(slots: List[Dict]) -> List[Dict]:
    """Celah yang dideklarasikan, dengan status closure yang eksplisit."""
    declared: Dict[str, Dict] = {}
    for slot in slots:
        for gap in slot.get("declared_gaps") or []:
            scenario_id = gap.get("scenario_id")
            if not scenario_id:
                continue
            declared.setdefault(
                scenario_id,
                {
                    "scenario_id": scenario_id,
                    "declared_in": slot["slot"],
                    "declared_in_source": slot["source"],
                    "reason": gap.get("reason"),
                    "status": "open",
                    "closed_by": None,
                    "closure_evidence": None,
                    "closure_note": None,
                },
            )
    for scenario_id, closure in DECLARED_GAP_CLOSURES.items():
        entry = declared.get(scenario_id)
        if entry is None:
            continue
        entry["status"] = "closed"
        entry["closed_by"] = closure["closed_by"]
        entry["closure_evidence"] = closure["evidence"]
        entry["closure_note"] = closure["note"]
    return list(declared.values())


def _validate_gap_closures(slots: List[Dict]) -> None:
    """Cek bahwa slot yang disebut menutup celah benar-benar ada dan terukur.

    Closure tidak boleh sekadar klaim: slot yang dirujuk harus ada di korpus
    dan harus punya perbandingan.
    """
    by_slot = {slot["slot"]: slot for slot in slots}
    for scenario_id, closure in DECLARED_GAP_CLOSURES.items():
        target = by_slot.get(closure["closed_by"])
        if target is None:
            raise ValueError(
                "Celah %s dinyatakan ditutup oleh %s, tapi slot itu tidak ada "
                "di korpus" % (scenario_id, closure["closed_by"])
            )
        if not target.get("comparisons"):
            raise ValueError(
                "Celah %s dinyatakan ditutup oleh %s, tapi slot itu tidak punya "
                "perbandingan" % (scenario_id, closure["closed_by"])
            )


# ---------------------------------------------------------------------------
# Supersession
# ---------------------------------------------------------------------------


def _read_supersedes(doc: Dict) -> List[str]:
    """Slot mana yang digantikan oleh slot ini, menurut evidence-nya sendiri.

    Backfill (§6.3) menambah slot baru dengan skenario dan dimensi yang SAMA
    seperti slot lama, hanya dengan n lebih besar. Kalau keduanya dihitung,
    korpus menghitung ganda: satu skenario terdua di dua bukti.

    Supersession dideklarasikan DI DALAM file evidence (``supersedes``), bukan
    di kode aggregator — supaya sumber kebenaran ikut travels bersama
    buktinya, dan supaya slot baru tidak bisa diam-diam menggantikan slot
    lama tanpa jejak.
    """
    raw = doc.get("supersedes") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(item) for item in raw]


def _apply_supersessions(slot_entries: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Keluarkan slot yang digantikan dari hitungan; tetap publikasikan.

    Mengembalikan ``(slot_aktif, daftar_supersession)``. Slot yang digantikan
    TIDAK hilang: ia tetap tercatat lengkap di ``corpus["slots"]`` dengan
    status ``superseded``, supaya pembaca bisa melihat bukti lamanya dan
    alasan penggantinya.
    """
    superseded_by: Dict[str, str] = {}
    for entry in slot_entries:
        for target in entry.get("supersedes") or []:
            superseded_by[target] = entry["slot"]

    active: List[Dict] = []
    records: List[Dict] = []
    for entry in slot_entries:
        if entry["slot"] in superseded_by:
            entry["status"] = "superseded"
            entry["superseded_by"] = superseded_by[entry["slot"]]
            records.append(
                {
                    "slot": entry["slot"],
                    "source": entry["source"],
                    "superseded_by": superseded_by[entry["slot"]],
                    "reason": (
                        "Slot ini digantikan oleh %s yang mengukur skenario "
                        "dan dimensi yang sama dengan n lebih besar. "
                        " evidences lamanya tetap utuh dan tetap dipublikasikan."
                        % superseded_by[entry["slot"]]
                    ),
                }
            )
            continue
        entry["status"] = "active"
        active.append(entry)

    known = {entry["slot"] for entry in slot_entries}
    for target, replacement in superseded_by.items():
        if target not in known:
            raise ValueError(
                "Slot %s menyatakan menggantikan %s, tapi slot %s tidak ada "
                "di korpus" % (replacement, target, target)
            )
    return active, records


# ---------------------------------------------------------------------------
# Rakit korpus
# ---------------------------------------------------------------------------


def discover_slots() -> List[Tuple[str, str]]:
    """Temukan evidence lintas-implementasi yang sudah dipublikasikan."""
    found: List[Tuple[str, str]] = []
    for path in sorted(BENCHMARK_DIR.glob("engine-results-e*.json")):
        if path.name == RESULTS_PATH.name:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(doc, dict):
            continue
        schema = _detect_schema(doc)
        if schema is None:
            # Bukan differential lintas-implementasi (mis. E5/E9/E12/E13) --
            # vonisnya tidak bisa masuk matriks korpus.
            continue
        slot = "E" + path.stem.rsplit("-e", 1)[-1]
        found.append((slot, path.name))
    return found


def build_corpus(slots: Optional[List[Tuple[str, str]]] = None) -> Dict:
    slots = slots if slots is not None else discover_slots()
    slot_entries: List[Dict] = []
    for slot, filename in slots:
        path = BENCHMARK_DIR / filename
        doc = json.loads(path.read_text(encoding="utf-8"))
        schema = _detect_schema(doc)
        if schema == "e14_like":
            entry = _slot_from_e14_like(doc, slot, filename)
        elif schema == "e15_like":
            entry = _slot_from_e15_like(doc, slot, filename)
        else:
            entry = _slot_from_e16_like(doc, slot, filename)
        entry["supersedes"] = _read_supersedes(doc)
        slot_entries.append(entry)

    active_slots, supersessions = _apply_supersessions(slot_entries)
    _validate_gap_closures(active_slots)
    gaps = _collect_gaps(active_slots)

    corpus_totals = _empty_totals()
    by_dimension: Dict[str, Dict] = {}
    for entry in active_slots:
        for key, value in entry["totals"].items():
            corpus_totals[key] += value
        dimension = entry["dimension"]
        bucket = by_dimension.setdefault(dimension, _empty_totals())
        for key, value in entry["totals"].items():
            bucket[key] += value

    closed = sum(1 for gap in gaps if gap["status"] == "closed")
    return {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Menggabungkan vonis seluruh benchmark lintas-implementasi UWAE vs "
            "Botasaurus jadi satu matriks korpus: menang, seri, kalah, dan "
            "belum teruji dipublikasikan terpisah (TEXT.md:1427, Tahap G; "
            "gerbang TEXT.md §9 #7)."
        ),
        "method": {
            "verdict_rule": VERDICT_RULE,
            "source_slots": [
                {"slot": slot, "source": filename} for slot, filename in slots
            ],
            "counts_are": (
                "Jumlah INSTANSI perbandingan, bukan jumlah skenario unik. "
                "Skenario yang sama bisa diukur di beberapa slot dengan lengan "
                "dan kriteria berbeda, jadi jumlah slot tidak boleh dibaca "
                "sebagai jumlah skenario."
            ),
            "no_new_runs": (
                "Modul ini tidak menjalankan benchmark. Ia hanya merangkum "
                "evidence yang sudah dipublikasikan."
            ),
        },
        "slots": slot_entries,
        "dimensions": by_dimension,
        "supersessions": supersessions,
        "declared_gaps": gaps,
        "summary": {
            "corpus_totals": corpus_totals,
            "active_slots": len(active_slots),
            "superseded_slots": len(supersessions),
            "declared_gaps_total": len(gaps),
            "declared_gaps_closed": closed,
            "declared_gaps_open": len(gaps) - closed,
            "interpretation": (
                "Korpus ini mengukur DUA HAL yang tidak boleh dicampur: "
                "kemampuan (vonis per perbandingan) dan cakupan (celah yang "
                "dideklarasikan lalu ditutup). Tidak ada klaim bahwa UWAE "
                "mengungguli Botasaurus secara keseluruhan."
            ),
        },
    }


def _fmt_rate(cell: Dict) -> str:
    """``3/5`` -- jumlah sukses atas run yang dievaluasi."""
    return "%d/%d" % (cell["primary_success_runs"], cell["evaluated_runs"])


def _verdict_label(outcome: str) -> str:
    return {
        "uwae": "**uwae**",
        "baseline": "**baseline**",
        "tie": "tie",
        "not_comparable": "**tidak sebanding**",
        "no_evaluable_runs": "**tanpa run yang dapat dinilai**",
    }[outcome]


def render_report(corpus: Dict) -> str:
    """Laporan korpus -- seluruh angka diambil dari evidence, bukan diketik."""
    totals = corpus["summary"]["corpus_totals"]
    lines: List[str] = []
    lines.append("# Matriks vonis korpus UWAE vs Botasaurus (E17)")
    lines.append("")
    lines.append(
        "Satu artefak yang menggabungkan vonis seluruh benchmark "
        "lintas-implementasi: menang, seri, kalah, dan **belum teruji** "
        "dipublikasikan terpisah (TEXT.md:1427, Tahap G; gerbang "
        "TEXT.md §9 #7)."
    )
    lines.append("")
    lines.append(
        "Evidence: `docs/benchmark/engine-results-e17.json` — benchmark_id "
        "`%s`. Matriks ini **tidak menjalankan benchmark**: ia merangkum "
        "evidence yang sudah dipublikasikan." % corpus["benchmark_id"]
    )
    lines.append("")

    lines.append("## Ringkasan korpus")
    lines.append("")
    lines.append("| Vonis | Jumlah |")
    lines.append("|---|---|")
    lines.append("| UWAE menang | **%d** |" % totals["uwae_wins"])
    lines.append("| Seri | **%d** |" % totals["ties"])
    lines.append("| Baseline menang | **%d** |" % totals["baseline_wins"])
    lines.append("| Tidak sebanding (bukti tidak cukup memilih) | **%d** |"
                 % totals["not_comparable"])
    lines.append("| Tanpa run yang dapat dinilai | **%d** |"
                 % totals["no_evaluable_runs"])
    lines.append("| Run belum teruji (total) | **%d** |"
                 % totals["untested_runs_total"])
    lines.append("")
    lines.append(
        "Jumlah di atas adalah **jumlah instansi perbandingan, bukan jumlah "
        "skenario unik**. Skenario yang sama bisa diukur di beberapa slot "
        "dengan lengan dan kriteria berbeda, jadi angkanya tidak boleh "
        "dibaca sebagai jumlah skenario."
    )
    lines.append("")
    lines.append(
        "**Tidak ada klaim bahwa UWAE mengungguli Botasaurus secara "
        "keseluruhan.** Yang diukur di sini adalah DUA hal yang tidak boleh "
        "dicampur: kemampuan (vonis per perbandingan) dan cakupan (celah "
        "yang dideklarasikan lalu ditutup)."
    )
    lines.append("")

    lines.append("## Vonis per dimensi")
    lines.append("")
    lines.append(
        "| Dimensi | UWAE | Seri | Baseline | Tidak sebanding | Tanpa run | "
        "Belum teruji |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for dimension, bucket in corpus["dimensions"].items():
        lines.append(
            "| `%s` | %d | %d | %d | %d | %d | %d |"
            % (
                dimension,
                bucket["uwae_wins"],
                bucket["ties"],
                bucket["baseline_wins"],
                bucket["not_comparable"],
                bucket["no_evaluable_runs"],
                bucket["untested_runs_total"],
            )
        )
    lines.append("")

    lines.append("## Vonis per slot")
    lines.append("")
    for slot in corpus["slots"]:
        bucket = slot["totals"]
        source = "eksplisit di evidence"
        if slot["comparisons"]:
            source = (
                "eksplisit di evidence"
                if slot["comparisons"][0]["verdict_source"] == "explicit"
                else "diturunkan di sini"
            )
        else:
            source = "tidak ada perbandingan"
        lines.append(
            "### %s — `%s` (dimensi `%s`)"
            % (slot["slot"], slot["source"], slot["dimension"])
        )
        lines.append("")
        if slot.get("status") == "superseded":
            lines.append(
                "**Status: superseded oleh %s.** Slot ini mengukur skenario "
                "dan dimensi yang sama dengan n lebih kecil, jadi TIDAK ikut "
                "dihitung pada ringkasan korpus. Evidence lamanya tetap "
                "utuh dan tetap dipublikasikan di sini sebagai rekaman "
                "historis." % slot.get("superseded_by", "-")
            )
            lines.append("")
        lines.append(
            "Skema `%s`; vonis %s. %d perbandingan: **%d** UWAE, **%d** seri, "
            "**%d** baseline, %d tidak sebanding, %d tanpa run yang dapat dinilai."
            % (
                slot["schema"],
                source,
                len(slot["comparisons"]),
                bucket["uwae_wins"],
                bucket["ties"],
                bucket["baseline_wins"],
                bucket["not_comparable"],
                bucket["no_evaluable_runs"],
            )
        )
        lines.append("")
        lines.append("| Skenario | Kriteria | UWAE | Baseline | Vonis |")
        lines.append("|---|---|---|---|---|")
        for comparison in slot["comparisons"]:
            lines.append(
                "| `%s` | `%s` | %s | %s | %s |"
                % (
                    comparison["scenario_id"],
                    comparison["criterion"],
                    _fmt_rate(comparison["uwae"]),
                    _fmt_rate(comparison["baseline"]),
                    _verdict_label(comparison["verdict"]),
                )
            )
        lines.append("")

    lines.append("## Celah yang dideklarasikan")
    lines.append("")
    lines.append(
        "Cakupan adalah hal yang berbeda dari kemampuan. Celah yang "
        "dideklarasikan sebuah slot dicatat beserta statusnya; closure "
        "menunjuk slot yang benar-benar mengukurnya, bukan klaim naratif."
    )
    lines.append("")
    lines.append(
        "| Celah | Dideklarasikan di | Status | Ditutup oleh | Bukti closure |"
    )
    lines.append("|---|---|---|---|---|")
    for gap in corpus["declared_gaps"]:
        lines.append(
            "| `%s` | %s | **%s** | %s | %s |"
            % (
                gap["scenario_id"],
                gap["declared_in"],
                gap["status"],
                gap["closed_by"] or "—",
                "`%s`" % gap["closure_evidence"] if gap["closure_evidence"] else "—",
            )
        )
    lines.append("")
    lines.append(
        "Celah: **%d** dideklarasikan, **%d** ditutup, **%d** masih terbuka."
        % (
            corpus["summary"]["declared_gaps_total"],
            corpus["summary"]["declared_gaps_closed"],
            corpus["summary"]["declared_gaps_open"],
        )
    )
    lines.append("")

    lines.append("## Aturan vonis")
    lines.append("")
    lines.append(corpus["method"]["verdict_rule"])
    lines.append("")
    lines.append("## Batasan")
    lines.append("")
    lines.append(
        "- **Fixture sintetis, satu origin.** Semua slot memakai fixture "
        "lokal; tidak ada TLS, redirect, rate limit, atau cookie lintas "
        "origin pada dimensi HTTP."
    )
    lines.append(
        "- **Jumlah instans, bukan skenario unik.** Lengan dan kriteria "
        "berbeda antar slot, jadi jumlah slot tidak boleh dijumlahkan "
        "menjadi klaim kapabilitas tunggal."
    )
    lines.append(
        "- **Basis run yang dievaluasi berbeda antar slot.** Evidence "
        "http-transport hanya memuat agregat per sel, evidence session-flow "
        "memuat run mentah, evidence browser-arm memuat vonis eksplisit; "
        "`evaluated_basis` pada setiap perbandingan menyatakan mana yang "
        "dipakai."
    )
    lines.append(
        "- **Slot tersuspen tidak ikut dihitung.** Backfill §6.3 (ADR-023) "
        "menggantikan slot n=5 dengan slot n=30 pada dimensi yang sama. "
        "Slot lama tetap dipublikasikan sebagai rekaman historis, tapi "
        "vonisnya tidak masuk hitungan — hanya slot aktif yang dihitung."
    )
    lines.append(
        "- **Tidak ada data historis yang ditimpa.** Matriks korpus menambah "
        "artefak baru; evidence slot lama tetap utuh, dan digantikan lewat "
        "deklarasi `supersedes` di dalam file evidence, bukan lewat penulisan "
        "ulang."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    corpus = build_corpus()
    RESULTS_PATH.write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    REPORT_PATH.write_text(render_report(corpus), encoding="utf-8")
    totals = corpus["summary"]["corpus_totals"]
    print(json.dumps(totals, indent=2))
    print("celah: %d dideklarasikan, %d ditutup, %d terbuka"
          % (corpus["summary"]["declared_gaps_total"],
             corpus["summary"]["declared_gaps_closed"],
             corpus["summary"]["declared_gaps_open"]))
    print("results -> %s" % RESULTS_PATH)
    print("report  -> %s" % REPORT_PATH)


if __name__ == "__main__":
    main()
