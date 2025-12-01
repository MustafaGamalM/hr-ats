# analyze_resume_page.py
from typing import Iterable, Tuple
from flask import render_template, request, jsonify
import json
import pyodbc
from analyze_resume import send_prompt_and_pdf_to_gemini

def analyze_resume_page(app, fetch_rows):
    """
    Register routes for analyzing/rescoring resumes.

    Routes:
      - GET  /pages/analyze-resume   -> simple upload page (optional template)
      - POST /api/analyze-resume     -> accepts multipart file + request_id OR JSON with base64_file + request_id
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
            return """
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
            """, 200

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
            request_id_raw = request.form.get("request_id") or request.values.get("request_id")
            upload = request.files.get("file")
            if upload:
                try:
                    pdf_bytes = upload.read()
                    import base64
                    base64_file = base64.b64encode(pdf_bytes).decode("utf-8")
                except Exception as exc:
                    return jsonify({"error": f"Failed to read/encode uploaded file: {exc}"}), 400

        # Validate request_id
        if request_id_raw is None:
            return jsonify({"error": "Missing request_id"}), 400

        try:
            request_id = int(request_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid request_id (must be integer). Got: {request_id_raw!r}"}), 400

        if not base64_file:
            return jsonify({"error": "Missing file content. Provide multipart 'file' or JSON 'base64_file'."}), 400

        # Call analyze_resume.send_prompt_and_pdf_to_gemini
        try:
            res = send_prompt_and_pdf_to_gemini(
                request_id=request_id,
                base64_file=base64_file,
                fetch_rows=fetch_rows,
                return_raw_response=False,
                raise_on_error=False
            )

            # If underlying function returned error structure, forward it
            if isinstance(res, dict) and "error" in res:
                return jsonify({"error": res["error"]}), 500

            # Expected shape: {"result": {...}, "percent": N}
            return jsonify(res), 200

        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return app
