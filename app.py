import os
from typing import Iterable, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, request
import pyodbc
from waitress import serve

from candidate_request import candidate_request_page
from create_request import request_create_page
from page_view import CVScreen
from score_results import score_results_page

from analyze_resume_api import analyze_resume_page
from scrap_api import register_scrap_api

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=ENV_PATH)

app = Flask(__name__)


def get_connection() -> pyodbc.Connection:
    """Create a new SQL Server connection using .env settings."""
    driver = os.getenv("SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    server = os.getenv("SQL_SERVER")
    database = os.getenv("SQL_DATABASE")
    user = os.getenv("SQL_USER")
    password = os.getenv("SQL_PWD")

    if not all([server, database, user, password]):
        raise RuntimeError("One or more SQL_* environment variables are missing.")

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def fetch_rows(query: str, params: Iterable = ()) -> Tuple[list, int]:
    """Execute a query and return rows as dicts plus a status code."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return rows, 200
    except Exception as exc:  # pragma: no cover - surfaced in response
        return {"error": str(exc)}, 500


@app.get("/api/categories")
def get_categories():
    query = """
        SELECT
            C.ID,
            C.En_Name,
            C.Ar_Name,
            ISNULL(SUM(CJCP.Score), 0) AS Score
        FROM Core_CVPointsCategories AS C
        LEFT JOIN Core_CVPointsSubCategory AS SC
            ON SC.CAT_ID = C.ID
            AND ISNULL(SC.Is_Delete, 0) = 0
        LEFT JOIN Core_CVPointsCriteria AS CR
            ON CR.SubCat_ID = SC.ID
            AND ISNULL(CR.Is_Delete, 0) = 0
        LEFT JOIN Core_JobTitle_CVPoints AS CJCP
            ON CJCP.Critiria_ID = CR.ID
            AND ISNULL(CJCP.Is_Delete, 0) = 0
        WHERE ISNULL(C.Is_Delete, 0) = 0
        GROUP BY C.ID, C.En_Name, C.Ar_Name
        ORDER BY C.En_Name
    """
    data, status = fetch_rows(query)
    return jsonify(data), status


@app.get("/api/subcategories")
def get_subcategories():
    query = """
        SELECT
            SC.ID,
            SC.En_Name,
            SC.Ar_Name,
            SC.CAT_ID,
            ISNULL(SUM(CJCP.Score), 0) AS Score
        FROM Core_CVPointsSubCategory AS SC
        LEFT JOIN Core_CVPointsCriteria AS CR
            ON CR.SubCat_ID = SC.ID
            AND ISNULL(CR.Is_Delete, 0) = 0
        LEFT JOIN Core_JobTitle_CVPoints AS CJCP
            ON CJCP.Critiria_ID = CR.ID
            AND ISNULL(CJCP.Is_Delete, 0) = 0
        WHERE ISNULL(SC.Is_Delete, 0) = 0
    """
    category_id = request.args.get("categoryId", type=int)
    params = []
    if category_id:
        query += " AND SC.CAT_ID = ?"
        params.append(category_id)

    query += """
        GROUP BY SC.ID, SC.En_Name, SC.Ar_Name, SC.CAT_ID
        ORDER BY SC.En_Name
    """
    data, status = fetch_rows(query, params)
    return jsonify(data), status


@app.get("/api/criteria")
def get_criteria():
    query = """
        SELECT
            CR.ID,
            CR.En_Name,
            CR.Ar_Name,
            CR.SubCat_ID,
            ISNULL(SUM(CJCP.Score), 0) AS Score
        FROM Core_CVPointsCriteria AS CR
        LEFT JOIN Core_JobTitle_CVPoints AS CJCP
            ON CJCP.Critiria_ID = CR.ID
            AND ISNULL(CJCP.Is_Delete, 0) = 0
        WHERE ISNULL(CR.Is_Delete, 0) = 0
    """
    subcategory_id = request.args.get("subcategoryId", type=int)
    params = []
    if subcategory_id:
        query += " AND CR.SubCat_ID = ?"
        params.append(subcategory_id)

    query += """
        GROUP BY CR.ID, CR.En_Name, CR.Ar_Name, CR.SubCat_ID
        ORDER BY CR.En_Name
    """
    data, status = fetch_rows(query, params)
    return jsonify(data), status


@app.get("/api/job-titles")
def get_job_titles():
    query = """
        SELECT JT.ID, JT.En_Name, JT.Ar_Name, ISNULL(SUM(CJCP.Score), 0) AS Score
        FROM Core_Job_Title AS JT
        LEFT JOIN Core_JobTitle_CVPoints AS CJCP
            ON CJCP.Job_Title_ID = JT.ID
            AND ISNULL(CJCP.Is_Delete, 0) = 0
    """
    criteria_id = request.args.get("criteriaId", type=int)
    params = []
    if criteria_id:
        query += " AND CJCP.Critiria_ID = ?"
        params.append(criteria_id)

    query += """
        GROUP BY JT.ID, JT.En_Name, JT.Ar_Name
        ORDER BY JT.En_Name
    """
    data, status = fetch_rows(query, params)
    return jsonify(data), status


@app.post("/api/job-title-criteria")
def add_job_title_criteria():
    """Insert a new mapping of job title -> criteria with a score."""
    payload = request.get_json(silent=True) or {}
    job_title_id = payload.get("jobTitleId")
    criteria_id = payload.get("criteriaId")
    full_score = payload.get("fullScore")
    user_id = payload.get("userId", 1)

    if job_title_id is None or criteria_id is None or full_score is None:
        return jsonify({"error": "jobTitleId, criteriaId and fullScore are required"}), 400

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO Core_JobTitle_CVPoints (
                    Job_Title_ID,
                    Critiria_ID,
                    Score,
                    Is_Delete,
                    Creat_User_ID,
                    Create_Date,
                    Last_Update_User_ID,
                    Last_Update_Date
                )
                VALUES (?, ?, ?, 0, ?, GETDATE(), ?, GETDATE());
                """,
                (job_title_id, criteria_id, full_score, user_id, user_id),
            )
            cursor.execute("SELECT SCOPE_IDENTITY() AS InsertedId;")
            new_id = cursor.fetchone()[0]
            conn.commit()
        return jsonify({"id": int(new_id) if new_id is not None else None}), 201
    except Exception as exc:  # pragma: no cover - bubbled to API
        return jsonify({"error": str(exc)}), 500


@app.get("/")
def index():
    return CVScreen.render()


request_create_page(app, fetch_rows, get_connection)
analyze_resume_page(app, fetch_rows)
candidate_request_page(app, fetch_rows)
score_results_page(app, fetch_rows)
register_scrap_api(app)

if __name__ == "__main__":
    import threading
    from analyze_resume_bulk import background_worker
    
    # Start the background worker in a daemon thread so it runs alongside your API
    # Daemon threads automatically shut down when the main process (Waitress/Flask) stops.
    worker_thread = threading.Thread(target=background_worker, daemon=True)
    worker_thread.start()
    
    port = int(os.getenv("PORT", "5000"))
    serve(app, host="0.0.0.0", port=port)
