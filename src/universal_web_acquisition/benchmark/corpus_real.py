"""Real-run labeled corpus (pertumbuhan korpus berlabel, §3.2 INSTRUCTION.md).

Korpus yang bermakna untuk kalibrasi confidence adalah kasus dari RUN NYATA —
bukan kasus sintetis yang ditulis terhadap spesifikasi yang sama dengan
classifier (self-fulfilling). Modul ini membangun kasus berlabel dari file
hasil benchmark nyata yang ter-commit:

- ``real-target-*.json`` (glob — komiku 6 + ampnavi 4; file target baru
  yang ter-commit otomatis masuk): skenario ``succeeded`` berlabel
  ACCESS_GRANTED (sinyal asli dari assessment events); skenario gagal
  HANYA diikutkan bila file membawa ``ground_truth_state`` eksplisit —
  diturunkan runner dari semantika protokol atas status HTTP mentah
  (429/401/403), bukan dari state classifier (hindari self-fulfilling).

- ``engine-results-e9.json`` — 10 skenario engine-level (3 granted + 7
  diagnosis §6.1: auth/rate/challenge/denied/content_invalid×2/js). Ground
  truth tiap skenario adalah ``EXPECTED_DIAGNOSIS`` yang ter-commit di file
  hasil (bukan rekonstruksi manual); sinyal adalah assessment event asli
  yang dikonsumsi classifier saat run — bukan korpus self-fulfilling.

Hasil: bucket ``access_granted`` mencapai >= 12 sampel (10 nyata + 3 E9 + 2
sintetis) → kalibrasi confidence untuk state itu AKTIF; bucket lain (sampel
< 10) tetap fallback kategorial (jujur terhadap §3.2 — jangan memalsukan
probabilitas tanpa dasar statistik).
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from universal_web_acquisition.access.classifier import Signal, classify
from universal_web_acquisition.access.model import AccessState, Observation

REPO_BENCHMARK_DIR = (
    Path(__file__).resolve().parents[3] / "docs" / "benchmark"
)

# File hasil run nyata: glob real-target-*.json di direktori benchmark —
# hasil target baru yang ter-commit otomatis masuk korpus.
REAL_RESULTS_GLOB = "real-target-*.json"

# E9 (engine-level, fixture lokal): ground truth ter-commit di file hasil.
E9_RESULTS_FILE = "engine-results-e9.json"


@dataclass(frozen=True)
class RealCase:
    """Satu kasus berlabel dari run nyata: sinyal asli → state ground truth."""

    case_id: str
    expected: AccessState
    signals: Tuple[Tuple[str, str], ...]


def _parse_signal(raw: str) -> Tuple[str, str]:
    """``"http.status=200"`` → ``("http.status", "200")`` (split "=" pertama)."""
    signal, _, value = raw.partition("=")
    return (signal, value)


def _load_e9_cases(base: Path) -> List[RealCase]:
    """Kasus berlabel dari E9 (engine-level, fixture lokal).

    Sinyal = assessment event asli per skenario (terekam penuh di file hasil
    sejak benchmark ber-sinyal); ground truth = ``EXPECTED_DIAGNOSIS``
    ter-commit (skenario tanpa entri expected = ACCESS_GRANTED).
    """
    path = base / E9_RESULTS_FILE
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    expected_map = (
        doc.get("summary", {}).get("diagnosis_accuracy_e9", {}).get("expected", {})
    )
    cases: List[RealCase] = []
    for scenario in doc.get("scenarios", {}).get("acquisition", {}).get("uwae", []):
        raw_signals = scenario.get("signals") or []
        if not raw_signals:
            continue
        expected_name = expected_map.get(scenario["scenario_id"], "access_granted")
        cases.append(
            RealCase(
                case_id=f"e9:{scenario['scenario_id']}",
                expected=AccessState(expected_name),
                signals=tuple(_parse_signal(s) for s in raw_signals),
            )
        )
    return cases


def load_real_cases(benchmark_dir: Optional[Path] = None) -> List[RealCase]:
    """Muat kasus berlabel dari file hasil run nyata yang ter-commit.

    Run target nyata (glob ``real-target-*.json``): skenario ``succeeded``
    berlabel ACCESS_GRANTED (200 + konten valid terverifikasi saat run);
    skenario gagal hanya diikutkan bila membawa ``ground_truth_state``
    eksplisit (semantika protokol atas status mentah). E9: semua skenario
    ber-sinyal; label dari ``EXPECTED_DIAGNOSIS`` ter-commit.
    """
    base = Path(benchmark_dir) if benchmark_dir else REPO_BENCHMARK_DIR
    cases: List[RealCase] = []
    for path in sorted(base.glob(REAL_RESULTS_GLOB)):
        source_name = path.stem.replace("real-target-", "", 1)
        doc = json.loads(path.read_text(encoding="utf-8"))
        for scenario in doc.get("scenarios", []):
            assessments = [
                t for t in scenario.get("lineage", []) if t.get("kind") == "assessment"
            ]
            if not assessments:
                continue
            raw_signals = assessments[-1].get("signals") or []
            signals = tuple(_parse_signal(s) for s in raw_signals)
            if not signals:
                continue
            if scenario.get("job_status") == "succeeded":
                expected = AccessState.ACCESS_GRANTED
            elif scenario.get("ground_truth_state"):
                expected = AccessState(scenario["ground_truth_state"])
            else:
                # gagal tanpa ground truth eksplisit → tidak diikutkan (jujur)
                continue
            cases.append(
                RealCase(
                    case_id=f"{source_name}:{scenario['scenario_id']}",
                    expected=expected,
                    signals=signals,
                )
            )
    cases.extend(_load_e9_cases(base))
    return cases


def real_outcomes(
    decided_at: Optional[datetime] = None,
    benchmark_dir: Optional[Path] = None,
) -> List[Tuple[str, bool]]:
    """Jalankan classifier atas kasus nyata → ``(bucket, benar)`` per kasus.

    Ini sekaligus verifikasi konsistensi: classifier harus mereproduksi
    diagnosis run nyata dari sinyal yang sama — granted maupun non-granted
    ber-ground-truth protokol.
    """
    decided_at = decided_at or datetime(2026, 1, 1)
    outcomes: List[Tuple[str, bool]] = []
    for index, case in enumerate(load_real_cases(benchmark_dir)):
        observations = tuple(
            Observation(
                observation_id=f"real-{index}-{position}",
                signal=signal,
                value=value,
                recorded_at=decided_at,
                source="real-run",
            )
            for position, (signal, value) in enumerate(case.signals)
        )
        assessment = classify(
            observations,
            assessment_id=f"real-{index}",
            job_id="corpus-real",
            attempt_id="corpus-real",
            transport_id="real-run",
            decided_at=decided_at,
        )
        outcomes.append(
            (assessment.state.value, assessment.state is case.expected)
        )
    return outcomes
