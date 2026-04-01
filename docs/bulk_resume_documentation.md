# HR-ATS Bulk Resume Analysis — Full Documentation

---

## Complete Endpoint Reference

### Core Criteria & Job Data

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/categories` | All CV evaluation categories with scores. |
| `GET` | `/api/subcategories` | Subcategories. Optional: `?categoryId=N`. |
| `GET` | `/api/criteria` | Specific scoring criteria. Optional: `?subcategoryId=N`. |
| `GET` | `/api/job-titles` | Job titles with their total possible scores. |
| `POST` | `/api/job-title-criteria` | Map a criterion + score to a job title. |

### Resume Analysis (Single)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/pages/analyze-resume` | Legacy manual upload page. |
| `POST` | `/api/analyze-resume` | Real-time Gemini analysis on a single PDF. Accepts multipart or JSON base64. Returns `percent`, `totalScore`, `result`. |

### Bulk Resume Analysis

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/pages/analyze-resume-bulk` | Interactive dashboard for batch processing. |
| `POST` | `/api/analyze-resume-bulk` | Enqueue an array of resumes. Returns `batch_id`. |
| `GET` | `/api/analyze-resume-batch/<batch_id>` | Enriched status: counts + FAILED breakdown. |
| `GET` | `/api/analyze-resume-batch/<batch_id>/results` | Final AI-parsed results for the batch. |

---

---


## Bulk Processing System

### Background Worker Behaviour
- Runs as a **daemon thread** alongside Flask on `python app.py`.
- Polls the local `resumes_bulk.db` SQLite database every 3 seconds.
- Prints `Background worker started.` on initialization.

### Queue & Retry Logic

| Behaviour | Detail |
| :--- | :--- |
| **Max Retries** | 5 total attempts per resume before permanent failure. |
| **Auto-retry** | FAILED jobs with `retry_count < 5` are automatically re-queued without user action. |
| **Manual retry** | Re-uploading a FAILED resume via the UI resets its `retry_count` to 0. |
| **Upsert** | Re-uploading a COMPLETED resume for the same `request_id` skips re-processing (returns cached result). Re-uploading for a different `request_id` resets to PENDING. |

### Rate Limit Safeguard (Gemini Free Tier: 5 RPM)

| Parameter | Value |
| :--- | :--- |
| **N** (consecutive failures to trigger sleep) | 3 |
| **S** (sleep duration) | 60 seconds |

When 3 consecutive resumes fully exhaust all their `tenacity` retries, the worker prints `*** RATE LIMIT SAFEGUARD TRIGGERED ***` and sleeps for 60 seconds to let the Gemini per-minute quota reset.

### Database Reaper
- Runs once per hour inside the worker loop.
- Automatically deletes any rows not updated in the last **7 days** to prevent database bloat.

---

## Enriched Status Endpoint Response

`GET /api/analyze-resume-batch/<batch_id>`

```json
{
  "batch_id": "abc123",
  "total": 5,
  "status_counts": {
    "PENDING": 0,
    "PROCESSING": 0,
    "COMPLETED": 3,
    "FAILED": 2
  },
  "failed_detail": {
    "will_retry_count": 1,
    "permanent_fail_count": 1,
    "will_retry": [
      {
        "id": "smith_cv.pdf",
        "retry_count": 2,
        "retries_remaining": 3,
        "last_error": "429 Resource exhausted"
      }
    ],
    "permanent_fail": [
      {
        "id": "corrupt_cv.pdf",
        "retry_count": 5,
        "retries_remaining": 0,
        "last_error": "Failed to decode base64 PDF bytes"
      }
    ]
  }
}
```

---

## Typical Bulk API Workflow

### 1. Start the Application
```cmd
python app.py
```
Console output: `Background worker started.`

### 2. Submit a Batch
`POST /api/analyze-resume-bulk`
```json
[
  { "id": "smith_cv.pdf", "request_id": 4, "base64_file": "..." },
  { "id": "doe_cv.pdf",   "request_id": 4, "base64_file": "..." }
]
```
Response `202`:
```json
{ "batch_id": "8a3f...", "count": 2 }
```

### 3. Poll Status
`GET /api/analyze-resume-batch/8a3f...`

Poll every few seconds until `PENDING` and `PROCESSING` both reach 0.

### 4. Retrieve Results
`GET /api/analyze-resume-batch/8a3f.../results`

```json
{
  "data": [
    {
      "id": "smith_cv.pdf",
      "status": "COMPLETED",
      "result": { "percent": 85, "totalScore": 170, "result": [...] },
      "error": null
    }
  ]
}
```

> [!IMPORTANT]
> Records are automatically purged after **7 days** of inactivity. Retrieve your results within this window.

> [!TIP]
> Re-submitting a resume ID that previously `FAILED` will automatically reset its retry counter and re-queue it — no need to create a new batch.
