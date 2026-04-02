import json
import re
import base64
import os
from typing import Dict, Any
from google import genai
from google.genai import types
from dotenv import load_dotenv
from asyncio.windows_events import NULL

# -----------------------
# Initialization
# -----------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

def _safe_extract_json(text: str) -> Any:
    """
    Extract and parse the first JSON object or array found in `text`.
    - Removes ```json and ``` fences.
    - Uses json.JSONDecoder.raw_decode to locate the first valid JSON object/array.
    - Returns the parsed JSON (dict or list).
    - Raises ValueError with helpful info on failure.
    """
    if not isinstance(text, str):
        raise ValueError("Expected a string from Gemini part.text, got: " + repr(type(text)))

    # Remove common fenced-code markers (```json ... ``` or ``` ... ```)
    cleaned = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE).strip()
    cleaned = cleaned.replace("```", "").strip()

    # Find first position of '{' or '['
    idx_candidates = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if not idx_candidates:
        raise ValueError("No JSON-like characters ('{' or '[') found in part text. Preview:\n" + cleaned[:1000])

    decoder = json.JSONDecoder()
    # Try starting from each candidate index (sorted, earliest first)
    for start in sorted(idx_candidates):
        try:
            obj, end = decoder.raw_decode(cleaned[start:])
            return obj
        except json.JSONDecodeError:
            continue

    # Fallback: scan through the string and attempt raw_decode at any '{' or '['
    for i, ch in enumerate(cleaned):
        if ch not in ("{", "["):
            continue
        try:
            obj, end = decoder.raw_decode(cleaned[i:])
            return obj
        except json.JSONDecodeError:
            continue

    # If we get here, nothing parsed
    preview = cleaned[:1000] + ("..." if len(cleaned) > 1000 else "")
    raise ValueError("Failed to parse JSON from Gemini part text. Preview:\n" + preview)

def build_gemini_prompt(request_id: int, fetch_rows) -> Dict[str, Any]:
    rows, status = fetch_rows(QUERY, (request_id,))
    if status != 200:
        # Return minimal structure even on error
        return {
            "system": "Error fetching criteria rows.",
            "user": f"Database error: {rows.get('error', 'unknown')}"
        }

    subcats = {}
    for r in rows:
        sc_name = r["SubCategoryName"]
        crit = {
            "PointsCriteriaId": r["PointsCriteriaId"],
            "CriteriaName": r["CriteriaName"],
            "FullScore": r["FullScore"],
            "CategoryId": r["CategoryId"],
            "CategoryName": r["CategoryName"]
        }
        subcats.setdefault(sc_name, []).append(crit)

    criteria_listing_lines = []
    for sc_name, crits in subcats.items():
        criteria_listing_lines.append(f"SubCategory: {sc_name}")
        for c in crits:
            criteria_listing_lines.append(
                f"  - CriteriaId: {c['PointsCriteriaId']}, Name: {c['CriteriaName']}, Score: {c['FullScore']}"
            )
        criteria_listing_lines.append("")

    criteria_listing_text = "\n".join(criteria_listing_lines)

    system_prompt = (
        "You are an expert resume-to-criteria matcher. "
        "Your job is to read a candidate resume (which will be supplied) "
        "and for each SUBCATEGORY supplied in the 'user' message, select the single most appropriate "
        "CRITERIA from the list for that subcategory that best matches the resume. "
        "Then return a single JSON object that maps SubCategoryName -> NumericScore.\n\n"

        "RESPONSE RULES:\n"
        "1) Reply with a single JSON object only.\n"
        "2) Keys = exact SubCategory names.\n"
        "3) Values = integers (FullScore).\n"
        "4) If nothing matches, return 0.\n"
        "5) Do NOT include CriteriaId or CriteriaName in the output."
    )

    user_prompt = (
        "Use the resume to choose the best matching criteria for each SUBCATEGORY listed below.\n"
        "Return ONLY the JSON mapping SubCategoryName -> FullScore.\n\n"

        "--- SubCategories and their Criteria ---\n\n"
        f"{criteria_listing_text}\n"
        "--- end of list ---\n\n"

        "Example output:\n"
        '{ "Years of Experience": 20, "Technical Skills": 30 }\n'
    )

    # Build a strict JSON schema dynamically mapped directly to the active subcategories
    response_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            sc_name: types.Schema(type=types.Type.NUMBER) for sc_name in subcats.keys()
        },
        required=list(subcats.keys())
    )

    return {
        "system": system_prompt,
        "user": user_prompt,
        "schema": response_schema,
        "rows": rows 
    }

