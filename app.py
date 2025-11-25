import os
from typing import Iterable, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request
import pyodbc

from create_request import request_create_page

load_dotenv()

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
        SELECT ID, En_Name, Ar_Name
        FROM Core_CVPointsCategories
        WHERE ISNULL(Is_Delete, 0) = 0
        ORDER BY En_Name
    """
    data, status = fetch_rows(query)
    return jsonify(data), status


@app.get("/api/subcategories")
def get_subcategories():
    category_id = request.args.get("categoryId", type=int)
    if not category_id:
        return jsonify({"error": "categoryId is required and must be an integer."}), 400

    query = """
        SELECT ID, En_Name, Ar_Name, CategoryId
        FROM Core_CVPointsSubCategory
        WHERE CategoryId = ? AND ISNULL(Is_Delete, 0) = 0
        ORDER BY En_Name
    """
    data, status = fetch_rows(query, (category_id,))
    return jsonify(data), status


@app.get("/api/criteria")
def get_criteria():
    subcategory_id = request.args.get("subcategoryId", type=int)
    if not subcategory_id:
        return jsonify({"error": "subcategoryId is required and must be an integer."}), 400

    query = """
        SELECT ID, En_Name, Ar_Name, SubCategoryId
        FROM Core_CVPointsCriteria
        WHERE SubCategoryId = ? AND ISNULL(Is_Delete, 0) = 0
        ORDER BY En_Name
    """
    data, status = fetch_rows(query, (subcategory_id,))
    return jsonify(data), status


@app.get("/api/job-titles")
def get_job_titles():
    criteria_id = request.args.get("criteriaId", type=int)
    if not criteria_id:
        return jsonify({"error": "criteriaId is required and must be an integer."}), 400

    query = """
        SELECT DISTINCT JT.ID, JT.En_Name, JT.Ar_Name
        FROM Core_JobTitle_CVPoints AS JTCP
        INNER JOIN Core_Job_Title AS JT ON JT.ID = JTCP.JobTitle_Id
        WHERE JTCP.PointsCriteriaId = ?
        ORDER BY JT.En_Name
    """
    data, status = fetch_rows(query, (criteria_id,))
    return jsonify(data), status


@app.get("/")
def index():
    page = """
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>CV Points Selector</title>
        <style>
            :root {
                --bg: #0b1723;
                --panel: #102030;
                --accent: #4cc3ff;
                --muted: #8ca0b3;
                --text: #e8f0f8;
            }
            * { box-sizing: border-box; }
            body {
                margin: 0;
                min-height: 100vh;
                font-family: "Segoe UI", "Helvetica Neue", sans-serif;
                background: radial-gradient(circle at 20% 20%, #0f2740, var(--bg));
                color: var(--text);
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 24px;
            }
            .shell {
                width: min(960px, 100%);
                background: linear-gradient(135deg, var(--panel), #0f1c2b);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 16px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.35);
                padding: 28px;
            }
            h1 {
                margin: 0 0 18px;
                font-weight: 700;
                letter-spacing: 0.02em;
            }
            .grid {
                display: grid;
                gap: 14px;
            }
            label {
                display: block;
                font-size: 14px;
                color: var(--muted);
                margin-bottom: 6px;
            }
            select {
                width: 100%;
                padding: 12px 14px;
                border-radius: 10px;
                border: 1px solid rgba(255,255,255,0.08);
                background: #0c1a28;
                color: var(--text);
                font-size: 15px;
                transition: border 120ms ease, box-shadow 120ms ease;
            }
            select:focus {
                outline: none;
                border-color: var(--accent);
                box-shadow: 0 0 0 3px rgba(76,195,255,0.18);
            }
            .row {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 14px;
            }
            .status {
                margin-top: 10px;
                font-size: 13px;
                color: var(--muted);
            }
        </style>
    </head>
    <body>
        <div class="shell">
            <h1>Job Matching: Cascading Filters</h1>
            <div class="grid">
                <div>
                    <label for="category">Category</label>
                    <select id="category"></select>
                </div>
                <div>
                    <label for="subcategory">SubCategory</label>
                    <select id="subcategory" disabled></select>
                </div>
                <div>
                    <label for="criteria">Criteria</label>
                    <select id="criteria" disabled></select>
                </div>
                <div>
                    <label for="jobTitle">Job Title</label>
                    <select id="jobTitle" disabled></select>
                </div>
            </div>
            <div class="status" id="status"></div>
        </div>

        <script>
            const categorySel = document.getElementById('category');
            const subcategorySel = document.getElementById('subcategory');
            const criteriaSel = document.getElementById('criteria');
            const jobTitleSel = document.getElementById('jobTitle');
            const status = document.getElementById('status');

            const setStatus = (msg) => { status.textContent = msg || ''; };

            const resetSelect = (selectEl, placeholder) => {
                selectEl.innerHTML = '';
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = placeholder;
                selectEl.appendChild(opt);
            };

            async function loadCategories() {
                setStatus('Loading categories...');
                resetSelect(categorySel, 'Select category');
                [subcategorySel, criteriaSel, jobTitleSel].forEach(sel => { resetSelect(sel, '---'); sel.disabled = true; });
                const res = await fetch('/api/categories');
                const data = await res.json();
                data.forEach(row => {
                    const opt = document.createElement('option');
                    opt.value = row.ID;
                    opt.textContent = row.En_Name || row.Ar_Name || `Category ${row.ID}`;
                    categorySel.appendChild(opt);
                });
                setStatus('');
            }

            async function loadSubcategories(categoryId) {
                resetSelect(subcategorySel, 'Select subcategory');
                resetSelect(criteriaSel, '---');
                resetSelect(jobTitleSel, '---');
                criteriaSel.disabled = true;
                jobTitleSel.disabled = true;

                if (!categoryId) {
                    subcategorySel.disabled = true;
                    return;
                }
                subcategorySel.disabled = false;
                setStatus('Loading subcategories...');
                const res = await fetch(`/api/subcategories?categoryId=${categoryId}`);
                const data = await res.json();
                data.forEach(row => {
                    const opt = document.createElement('option');
                    opt.value = row.ID;
                    opt.textContent = row.En_Name || row.Ar_Name || `SubCategory ${row.ID}`;
                    subcategorySel.appendChild(opt);
                });
                setStatus('');
            }

            async function loadCriteria(subcategoryId) {
                resetSelect(criteriaSel, 'Select criteria');
                resetSelect(jobTitleSel, '---');
                jobTitleSel.disabled = true;
                if (!subcategoryId) {
                    criteriaSel.disabled = true;
                    return;
                }
                criteriaSel.disabled = false;
                setStatus('Loading criteria...');
                const res = await fetch(`/api/criteria?subcategoryId=${subcategoryId}`);
                const data = await res.json();
                data.forEach(row => {
                    const opt = document.createElement('option');
                    opt.value = row.ID;
                    opt.textContent = row.En_Name || row.Ar_Name || `Criteria ${row.ID}`;
                    criteriaSel.appendChild(opt);
                });
                setStatus('');
            }

            async function loadJobTitles(criteriaId) {
                resetSelect(jobTitleSel, 'Select job title');
                if (!criteriaId) {
                    jobTitleSel.disabled = true;
                    return;
                }
                jobTitleSel.disabled = false;
                setStatus('Loading job titles...');
                const res = await fetch(`/api/job-titles?criteriaId=${criteriaId}`);
                const data = await res.json();
                data.forEach(row => {
                    const opt = document.createElement('option');
                    opt.value = row.ID;
                    opt.textContent = row.En_Name || row.Ar_Name || `Job ${row.ID}`;
                    jobTitleSel.appendChild(opt);
                });
                setStatus('');
            }

            categorySel.addEventListener('change', (e) => loadSubcategories(e.target.value));
            subcategorySel.addEventListener('change', (e) => loadCriteria(e.target.value));
            criteriaSel.addEventListener('change', (e) => loadJobTitles(e.target.value));

            loadCategories().catch(err => {
                console.error(err);
                setStatus('Failed to load categories. Check server logs.');
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(page)

request_create_page(app, fetch_rows, get_connection)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
