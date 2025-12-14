# analyze_resume.py
import json
import re
import base64
import os
import requests
import pdfplumber
import io
from typing import Dict, Any

# -----------------------
# CONFIG
# -----------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"  # change if needed

QUERY = """
SELECT 
      jtp.JobTitle_Id,
      jtp.PointsCriteriaId,
      jtp.FullScore,
      pcr.En_Name AS CriteriaName,
      pcr.SubCategoryId,
      psc.En_Name AS SubCategoryName,
      psc.CategoryId,
      pca.En_Name AS CategoryName
FROM dbo.Core_JobTitle_CVPoints AS jtp
JOIN dbo.I_Core_Job_Title_Rec_Requests AS rec
      ON jtp.JobTitle_Id = rec.Job_Title_ID
JOIN dbo.Core_CVPointsCriteria AS pcr
      ON jtp.PointsCriteriaId = pcr.ID
JOIN dbo.Core_CVPointsSubCategory AS psc
      ON pcr.SubCategoryId = psc.ID
JOIN dbo.Core_CVPointsCategories AS pca
      ON psc.CategoryId = pca.ID
WHERE rec.Request_ID = ?
"""

STATIC_SUBCATEGORIES = [
    "Years of Experience",
    "Job Title Match",
    "Industry Match",
    "Job Level",
    "Degree Level",
    "Field of Study",
    "Certifications",
    "Technical Skills",
    "Soft Skills",
    "Keywords Match"
]

# -----------------------
# UTILITIES
# -----------------------
def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    text = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text)
    return "\n".join(text)

def _safe_extract_json(text: str) -> Any:
    cleaned = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()

    decoder = json.JSONDecoder()
    for i, ch in enumerate(cleaned):
        if ch in ("{", "["):
            try:
                return decoder.raw_decode(cleaned[i:])[0]
            except json.JSONDecodeError:
                continue

    raise ValueError("No valid JSON found in Ollama response.")

# -----------------------
# PROMPT BUILDING
# -----------------------
def build_gemini_prompt(request_id: int, fetch_rows) -> Dict[str, Any]:
    rows, status = fetch_rows(QUERY, (request_id,))
    if status != 200:
        return {"error": "DB error", "rows": []}

    subcats = {}
    for r in rows:
        subcats.setdefault(r["SubCategoryName"], []).append(r)

    lines = []
    for sc, items in subcats.items():
        lines.append(f"SubCategory: {sc}")
        for i in items:
            lines.append(
                f"- CriteriaId: {i['PointsCriteriaId']}, "
                f"Name: {i['CriteriaName']}, "
                f"Score: {i['FullScore']}"
            )
        lines.append("")

    system = (
        "You are an expert resume-to-criteria matcher.\n"
        "Return ONLY a single JSON object mapping SubCategoryName -> integer score.\n"
        "Rules:\n"
        "1. Keys must match subcategory names exactly\n"
        "2. Values must be integers\n"
        "3. Use FullScore\n"
        "4. Use 0 if no match\n"
        "5. No explanations\n"
    )

    user = (
        "Use the resume below.\n\n"
        "CRITERIA:\n"
        f"{chr(10).join(lines)}\n"
        "OUTPUT JSON ONLY."
    )

    return {"system": system, "user": user, "rows": rows}

# -----------------------
# OLLAMA CALL
# -----------------------
def call_ollama(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["response"]

# -----------------------
# MAIN ENTRY (REPLACEMENT)
# -----------------------
def send_prompt_and_pdf_to_gemini(
    request_id: int,
    base64_file: str,
    fetch_rows,
    return_raw_response: bool = False,
    raise_on_error: bool = False
):
    try:
        prompts = build_gemini_prompt(request_id, fetch_rows)
        rows = prompts.get("rows", [])

        b64 = base64_file.split("base64,", 1)[-1]
        pdf_bytes = base64.b64decode(b64)
        resume_text = extract_text_from_pdf(pdf_bytes)

        full_prompt = (
            prompts["system"] + "\n\n" +
            prompts["user"] + "\n\n" +
            "RESUME:\n" + resume_text
        )

        response_text = call_ollama(full_prompt)
        parsed = _safe_extract_json(response_text)

        percent = calculate_total_percent_from_rows(parsed, rows)
        normalized = enforce_static_subcategories(parsed)

        out = {
            "result": normalized,
            "percent": percent
        }

        if return_raw_response:
            out["raw"] = response_text

        return out

    except Exception as e:
        if raise_on_error:
            raise
        return {"error": str(e)}

# -----------------------
# SCORING (UNCHANGED)
# -----------------------
def enforce_static_subcategories(parsed_result: dict) -> list:
    result = []
    for idx, name in enumerate(STATIC_SUBCATEGORIES, 1):
        val = parsed_result.get(name)
        try:
            val = int(val)
        except:
            #val = None
            continue

        result.append({
            "subCategoryID": idx,
            "subCategoryName": name,
            "subCategoryScore": val
        })
    return result

def calculate_total_percent_from_rows(gemini_scores: dict, rows: list) -> int:
    if not gemini_scores:
        return 0

    max_scores = {}
    for r in rows:
        sc = r["SubCategoryName"]
        max_scores[sc] = max(max_scores.get(sc, 0), float(r["FullScore"]))

    assigned = sum(float(v) for k, v in gemini_scores.items() if k in max_scores)
    total = sum(max_scores.values())

    if total == 0:
        return 0

    return max(0, min(100, round((assigned / total) * 100)))
