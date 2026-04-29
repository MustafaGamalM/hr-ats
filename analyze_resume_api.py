# analyze_resume_page.py
from typing import Iterable, Tuple
from flask import render_template, request, jsonify
import json
import pyodbc
import uuid
from analyze_resume import send_prompt_and_pdf_to_gemini
from analyze_resume_bulk import enqueue_resumes
from analyze_resume import build_gemini_prompt, compute_criteria_hash


def analyze_resume_page(app, fetch_rows):
    """
    Register routes for analyzing/rescoring resumes.

    Routes:
      - GET  /pages/analyze-resume               -> simple upload page
      - GET  /pages/analyze-resume-bulk          -> bulk upload page UI
      - POST /api/analyze-resume                 -> accepts multipart file + request_id OR JSON
      - POST /api/analyze-resume-bulk            -> bulk uploads resumes
      - GET  /api/analyze-resume-batch/<batch_id> -> gets status counts of a batch
      - GET  /api/analyze-resume-batch/<batch_id>/results -> gets the final parsed data
    """

    @app.get("/pages/analyze-resume")
    def analyze_page():
        """
        Optional simple page for manual testing. Expects a template named 'analyze_resume.html'
        (you can create a minimal HTML form that posts a file and request_id to /api/analyze-resume).
        If the template does not exist, return a small HTML fallback.
        """
        try:
            return render_template("analyze_resume.html")
        except Exception:
            # Minimal fallback HTML form (no JS)
            return (
                """
            <html>
              <body>
                <h3>Analyze Resume</h3>
                <form method="post" action="/api/analyze-resume" enctype="multipart/form-data">
                  <label>Request ID: <input type="text" name="request_id" /></label><br/><br/>
                  <label>Resume PDF: <input type="file" name="file" accept="application/pdf" /></label><br/><br/>
                  <button type="submit">Upload & Analyze</button>
                </form>
              </body>
            </html>
            """,
                200,
            )

    @app.get("/pages/analyze-resume-bulk")
    def analyze_resume_bulk_page():
        """
        Serves the frontend page that orchestrates the bulk resume upload logic.
        """
        try:
            return render_template("analyze_resume_bulk.html")
        except Exception as exc:
            return (
                f"Error loading template: {exc}. Ensure templates/analyze_resume_bulk.html exists.",
                500,
            )

    @app.post("/api/analyze-resume")
    def analyze_resume():
        """
        Accepts either:
          - multipart/form-data with 'file' (file upload) and 'request_id' (form field)
          - or JSON body: { "request_id": <int>, "base64_file": "<base64 string>" }

        Returns JSON containing the Gemini-parsed result and percent score, e.g.:
          { "result": {...}, "percent": 85 }
        """
        # Try JSON body first
        base64_file = None
        request_id_raw = None

        if request.is_json:
            payload = request.get_json(silent=True)
            if not payload:
                return jsonify({"error": "Invalid JSON payload"}), 400

            request_id_raw = payload.get("request_id")
            base64_file = payload.get("base64_file")
        else:
            # multipart/form-data fallback
            request_id_raw = request.form.get("request_id") or request.values.get(
                "request_id"
            )
            upload = request.files.get("file")
            if upload:
                try:
                    pdf_bytes = upload.read()
                    import base64

                    base64_file = base64.b64encode(pdf_bytes).decode("utf-8")
                except Exception as exc:
                    return (
                        jsonify(
                            {"error": f"Failed to read/encode uploaded file: {exc}"}
                        ),
                        400,
                    )

        # Validate request_id
        if request_id_raw is None:
            return jsonify({"error": "Missing request_id"}), 400

        try:
            request_id = int(request_id_raw)
        except (TypeError, ValueError):
            return (
                jsonify(
                    {
                        "error": f"Invalid request_id (must be integer). Got: {request_id_raw!r}"
                    }
                ),
                400,
            )

        if not base64_file:
            return (
                jsonify(
                    {
                        "error": "Missing file content. Provide multipart 'file' or JSON 'base64_file'."
                    }
                ),
                400,
            )

        # Call analyze_resume.send_prompt_and_pdf_to_gemini
        try:
            res = send_prompt_and_pdf_to_gemini(
                request_id=request_id,
                base64_file=base64_file,
                fetch_rows=fetch_rows,
                return_raw_response=False,
                raise_on_error=False,
            )

            # If underlying function returned error structure, forward it
            if isinstance(res, dict) and "error" in res:
                return jsonify({"error": res["error"]}), 500

            # Expected shape: {"result": {...}, "percent": N}
            return jsonify(res), 200

        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/api/analyze-resume-bulk")
    def analyze_resume_bulk():
        """
        Accepts a JSON payload structured like this:
        {
          "auth_token": "...",
          "company_id": 1,
          "business_entity_id": 1,
          "request_id": 10,
          "resumes": [
            { "id": "uuid-1", "attachment_id": 801 },
            ...
          ]
        }

        Returns a batch_id for tracking.
        """
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Payload must be a JSON object"}), 400

        auth_token = payload.get("auth_token")
        company_id = payload.get("company_id")
        business_entity_id = payload.get("business_entity_id")
        request_id = payload.get("request_id")
        resumes = payload.get("resumes")

        if not all([auth_token, company_id, business_entity_id, request_id]):
            return (
                jsonify(
                    {
                        "error": "Missing required top-level fields (auth_token, company_id, business_entity_id, request_id)"
                    }
                ),
                400,
            )

        if not isinstance(resumes, list) or not resumes:
            return (
                jsonify({"error": "Payload must contain a non-empty 'resumes' array"}),
                400,
            )

        # Generate a unique batch ID
        batch_id = str(uuid.uuid4())

        # --- Compute criteria hash BEFORE enqueueing ---
        # This detects if criteria for this request_id have changed since the
        # last analysis, even when the request_id itself hasn't changed.
        # build_gemini_prompt fetches criteria rows from the DB and returns their hash.
        try:
            prompt_data = build_gemini_prompt(request_id, fetch_rows)
            if "error_msg" in prompt_data:
                return (
                    jsonify({"error": f"Could not fetch criteria: {prompt_data['error_msg']}"}),
                    400,
                )
            criteria_hash = prompt_data.get("criteria_hash")
        except Exception as exc:
            # Non-fatal: proceed without hash; enqueue_resumes treats None as "no hash available"
            criteria_hash = None
            print(f"[WARN] Could not compute criteria hash for request_id {request_id}: {exc}")

        try:
            # Enqueue resumes for background processing
            enqueue_resumes(
                batch_id=batch_id,
                request_id=request_id,
                auth_token=auth_token,
                company_id=company_id,
                business_entity_id=business_entity_id,
                resumes=resumes,
                criteria_hash=criteria_hash,
            )

            return (
                jsonify(
                    {
                        "message": "Resumes enqueued for bulk processing",
                        "batch_id": batch_id,
                        "count": len(resumes),
                        "criteria_hash": criteria_hash,
                    }
                ),
                202,
            )
        except Exception as exc:
            return jsonify({"error": f"Failed to enqueue resumes: {exc}"}), 500

    @app.post("/api/analyze-resume-bulk-urls")
    def analyze_resume_bulk_urls():
        """
        Accepts a JSON array of resumes with URLs instead of Base64:
        [
          { "id": <int/str>, "request_id": <int>, "url": "<url to pdf>" },
          ...
        ]
        """
        import requests
        import base64

        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400

        payload = request.get_json(silent=True)
        if not isinstance(payload, list):
            return (
                jsonify({"error": "Payload must be a JSON array of resume objects"}),
                400,
            )

        if not payload:
            return jsonify({"error": "Resume list is empty"}), 400

        resumes = []
        for item in payload:
            url = item.get("url")
            req_id = item.get("request_id")
            item_id = item.get("id")

            if not url or not req_id or item_id is None:
                return (
                    jsonify(
                        {
                            "error": "Each object must contain 'id', 'request_id', and 'url'"
                        }
                    ),
                    400,
                )

            try:
                # Fetch PDF from URL
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()

                pdf_bytes = resp.content
                base64_file = base64.b64encode(pdf_bytes).decode("utf-8")

                resumes.append(
                    {"id": item_id, "request_id": req_id, "base64_file": base64_file}
                )
            except Exception as exc:
                return (
                    jsonify(
                        {
                            "error": f"Failed to download or encode file from {url}: {exc}"
                        }
                    ),
                    400,
                )

        batch_id = str(uuid.uuid4())
        try:
            enqueue_resumes(batch_id, resumes)
            return (
                jsonify(
                    {
                        "message": "Resumes enqueued for bulk processing via URLs",
                        "batch_id": batch_id,
                        "count": len(resumes),
                    }
                ),
                202,
            )
        except Exception as exc:
            return jsonify({"error": f"Failed to enqueue resumes: {exc}"}), 500

    @app.get("/api/analyze-resume-batch/<batch_id>")
    def analyze_resume_batch_status(batch_id):
        """
        Returns the current parsing status and progress for the given batch_id.
        """
        from analyze_resume_bulk import get_batch_status

        try:
            status = get_batch_status(batch_id)
            return jsonify(status), 200
        except Exception as exc:
            return jsonify({"error": f"Failed to get batch status: {exc}"}), 500

    @app.get("/api/analyze-resume-batch/<batch_id>/results")
    def analyze_resume_batch_results(batch_id):
        """
        Returns the actual parsed JSON results for the batch.
        """
        from analyze_resume_bulk import get_batch_results

        try:
            results = get_batch_results(batch_id)
            return jsonify({"batch_id": batch_id, "data": results}), 200
        except Exception as exc:
            return jsonify({"error": f"Failed to get batch results: {exc}"}), 500

    return app