def _parse_gemini_response_for_json(response):
    """
    Extract the first JSON object/array found in the response using the same
    logic from analyze_resume (candidates -> content -> parts -> text).
    Returns the parsed JSON (dict/list) or raises ValueError.
    """
    # Adapted from analyze_resume's parsing logic
    # Obtain candidates from either attribute access or dict-style access
    candidates = None
    if hasattr(response, "candidates"):
        candidates = getattr(response, "candidates")
    elif isinstance(response, dict):
        candidates = response.get("candidates")
    else:
        raise ValueError(f"Expected Gemini response with 'candidates'. Got: {type(response)}")

    if not candidates:
        raise ValueError("Gemini response contains no 'candidates' or it's empty.")

    last_errors = []

    # Helper to pull attr or key
    def _get(obj, key):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    for ci, candidate in enumerate(candidates):
        content = _get(candidate, "content")
        if content is None:
            content = _get(candidate, "message") or _get(candidate, "output") or content
        if content is None:
            last_errors.append(f"candidate[{ci}]: missing content/message")
            continue

        parts = _get(content, "parts")
        if not parts:
            last_errors.append(f"candidate[{ci}]: content has no parts")
            continue

        for pi, part in enumerate(parts):
            # part may be object with .text, dict with 'text', or a string
            text_val = None
            if isinstance(part, str):
                text_val = part
            else:
                text_val = _get(part, "text") or _get(part, "content") or None

            if not isinstance(text_val, str):
                try:
                    text_val = str(part)
                except Exception:
                    text_val = None

            if not text_val:
                last_errors.append(f"candidate[{ci}].part[{pi}]: no textual payload")
                continue

            try:
                parsed = _safe_extract_json(text_val)
                return parsed
            except ValueError as e:
                last_errors.append(f"candidate[{ci}].part[{pi}]: {e}")
                continue

    error_msg = "Failed to extract JSON from Gemini response. Tried all candidates/parts."
    if last_errors:
        error_msg += "\nSample errors:\n" + "\n".join(last_errors[:8])
    raise ValueError(error_msg)

def enforce_static_subcategories(parsed_result: dict) -> list:
    """
    Convert the model response into the final required array structure.
    """
    if not isinstance(parsed_result, dict):
        parsed_result = {}

    result_array = []

    for idx, name in enumerate(STATIC_SUBCATEGORIES, start=1):
        raw_score = parsed_result.get(name)
        if raw_score is None:
            out_score = None
        else:
            try:
                fv = float(raw_score)
                out_score = int(fv) if fv.is_integer() else fv
            except Exception:
                out_score = None

        result_array.append({
            "subCategoryID": idx,
            "subCategoryName": name,
            "subCategoryScore": out_score
        })

    return result_array

def format_dynamic_subcategories(parsed_result: dict, rows: list) -> list:
    """
    Convert the model response into the final required array structure
    using dynamic subcategories directly from the database rows.
    """
    if not isinstance(parsed_result, dict):
        parsed_result = {}

    # Extract unique subcategories and their actual database IDs
    seen_ids = set()
    dynamic_subcategories = []
    
    for r in rows:
        sc_id = r.get("SubCategoryId")
        sc_name = r.get("SubCategoryName")
        
        # Ensure we only add each subcategory once
        if sc_id and sc_name and sc_id not in seen_ids:
            seen_ids.add(sc_id)
            dynamic_subcategories.append((sc_id, sc_name))

    result_array = []

    for sc_id, name in dynamic_subcategories:
        raw_score = parsed_result.get(name)
        
        if raw_score is None:
            out_score = None
        else:
            try:
                fv = float(raw_score)
                out_score = int(fv) if fv.is_integer() else fv
            except Exception:
                out_score = None

        result_array.append({
            "subCategoryID": sc_id,  # Uses the real DB ID now!
            "subCategoryName": name,
            "subCategoryScore": out_score
        })

    return result_array

