"""Checkpoint per-run untuk harness benchmark.

Kenapa modul ini ada
--------------------
Benchmark di device ini bisa berjalan berjam-jam, dan perangkat Android/
Termux sudah dua kali reboot di tengah benchmark E16. Kalau evidence hanya
ditulis di akhir ``main()``, seluruh run yang sudah selesai hilang tanpa
jejak. Checkpoint JSONL ditulis **setiap run selesai** (flush + fsync), jadi
restart melanjutkan dari cell terakhir, bukan dari nol.

Sifat yang dijaga modul ini:

- **append-only** — satu baris JSON per run, tidak pernah ditulis ulang;
- **tahan mati mendadak** — ``flush`` + ``os.fsync`` setelah tiap baris;
- **baris terpotong diabaikan** — proses bisa mati tepat saat menulis, dan
  baris rusak itu tidak boleh menggagalkan seluruh checkpoint;
- **sidik jari konfigurasi** — record dengan sidik jari berbeda diabaikan dan
  dilaporkan, bukan dipakai diam-diam. Run lama tidak boleh dicampur dengan
  run baru yang memakai kriteria berbeda;
- **simpan ROW KASAR, bukan ringkasan** — kalau aturan adjudikasi berubah,
  ringkasan dihitung ulang dari row yang sama tanpa mengulang benchmark.

Modul ini dipakai oleh ``browser_diff_bench.py`` (E16), ``cross_impl_bench.py``
(E14) dan ``session_diff_bench.py`` (E15). Fingerprint harness dihitung oleh
setiap harness — nilainya berbeda per harness karena konfigurasi yang
di-fingerprint-kan juga berbeda — lalu diteruskan ke sini.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

# Jeda antar-run yang dianggap INTERUPSI, bukan jeda normal. Jeda normal di
# device ini <= ~37 s (run UWAE dengan rantai retry + cold start chromium).
# Jeda jauh di atas itu berarti perangkat mati / harness restart, dan itu
# harus terlihat di evidence sebagai batas segmen eksekusi.
DEFAULT_INTERRUPTION_GAP_THRESHOLD_S = 60.0


class Checkpoint:
    """Penyimpan baris JSONL: satu baris per run yang selesai.

    Kunci run adalah ``(scope_id, subject_id, index)`` — scope = skenario,
    subject = lengan/engine, index = nomor run. Restart melanjutkan dari cell
    terakhir, bukan mengulang sel yang sudah selesai.
    """

    def __init__(self, path: Path, fingerprint: str):
        self.path = Path(path)
        self.fingerprint = fingerprint
        self.rows: Dict[str, dict] = {}
        self.reused_keys: Set[str] = set()
        self.ignored_records = 0
        self._load()

    @staticmethod
    def _key(scope_id: str, subject_id: str, index: int) -> str:
        return "%s|%s|%03d" % (scope_id, subject_id, index)

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # Baris terakhir bisa terpotong kalau proses mati tepat
                    # saat menulis. Abaikan baris rusak; sisanya tetap valid.
                    self.ignored_records += 1
                    continue
                if record.get("fingerprint") != self.fingerprint:
                    self.ignored_records += 1
                    continue
                # Skema kunci kanonik: scope_id/subject_id/index. File
                # checkpoint yang dibuat sebelum modul ini ada memakai
                # scenario_id/arm_id/run_index — tetap dibaca supaya checkpoint
                # E16 yang sudah berisi 480 run tidak hilang tanpa sebab.
                scope_id = record.get("scope_id", record.get("scenario_id"))
                subject_id = record.get("subject_id", record.get("arm_id"))
                index = record.get("index", record.get("run_index"))
                if scope_id is None or subject_id is None or index is None:
                    self.ignored_records += 1
                    continue
                key = self._key(scope_id, subject_id, index)
                self.rows[key] = record["row"]

    def get(self, scope_id: str, subject_id: str, index: int) -> Optional[dict]:
        row = self.rows.get(self._key(scope_id, subject_id, index))
        if row is not None:
            self.reused_keys.add(self._key(scope_id, subject_id, index))
        return row

    def append(
        self, scope_id: str, subject_id: str, index: int, row: dict
    ) -> None:
        key = self._key(scope_id, subject_id, index)
        record = {
            "fingerprint": self.fingerprint,
            "scope_id": scope_id,
            "subject_id": subject_id,
            "index": index,
            "row": row,
        }
        self.rows[key] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def stats(self) -> Dict:
        return {
            "checkpoint_path": str(self.path),
            "harness_fingerprint": self.fingerprint,
            "runs_in_checkpoint": len(self.rows),
            "runs_reused": len(self.reused_keys),
            "records_ignored": self.ignored_records,
        }


def execution_sessions(
    rows: List[dict], gap_threshold_s: float = DEFAULT_INTERRUPTION_GAP_THRESHOLD_S
) -> List[dict]:
    """Segmen eksekusi, dihitung dari rekam waktu tiap run.

    Jeda antar-run yang jauh di atas jeda normal menandai restart harness
    (perangkat mati / reboot). Segmen dipisah berdasarkan jeda itu, BUKAN
    berdasarkan urutan skenario-lengan, supaya hasilnya tetap benar walau
    urutan run berubah.
    """
    ordered = sorted(
        (row for row in rows if row.get("recorded_at")),
        key=lambda row: row["recorded_at"],
    )
    groups: List[List[dict]] = []
    current: List[dict] = []
    previous: Optional[dict] = None
    for row in ordered:
        if previous is not None:
            gap = (
                datetime.fromisoformat(row["recorded_at"])
                - datetime.fromisoformat(previous["recorded_at"])
            ).total_seconds()
            if gap > gap_threshold_s:
                groups.append(current)
                current = []
        current.append(row)
        previous = row
    if current:
        groups.append(current)

    sessions: List[dict] = []
    for index, group in enumerate(groups, start=1):
        started_at = group[0]["recorded_at"]
        ended_at = group[-1]["recorded_at"]
        base_urls: List[str] = []
        for row in group:
            url = row.get("fixture_base_url")
            if url and url not in base_urls:
                base_urls.append(url)
        gap_before_s = 0.0
        if index > 1:
            previous_end = groups[index - 2][-1]["recorded_at"]
            gap_before_s = round(
                (
                    datetime.fromisoformat(started_at)
                    - datetime.fromisoformat(previous_end)
                ).total_seconds(),
                1,
            )
        sessions.append(
            {
                "session": index,
                "runs": len(group),
                "started_at": started_at,
                "ended_at": ended_at,
                "wall_clock_span_s": round(
                    (
                        datetime.fromisoformat(ended_at)
                        - datetime.fromisoformat(started_at)
                    ).total_seconds(),
                    1,
                ),
                "gap_before_s": gap_before_s,
                "fixture_base_urls": base_urls,
            }
        )
    return sessions


def timing_evidence(
    rows: List[dict],
    checkpoint_stats: Dict,
    invocation_wall_clock_s: float,
    gap_threshold_s: float = DEFAULT_INTERRUPTION_GAP_THRESHOLD_S,
) -> Dict:
    """Durasi benchmark, diuraikan sehingga tidak bisa disalahbaca.

    ``elapsed_s`` tingkat dokumen pernah hanya mengukur SATU pemanggilan
    harness: kalau sebagian besar run diambil dari checkpoint, angka itu
    jauh lebih kecil daripada durasi kerja sebenarnya, dan pembaca akan
    salah menyimpulkan seluruh benchmark hanya memakan waktu itu.

    Jadi durasi dipublikasikan sebagai tiga hal yang eksplisit: durasi
    kerja terukur (jumlah ``elapsed_ms`` semua run), rentang pengukuran
    (rekam run pertama sampai terakhir, plus segmen eksekusi), dan durasi
    pemanggilan harness ini -- yang terakhir diberi label bahwa cakupannya
    HANYA invocation yang menulis dokumen.
    """
    measured_ms = [
        float(row["elapsed_ms"])
        for row in rows
        if row.get("elapsed_ms") is not None
    ]
    stamps = sorted(
        row["recorded_at"] for row in rows if row.get("recorded_at")
    )
    window_span_s = None
    if len(stamps) >= 2:
        window_span_s = round(
            (
                datetime.fromisoformat(stamps[-1])
                - datetime.fromisoformat(stamps[0])
            ).total_seconds(),
            2,
        )
    reused = checkpoint_stats.get("runs_reused", 0)
    return {
        "measured_arm_execution_s_total": round(sum(measured_ms) / 1000.0, 2),
        "measured_arm_execution_runs": len(measured_ms),
        "measured_arm_execution_note": (
            "Jumlah waktu eksekusi lengan yang terukur, dijumlahkan dari "
            "elapsed_ms tiap run. Ini durasi kerja yang sebenarnya, dan "
            "bukan durasi satu pemanggilan harness."
        ),
        "measurement_window": {
            "first_run_recorded_at": stamps[0] if stamps else None,
            "last_run_recorded_at": stamps[-1] if stamps else None,
            "wall_clock_span_s": window_span_s,
            "note": (
                "Rentang rekam run pertama sampai run terakhir di perangkat. "
                "Lebih besar dari durasi kerja terukur karena mencakup jeda "
                "antar-run dan jeda restart perangkat."
            ),
        },
        "execution_sessions": execution_sessions(rows, gap_threshold_s),
        "interruption_gap_threshold_s": gap_threshold_s,
        "harness_invocation": {
            "wall_clock_s": round(invocation_wall_clock_s, 2),
            "runs_executed_this_invocation": len(rows) - reused,
            "runs_reused_from_checkpoint": reused,
            "note": (
                "Durasi pemanggilan harness yang menulis dokumen ini. "
                "Kalau sebagian besar run diambil dari checkpoint, angka ini "
                "TIDAK mencakup durasi eksekusi run tersebut -- makanya "
                "durasi kerja terukur dipublikasikan terpisah."
            ),
        },
    }
