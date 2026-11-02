"""Adapter export: JSON (lossless) dan CSV (kolom tetap + fields JSON)."""

import csv
import json
from pathlib import Path
from typing import List

EXPORT_FORMATS = ("json", "csv")


def rows_from_events(events: List[dict]) -> List[dict]:
    """Bentuk baris export dari event ``extraction`` — persis apa yang tercatat.

    ``events`` = hasil ``JobRepository.list_events(job_id)`` (dict dengan
    kunci ``event``/``detail``/``at``); hanya event ``extraction`` yang
    relevan (disaring pemanggil).
    """
    rows = []
    for e in events:
        detail = e.get("detail") or "{}"
        if isinstance(detail, str):
            detail = json.loads(detail)
        rows.append(
            {
                "extractor": detail.get("extractor"),
                "format": detail.get("format"),
                "fields": detail.get("fields") or {},
                "source_sha256": detail.get("source_sha256"),
                "source_size_bytes": detail.get("source_size_bytes"),
                "recorded_at": e.get("at"),
            }
        )
    return rows


class JsonExporter:
    """Export lossless ke JSON — array objek, ``fields`` tetap bersarang."""

    format_name = "json"

    def export(self, rows: List[dict], output_path: str) -> int:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return len(rows)


class CsvExporter:
    """Export ke CSV — kolom tetap + ``fields`` sebagai string JSON (lossless)."""

    format_name = "csv"

    COLUMNS = (
        "extractor",
        "format",
        "source_sha256",
        "source_size_bytes",
        "recorded_at",
        "fields_json",
    )

    def export(self, rows: List[dict], output_path: str) -> int:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "extractor": row["extractor"],
                        "format": row["format"],
                        "source_sha256": row["source_sha256"],
                        "source_size_bytes": row["source_size_bytes"],
                        "recorded_at": row["recorded_at"],
                        "fields_json": json.dumps(
                            row["fields"], ensure_ascii=False, sort_keys=True
                        ),
                    }
                )
        return len(rows)


def get_exporter(format_name: str):
    """Pilih exporter berdasar nama format — ValueError untuk yang tak dikenal."""
    exporters = {e.format_name: e for e in (JsonExporter(), CsvExporter())}
    if format_name not in exporters:
        raise ValueError(
            f"format export tidak dikenal: {format_name} "
            f"(pilihan: {', '.join(sorted(exporters))})"
        )
    return exporters[format_name]