def send_prompt_and_pdf_to_gemini(
    request_id: int,
    base64_file: str,
    fetch_rows,
    model: str = "gemini-3.1-flash-lite-preview",
    return_raw_response: bool = False,
    raise_on_error: bool = False
):
    """
    Build system+user prompts for the given request_id using build_gemini_prompt(),
    send those prompts plus the provided PDF (base64) to Gemini, and return the parsed JSON.
    """
    GEMINI_CLIENT = NULL

    try:
        prompts = build_gemini_prompt(request_id, fetch_rows)
        rows = prompts.get("rows", [])

        if not rows:
            return {
                "result": [],
                "percent": 0,
                "error": f"No criteria found in the database for request_id {request_id}. Skipping Gemini analysis."
            }

        if not isinstance(prompts, dict) or "system" not in prompts or "user" not in prompts:
            raise ValueError("build_gemini_prompt did not return expected dict with 'system' and 'user' keys.")

        # Normalize/strip data-uri header if present
        if isinstance(base64_file, str) and "base64," in base64_file:
            _, b64 = base64_file.split("base64,", 1)
        else:
            b64 = base64_file

        pdf_bytes = base64.b64decode(b64)

        # Initialize Gemini client if needed
        if GEMINI_CLIENT == NULL:
            GEMINI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)

        # Isolate system instruction from user payload
        system_text = prompts["system"].strip()
        user_text = prompts["user"].strip()
        schema = prompts.get("schema")

        content_parts = [
            genai.types.Part.from_text(text=user_text),
            genai.types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
        ]

        # Send to Gemini with strictly deterministic decoding strategies and JSON schema enforcement
        raw_response = GEMINI_CLIENT.models.generate_content(
            model=model,
            contents=content_parts,
            config=types.GenerateContentConfig(
                temperature=0.0,
                top_p=0.0,
                top_k=1,
                seed=42, 
                system_instruction=system_text,
                response_mime_type="application/json",
                response_schema=schema
            )
        )

        # Parse JSON using existing helper
        parsed = _parse_gemini_response_for_json(raw_response)

        try:
            percent, total_score = calculate_total_percent_from_rows(parsed, rows)
        except Exception:
            percent, total_score = 0, 0

        # Pass the database rows so the function knows what the dynamic categories are
        normalized = format_dynamic_subcategories(parsed, rows)

        out = {
            "result": normalized,
            "percent": percent if isinstance(percent, int) else None,
            "totalScore": total_score
        }

        if return_raw_response:
            out["raw"] = raw_response

        return out

    except Exception as exc:
        if raise_on_error:
            raise
        return {"error": str(exc)}

def calculate_total_percent_from_rows(gemini_scores: dict, rows: list) -> tuple:
    """
    Calculate percent score and total assigned score from Gemini output using previously fetched DB rows.
    No database queries are made here.
    Returns (percent, sum_assigned)
    """

    if not isinstance(gemini_scores, dict) or not gemini_scores:
        return 0, 0

    # Build: SubCategoryName -> max FullScore
    subcat_max = {}
    for r in rows:
        sc = r.get("SubCategoryName")
        try:
            score = float(r.get("FullScore") or 0)
        except:
            score = 0
        if sc:
            subcat_max[sc] = max(subcat_max.get(sc, 0), score)

    if not subcat_max:
        return 0, 0

    # Compute totals
    sum_assigned = 0.0
    sum_max = 0.0

    for sc_name, assigned in gemini_scores.items():
        if sc_name not in subcat_max:
            continue  # ignore unknown subcategories

        try:
            assigned_val = float(assigned)
        except:
            assigned_val = 0

        sum_assigned += assigned_val
        sum_max += subcat_max[sc_name]

    if sum_max <= 0:
        return 0, int(sum_assigned)

    percent = round((sum_assigned / sum_max) * 100)
    return max(0, min(100, percent)), int(sum_assigned)

