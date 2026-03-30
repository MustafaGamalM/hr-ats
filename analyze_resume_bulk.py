import sqlite3
import os
import time
import json
import uuid
from typing import List, Dict, Any

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from analyze_resume import send_prompt_and_pdf_to_gemini
# We'll import fetch_rows when needed to avoid circular dependencies

# --- Configuration ---
DB_PATH = "resumes_bulk.db"
POLL_INTERVAL = 3  # seconds

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def setup_sqlite_db():
    """
    Initializes the local SQLite database and table if it doesn't exist.
    """
    # SQLite creates the file automatically if it doesn't exist when we connect.
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cv_jobs (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                request_id INTEGER,
                status TEXT DEFAULT 'PENDING',
                cv_payload TEXT,
                ai_response TEXT,
                error_log TEXT,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()

def enqueue_resumes(batch_id: str, resumes: List[Dict[str, Any]]):
    """
    Inserts a list of resumes into the cv_jobs table for background processing.
    Each resume in the list should have 'id', 'request_id', and 'base64_file'.
    If 'id' already exists, it links it to the current batch. If the target request_id 
    has changed, it resets it to PENDING to be re-processed; otherwise it keeps the old result.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        for r in resumes:
            cursor.execute("""
                INSERT INTO cv_jobs (id, batch_id, request_id, status, cv_payload)
                VALUES (?, ?, ?, 'PENDING', ?)
                ON CONFLICT(id) DO UPDATE SET 
                    batch_id = excluded.batch_id,
                    cv_payload = excluded.cv_payload,
                    status = CASE WHEN cv_jobs.request_id != excluded.request_id THEN 'PENDING' ELSE cv_jobs.status END,
                    request_id = excluded.request_id,
                    last_updated = CURRENT_TIMESTAMP
            """, (str(r.get("id")), batch_id, r.get("request_id"), r.get("base64_file")))
        conn.commit()
    finally:
        conn.close()

def get_batch_status(batch_id: str) -> Dict[str, Any]:
    """
    Queries the database to return the current status of all CVs in a batch.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) as count FROM cv_jobs WHERE batch_id = ? GROUP BY status", (batch_id,))
        rows = cursor.fetchall()
        
        status_counts = { "PENDING": 0, "PROCESSING": 0, "COMPLETED": 0, "FAILED": 0 }
        total = 0
        for row in rows:
            status_counts[row["status"]] = row["count"]
            total += row["count"]
            
        return {
            "batch_id": batch_id,
            "total": total,
            "status_counts": status_counts
        }
    finally:
        conn.close()

def get_batch_results(batch_id: str) -> List[Dict[str, Any]]:
    """
    Retrieves all COMPLETED or FAILED resume profiles for a given batch.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, request_id, status, ai_response, error_log FROM cv_jobs WHERE batch_id = ?", (batch_id,))
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            ai_data = None
            if row["ai_response"]:
                try:
                    ai_data = json.loads(row["ai_response"])
                except Exception:
                    ai_data = row["ai_response"]
                    
            results.append({
                "id": row["id"],
                "request_id": row["request_id"],
                "status": row["status"],
                "result": ai_data,
                "error": row["error_log"]
            })
        return results
    finally:
        conn.close()


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type(Exception) # You can refine this to specific Gemini API errors if needed
)
def call_gemini_with_retry(request_id: int, base64_file: str, fetch_rows_func):
    """
    Wrapper for Gemini call that utilizes tenacity to handle rate limits and transient errors.
    """
    res = send_prompt_and_pdf_to_gemini(
        request_id=request_id,
        base64_file=base64_file,
        fetch_rows=fetch_rows_func,
        return_raw_response=False,
        raise_on_error=True # Important: Raise error so tenacity can catch it and retry
    )
    if isinstance(res, dict) and "error" in res:
        # Sometimes the function might return an error dict instead of throwing
        raise Exception(f"Gemini API returned an error: {res['error']}")
    return res


def process_single_cv(cv_row: sqlite3.Row):
    """
    Logic for processing a single CV through Gemini with tenacity retry logic.
    """
    # Import inside to prevent circular dependency
    from app import fetch_rows 
    
    row_id = cv_row["id"]
    request_id = cv_row["request_id"]
    cv_payload = cv_row["cv_payload"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        ai_response = call_gemini_with_retry(request_id, cv_payload, fetch_rows)
        
        # Success
        cursor.execute("""
            UPDATE cv_jobs 
            SET status = 'COMPLETED', ai_response = ?, last_updated = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (json.dumps(ai_response), row_id))
        
    except Exception as exc:
        # Failure
        cursor.execute("""
            UPDATE cv_jobs 
            SET status = 'FAILED', error_log = ?, last_updated = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (str(exc), row_id))
        
    finally:
        conn.commit()
        conn.close()

def background_worker():
    """
    Infinite loop that polls SQLite for PENDING resumes and processes them.
    Also acts as a reaper, cleaning up old untouched rows.
    """
    # Ensure db is setup before starting
    setup_sqlite_db()
    
    last_cleanup = 0
    
    while True:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Reaper logic: Delete rows un-touched for > 7 days every hour to prevent DB bloat
            now = time.time()
            if now - last_cleanup > 3600:
                cursor.execute("DELETE FROM cv_jobs WHERE last_updated <= datetime('now', '-7 days')")
                conn.commit()
                last_cleanup = now
            
            # Find one pending job
            cursor.execute("SELECT * FROM cv_jobs WHERE status = 'PENDING' LIMIT 1")
            job = cursor.fetchone()
            
            if not job:
                # No jobs, sleep and poll again
                conn.close()
                time.sleep(POLL_INTERVAL)
                continue
                
            job_id = job["id"]
            
            # Claim the job
            cursor.execute("UPDATE cv_jobs SET status = 'PROCESSING', last_updated = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
            conn.commit()
            conn.close()
            
            # Process the claimed job
            process_single_cv(job)
            
        except Exception as exc:
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    setup_sqlite_db()
    # To run the worker independently:
    # background_worker()

