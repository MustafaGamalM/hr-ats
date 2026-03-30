# HR-ATS Bulk Resume Analysis Documentation

This document provides a comprehensive overview of the newly implemented bulk resume analysis system and the existing API surface.

## Modified Files in This Session

| File | Status | Description |
| :--- | :--- | :--- |
| [analyze_resume_bulk.py](file:///d:/Handsa/Mashura%20Internship/hr-ats/hr-ats/analyze_resume_bulk.py) | **NEW** | Core background processor, SQLite queue logic, and Gemini retry handler. |
| [analyze_resume_api.py](file:///d:/Handsa/Mashura%20Internship/hr-ats/hr-ats/analyze_resume_api.py) | **MODIFIED** | Added bulk upload, status tracking, and result retrieval endpoints. |
| [app.py](file:///d:/Handsa/Mashura%20Internship/hr-ats/hr-ats/app.py) | **MODIFIED** | Integrated the background worker as a daemon thread. |
| [requirements.txt](file:///d:/Handsa/Mashura%20Internship/hr-ats/hr-ats/requirements.txt) | **MODIFIED** | Added `tenacity` for robust API retry logic. |
| [.gitignore](file:///d:/Handsa/Mashura%20Internship/hr-ats/hr-ats/.gitignore) | **NEW** | Standard Python and project-specific excludes (including `.db` files). |
| [analyze_resume_bulk.html](file:///d:/Handsa/Mashura%20Internship/hr-ats/hr-ats/templates/analyze_resume_bulk.html) | **NEW** | Interactive UI for batch uploading and real-time tracking. |

---

## Endpoint Description List

### Core Criteria & Job Data
- **`GET /api/categories`**: Retrieves all resume evaluation categories.
- **`GET /api/subcategories`**: Retrieves subcategories. (Optional: `?categoryId=N`).
- **`GET /api/criteria`**: Retrieves specific scoring criteria. (Optional: `?subcategoryId=N`).
- **`GET /api/job-titles`**: Retrieves job titles and their total possible scores.
- **`POST /api/job-title-criteria`**: Maps a specific criterion and score to a job title.

### Resume Analysis (Single)
- **`GET /pages/analyze-resume`**: Serves the legacy manual upload page.
- **`POST /api/analyze-resume`**: Real-time analysis of a single PDF (Multipart file or JSON base64).

### Bulk Resume Analysis (New)
- **`GET /pages/analyze-resume-bulk`**: Serves the new interactive dashboard for batch processing.
- **`POST /api/analyze-resume-bulk`**: Enqueues an array of resumes for background processing.
- **`GET /api/analyze-resume-batch/<batch_id>`**: Returns status counts (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`).
- **`GET /api/analyze-resume-batch/<batch_id>/results`**: Retrieves the final parsed AI data for all resumes in the batch.

---

## Typical Bulk API Workflow

To process large batches of resumes programmatically, follow this sequence:

### 1. Initiate the Batch
Send a JSON array of resumes to the bulk endpoint. Each item requires a unique `id` (usually the filename) and a `request_id` (the job description ID).

**Endpoint**: `POST /api/analyze-resume-bulk`
```json
[
  { "id": "smith_cv.pdf", "request_id": 4, "base64_file": "..." },
  { "id": "doe_cv.pdf", "request_id": 4, "base64_file": "..." }
]
```
> [!TIP]
> This endpoint supports **Upsert** logic. Re-uploading the same `id` for the same `request_id` will immediately return existing results without re-consuming Gemini API units.

### 2. Capture the Batch ID
The API returns a `202 Accepted` response with a unique `batch_id`.
```json
{ "batch_id": "8a3f..." }
```

### 3. Monitor Progress
Poll the status endpoint every few seconds to track the movement from `PENDING` to `COMPLETED`.

**Endpoint**: `GET /api/analyze-resume-batch/8a3f...`
```json
{
  "status_counts": { "PENDING": 0, "COMPLETED": 2 },
  "total": 2
}
```

### 4. Retrieve Final Results
Once `PENDING` and `PROCESSING` counts reach zero, fetch the final payload.

**Endpoint**: `GET /api/analyze-resume-batch/8a3f.../results`
```json
{
  "data": [
    { "id": "smith_cv.pdf", "status": "COMPLETED", "result": { ... } }
  ]
}
```

> [!IMPORTANT]
> To prevent storage bloat, the background worker automatically deletes records that have been un-touched (last_updated) for more than **7 days**. Ensure you retrieve your results within this window.
