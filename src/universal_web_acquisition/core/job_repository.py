"""Job repository for the Universal Web Acquisition Engine."""

import base64
import json
import os
import sqlite3
from typing import Dict, List, Optional
from datetime import datetime

from universal_web_acquisition.core.job_model import Job, JobStatus

#: Kolom tabel ``jobs`` dalam urutan TETAP. Dipakai eksplisit (bukan
#: ``SELECT *``) supaya pemetaan baris tidak berubah kalau skema database
#: bertambah kolom — termasuk lewat migrasi yang menambah kolom baru.
_JOB_COLUMNS = (
    "job_id",
    "url",
    "status",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "artifact_id",
    "error",
    "retry_count",
    "max_retries",
    "request_spec",
    "retry_budget",
    "peak_memory_bytes",
)

#: SELECT dengan daftar kolom eksplisit. Dibentuk sekali dari konstanta
#: modul — bukan input pengguna — jadi aman disisipkan ke SQL.
_JOB_SELECT = "SELECT " + ", ".join(_JOB_COLUMNS) + " FROM jobs"


def _encode_request(job: Job) -> Optional[str]:
    """Serialisasi semantik request job (method/body/header) untuk persistensi.

    Job GET tanpa body dan tanpa header tidak butuh kolom — ``request_spec``
    NULL. Database lama yang belum punya kolom itu tetap terbaca apa adanya.
    """
    if job.method.upper() == "GET" and job.body is None and not job.headers:
        return None
    payload = {
        "method": job.method,
        "headers": job.headers or {},
        "body_b64": (
            base64.b64encode(job.body).decode("ascii")
            if job.body is not None
            else None
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _encode_retry_budget(job: Job) -> Optional[str]:
    """Serialisasi retry budget per ReasonCode."""
    if job.retry_budget is None:
        return None
    return json.dumps(job.retry_budget, ensure_ascii=False, sort_keys=True)


def _decode_retry_budget(raw: Optional[str]) -> Optional[Dict[str, int]]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _decode_request(raw: Optional[str]) -> Dict[str, object]:
    """Baca kembali semantik request job.

    ``None`` = job GET biasa (kolom belum ada di database lama, atau job
    memang tanpa body/header). Isi yang rusak **tidak** boleh diam-diam
    berubah jadi GET: diam-diam mengubah POST menjadi GET akan mengirim
    permintaan yang berbeda dari yang/job minta — jadi itu error, bukan
    fallback.
    """
    if not raw:
        return {"method": "GET", "body": None, "headers": None}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"request_spec job korup: {raw[:120]!r}") from exc
    body = None
    body_b64 = payload.get("body_b64")
    if body_b64:
        try:
            body = base64.b64decode(body_b64)
        except (TypeError, ValueError) as exc:
            raise ValueError("request_spec job korup: body_b64 tidak valid") from exc
    return {
        "method": payload.get("method") or "GET",
        "body": body,
        "headers": payload.get("headers") or None,
    }


class JobRepository:
    """Repository for job persistence."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize the job repository.
        
        Args:
            db_path: Optional path to the SQLite database file
        """
        self.db_path = db_path or "jobs.db"
        self._init_db()
        
    def _init_db(self) -> None:
        """Initialize the database schema."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    artifact_id TEXT,
                    error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    request_spec TEXT,
                    retry_budget TEXT,
                    peak_memory_bytes INTEGER
                )
            """)
            # Migrasi idempotent: database yang dibuat SEBELUM kolom
            # request_spec/retry_budget/peak_memory_bytes ada tidak mendapat
            # kolom itu dari CREATE TABLE IF NOT EXISTS — jadi kolom harus
            # ditambah eksplisit. Tanpa ini, database lama akan gagal saat
            # job disimpan.
            existing = {
                row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            for col in ("request_spec", "retry_budget", "peak_memory_bytes"):
                if col not in existing:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_id TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    detail TEXT,
                    at TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()
            
    def save_job(self, job: Job) -> None:
        """Save a job to the repository.
        
        Args:
            job: The job to save
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO jobs (
                    job_id, url, status, created_at, updated_at,
                    started_at, completed_at, artifact_id, error,
                    retry_count, max_retries, request_spec, retry_budget,
                    peak_memory_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.job_id,
                job.url,
                job.status.value,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
                job.started_at.isoformat() if job.started_at else None,
                job.completed_at.isoformat() if job.completed_at else None,
                job.artifact_id,
                job.error,
                job.retry_count,
                job.max_retries,
                _encode_request(job),
                _encode_retry_budget(job),
                job.peak_memory_bytes,
            ))
            conn.commit()
        finally:
            conn.close()
            
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID.
        
        Args:
            job_id: The job ID
            
        Returns:
            The job if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                _JOB_SELECT + " WHERE job_id = ?", (job_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
                
            return self._row_to_job(row)
        finally:
            conn.close()
            
    def list_jobs(self, limit: int = 10) -> List[Job]:
        """List recent jobs.
        
        Args:
            limit: Maximum number of jobs to return
            
        Returns:
            List of jobs, most recent first
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                _JOB_SELECT + " ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = cursor.fetchall()
            
            return [self._row_to_job(row) for row in rows]
        finally:
            conn.close()
            
    def _row_to_job(self, row: tuple) -> Job:
        """Convert a database row to a Job object.
        
        Args:
            row: The database row
            
        Returns:
            The Job object
        """
        (
            job_id, url, status, created_at, updated_at,
            started_at, completed_at, artifact_id, error,
            retry_count, max_retries, request_spec, retry_budget,
            peak_memory_bytes
        ) = row

        request = _decode_request(request_spec)
        retry_budget = _decode_retry_budget(retry_budget)
        job = Job(
            job_id=job_id,
            url=url,
            status=JobStatus(status),
            created_at=datetime.fromisoformat(created_at),
            updated_at=datetime.fromisoformat(updated_at),
            artifact_id=artifact_id,
            error=error,
            retry_count=retry_count,
            max_retries=max_retries,
            method=str(request["method"]),
            body=request["body"],
            headers=request["headers"],
            retry_budget=retry_budget,
            peak_memory_bytes=peak_memory_bytes,
        )
        
        if started_at:
            job.started_at = datetime.fromisoformat(started_at)
        if completed_at:
            job.completed_at = datetime.fromisoformat(completed_at)

        return job

    # -- attempt tracking (G6 durability, §5.1–§5.2) -------------------------

    def start_attempt(self, job_id: str, attempt_id: str, transport: str) -> None:
        """Catat attempt RUNNING — ditulis SEBELUM eksekusi agar crash
        meninggalkan jejak yang dapat dipulihkan."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO attempts
                    (attempt_id, job_id, transport, status, artifact_id, error,
                     started_at, finished_at)
                VALUES (?, ?, ?, 'running', NULL, NULL, ?, NULL)
                """,
                (attempt_id, job_id, transport, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def finish_attempt(
        self,
        attempt_id: str,
        status: str,
        artifact_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE attempts
                SET status = ?, artifact_id = ?, error = ?, finished_at = ?
                WHERE attempt_id = ?
                """,
                (status, artifact_id, error, datetime.now().isoformat(), attempt_id),
            )
            conn.commit()
        finally:
            conn.close()

    def latest_attempt(self, job_id: str) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT attempt_id, transport, status, artifact_id, error,
                       started_at, finished_at
                FROM attempts WHERE job_id = ?
                ORDER BY started_at DESC, rowid DESC LIMIT 1
                """,
                (job_id,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        keys = (
            "attempt_id",
            "transport",
            "status",
            "artifact_id",
            "error",
            "started_at",
            "finished_at",
        )
        return dict(zip(keys, row))

    def list_attempts(self, job_id: str) -> List[dict]:
        """Seluruh attempt satu job berurutan — jejak audit (§5.1)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT attempt_id, transport, status, artifact_id, error,
                       started_at, finished_at
                FROM attempts WHERE job_id = ?
                ORDER BY started_at, rowid
                """,
                (job_id,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        keys = (
            "attempt_id",
            "transport",
            "status",
            "artifact_id",
            "error",
            "started_at",
            "finished_at",
        )
        return [dict(zip(keys, row)) for row in rows]

    def record_event(self, job_id: str, event: str, detail: str = "") -> None:
        """Catat transisi state yang dapat diaudit (tabel job_events, §5.1)."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO job_events (job_id, event, detail, at) VALUES (?, ?, ?, ?)",
                (job_id, event, detail, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def list_events(self, job_id: str) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT event, detail, at FROM job_events WHERE job_id = ? ORDER BY id",
                (job_id,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [dict(zip(("event", "detail", "at"), row)) for row in rows]

    def latest_checkpoint(self, job_id: str) -> Optional[dict]:
        """Checkpoint unduhan terakhir (A09) — durabel lintas restart proses."""
        for event in reversed(self.list_events(job_id)):
            if event["event"] == "download_checkpoint":
                try:
                    return json.loads(event["detail"])
                except json.JSONDecodeError:
                    return None
        return None

    def recover_interrupted(self) -> List[str]:
        """Pulihkan job non-terminal pasca-crash (§5.2) — kembalikan id yang diproses.

        Aturan:
        - job RUNNING + attempt terakhir RUNNING → attempt ditandai
          INTERRUPTED (bukan SUCCESS); job diantrekan ulang SELAMA anggaran
          retry lintas-restart tersedia, selain itu FAILED budget_exhausted;
        - job RUNNING + attempt terakhir SUCCEEDED dengan artifact → job
          diselesaikan dari bukti — TANPA re-akuisisi (tidak ada artifact ganda);
        - NEEDS_USER tidak pernah dipulihkan otomatis (ACP §2.2);
        - job terminal tidak disentuh.
        """
        processed: List[str] = []
        for job in self.list_jobs(limit=1000):
            if job.status is not JobStatus.RUNNING:
                continue
            attempt = self.latest_attempt(job.job_id)
            if attempt is None:
                continue
            if attempt["status"] == "succeeded" and attempt["artifact_id"]:
                # Selesaikan dari bukti — artifact sudah ada, jangan akuisisi ulang.
                job.mark_completed(attempt["artifact_id"])
                self.save_job(job)
                self.record_event(
                    job.job_id,
                    "recovered_completed",
                    f"attempt {attempt['attempt_id']} succeeded; job diselesaikan dari bukti",
                )
                processed.append(job.job_id)
                continue
            if attempt["status"] in ("running", "succeeded"):
                # RUNNING saat crash, atau succeeded tanpa artifact (tak terduga)
                # → keduanya diperlakukan terputus.
                self.finish_attempt(attempt["attempt_id"], "interrupted")
                if job.retry_count >= job.max_retries:
                    job.mark_failed(
                        "budget_exhausted: attempt terputus melebihi anggaran retry "
                        f"({job.retry_count}/{job.max_retries})"
                    )
                    self.save_job(job)
                    self.record_event(
                        job.job_id, "recovery_budget_exhausted", attempt["attempt_id"]
                    )
                else:
                    job.retry_count += 1
                    job.status = JobStatus.QUEUED
                    job.updated_at = datetime.now()
                    self.save_job(job)
                    self.record_event(
                        job.job_id,
                        "recovered_requeued",
                        f"attempt {attempt['attempt_id']} INTERRUPTED; diantrekan ulang "
                        f"(retry {job.retry_count}/{job.max_retries})",
                    )
                processed.append(job.job_id)
        return processed
