# requests_page.py
from typing import Iterable, Tuple
from flask import render_template, request, jsonify
import json
import pyodbc

def request_create_page(app, fetch_rows, get_connection):
    """
    Register routes for the Create Request page.
    `fetch_rows(query, params)` and `get_connection()` are provided by the caller.
    """

    def insert_and_get_id(insert_query: str, params: Iterable = ()) -> Tuple[dict, int]:
        try:
            # Normalize query (remove leading/trailing whitespace)
            q = insert_query.strip()

            # If OUTPUT isn't already present, inject it
            if "OUTPUT" not in q.upper():
                # Find the end of the first line (INSERT INTO ...)
                parts = q.split("VALUES", 1)
                if len(parts) != 2:
                    return {"error": "Invalid INSERT query format for OUTPUT injection"}, 500

                insert_part, values_part = parts

                # Rebuild query with OUTPUT INSERTED.ID
                q = f"{insert_part} OUTPUT INSERTED.ID VALUES{values_part}"

            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(q, params)

                row = cursor.fetchone()
                new_id = row[0] if row else None

                return {"NewID": new_id}, 200

        except Exception as exc:
            return {"error": str(exc)}, 500

    @app.get("/pages/create-request")
    def request_page():
        query = """
            SELECT DISTINCT TOP 20 ID, En_Name
            FROM dbo.Core_Job_Title;
        """
        data, status = fetch_rows(query, ())

        if status != 200:
            return "Job Titles Fetch Error", 500

        # Pass rows to template; template builds the <option> list
        return render_template("create_request.html", job_titles=data)


    @app.post("/api/submit-request")
    def submit_job_title():
        """
        Inserts base Rec_Request and links job title (same as before).
        Does NOT modify your SQL logic — returns request_id and echoes payload so you can use them.
        """

        data = request.get_json(silent=True)
        if not data:
            return {"error": "Invalid or missing JSON payload"}, 400

        # expected fields from your JS
        job_title_id_raw  = data.get("jobTitleId")
        needed_by = data.get("neededBy")
        json_conditions = data.get("jsonConditions")
        sql_where = data.get("sqlWhere")

        # basic validation
        if not job_title_id_raw :
            return {"error": "jobTitleId is required"}, 400
        if not needed_by:
            return {"error": "neededBy is required"}, 400
        if json_conditions is None:
            return {"error": "jsonConditions is required"}, 400
        if sql_where is None:
            return {"error": "sqlWhere is required"}, 400

        # Coerce/validate job_title_id to int
        try:
            job_title_id = int(job_title_id_raw)
        except (TypeError, ValueError):
            return {"error": f"Invalid jobTitleId (must be integer-like). Got: {job_title_id_raw!r}"}, 400

        # Serialize json_conditions to a JSON string before passing to DB
        try:
            json_conditions_str = json.dumps(json_conditions, ensure_ascii=False)
        except Exception as exc:
            return {"error": f"Failed to serialize jsonConditions: {str(exc)}"}, 400

        # Insert the base Rec_Request row and get its ID
        insert_req_query = """
            INSERT INTO dbo.Rec_Request (Request_Status_ID, EmployementType_ID, Request_Reason_ID, Is_Delete, IsFromJobProfile, From_Date, To_Date, SearchCriteria, SearchCriteriaJson)
            VALUES (1, 3, 2, 0, 0, GETDATE(), ?, ?, ?);
        """
        result, status = insert_and_get_id(insert_req_query, (needed_by, sql_where, json_conditions_str))
        if status != 200:
            return result, status

        request_id = result.get("NewID")
        if request_id is None:
            return {"error": "Failed to obtain created request ID"}, 500

        # Link the job title to the created request
        try:
            insert_link_query = """
                INSERT INTO dbo.I_Core_Job_Title_Rec_Requests (Job_Title_ID, Request_ID, Create_Date, Last_Update_Date)
                VALUES (?, ?, GETDATE(), GETDATE());
            """
            
            result2, status2 = insert_and_get_id(insert_link_query, (job_title_id, request_id))
            if status2 != 200:
                return result2, status2

            response_payload = {
                "request_id": request_id,
                "link_insert_result": result2,
                "jsonConditions_received": json_conditions,
                "sqlWhere_received": sql_where,
                "neededBy": needed_by
            }

            return jsonify(response_payload), 200

        except Exception as exc:
            return {"error": str(exc)}, 500

    # add inside request_create_page(app, fetch_rows, get_connection) next to your other routes
    @app.get("/api/get-tables")
    def get_tables():
        """
        Returns JSON with two arrays:
        - requests: rows from dbo.Rec_Request
        - jobTitleRequests: rows from dbo.I_Core_Job_Title_Rec_Requests
        Uses the provided fetch_rows(query, params) helper.
        """
        # Query 1: Rec_Request
        q1 = """
            SELECT ID, From_Date, To_Date, SearchCriteria, SearchCriteriaJson
            FROM dbo.Rec_Request;
        """
        data1, status1 = fetch_rows(q1, ())
        if status1 != 200:
            return jsonify({"error": "Failed to fetch Rec_Request", "detail": data1}), 500

        # Query 2: I_Core_Job_Title_Rec_Requests
        q2 = """
            SELECT Job_Title_ID, Request_ID
            FROM dbo.I_Core_Job_Title_Rec_Requests;
        """
        data2, status2 = fetch_rows(q2, ())
        if status2 != 200:
            return jsonify({"error": "Failed to fetch I_Core_Job_Title_Rec_Requests", "detail": data2}), 500

        # Return both sets as JSON
        return jsonify({
            "requests": data1,
            "jobTitleRequests": data2
        }), 200
