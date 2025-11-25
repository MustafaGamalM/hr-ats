from typing import Iterable, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request
import pyodbc


def request_create_page(app, fetch_rows, get_connection):


    def insert_and_get_id(query: str, params: Iterable = ()) -> Tuple[dict, int]:
        """Execute an INSERT query, then return the newly generated ID using SCOPE_IDENTITY()"""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()

                # Execute the INSERT query
                cursor.execute(query, params)

                # Get the newly generated ID using SCOPE_IDENTITY()
                cursor.execute("SELECT MAX(ID) AS NewID FROM dbo.Rec_Request")
                new_id = cursor.fetchone()[0]  # Fetch the first row and get the ID

                # Return the result as a dictionary with the new ID
                return {"NewID": new_id}, 200

        except Exception as exc:
            # Handle any errors and return an error message
            return {"error": str(exc)}, 500


    @app.get("/pages/create-request")
    def request_page():

        query = """
            Select Distinct Top 20 ID, En_Name
            From dbo.Core_Job_Title;
        """
        data, status = fetch_rows(query, ())

        if status != 200:
            return "Job Titles Fetch Error"

        # Create a list of job titles from the data to populate the dropdown
        job_titles_html = ''.join(
            [f'<option value="{job["ID"]}">{job["ID"]}: {job["En_Name"]}</option>' for job in data]
        )

        page = f"""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Create Request</title>
            <style>
                :root {{
                    --bg: #0b1723;
                    --panel: #102030;
                    --accent: #4cc3ff;
                    --muted: #8ca0b3;
                    --text: #e8f0f8;
                }}
                * {{ box-sizing: border-box; }}
                body {{
                    margin: 0;
                    min-height: 100vh;
                    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
                    background: radial-gradient(circle at 20% 20%, #0f2740, var(--bg));
                    color: var(--text);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 24px;
                }}
                .shell {{
                    width: min(960px, 100%);
                    background: linear-gradient(135deg, var(--panel), #0f1c2b);
                    border: 1px solid rgba(255,255,255,0.06);
                    border-radius: 16px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.35);
                    padding: 28px;
                }}
                h1 {{
                    margin: 0 0 18px;
                    font-weight: 700;
                    letter-spacing: 0.02em;
                }}
                label {{
                    display: block;
                    font-size: 14px;
                    color: var(--muted);
                    margin-bottom: 6px;
                }}
                select, button {{
                    width: 100%;
                    padding: 12px 14px;
                    border-radius: 10px;
                    border: 1px solid rgba(255,255,255,0.08);
                    background: #0c1a28;
                    color: var(--text);
                    font-size: 15px;
                    transition: border 120ms ease, box-shadow 120ms ease;
                }}
                select:focus, button:focus {{
                    outline: none;
                    border-color: var(--accent);
                    box-shadow: 0 0 0 3px rgba(76,195,255,0.18);
                }}
                .my-5 {{
                    margin-top: 2rem;
                    margin-bottomL 2rem;
                }}
            </style>
        </head>
        <body>
            <div class="shell">
                <h1>Create Request</h1>
                <div class="my-5">
                    <label for="jobTitle">Select Job Title</label>
                    <select id="jobTitle" style="max-height: 150px; overflow-y: auto;">
                        <option value="">Select a job title</option>
                        {job_titles_html}  <!-- Dropdown filled with job titles -->
                    </select>
                </div>
                <div class="my-5">
                    <button id="submitButton">Submit</button>
                </div>
            </div>

            <script>
                const submitButton = document.getElementById('submitButton');
                const jobTitleSel = document.getElementById('jobTitle');

                submitButton.addEventListener('click', () => {{
                    const selectedJobTitleId = jobTitleSel.value;
                    if (selectedJobTitleId) {{
                        // Call your TODO function with the selected Job Title ID
                        console.log('Selected Job Title ID:', selectedJobTitleId);

                        // You can send this ID to a backend function or handle it in your code
                        fetch('/api/submit-job-title', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                            }},
                            body: JSON.stringify({{
                                jobTitleId: selectedJobTitleId
                            }})
                        }})
                        .then(response => response.json())
                        .then(data => {{
                            console.log('Success:', data);
                            alert('Job title submitted successfully');
                        }})
                        .catch(error => {{
                            console.error('Error:', error);
                            alert('Failed to submit job title');
                        }});
                    }} else {{
                        alert('Please select a job title');
                    }}
                }});
            </script>
        </body>
        </html>
        """

        return render_template_string(page)

    @app.post("/api/submit-job-title")
    def submit_job_title():
        # Get the job title ID from the request
        data = request.get_json()
        job_title_id = data.get('jobTitleId')

        query = """
            INSERT INTO dbo.Rec_Request (Request_Status_ID, EmployementType_ID, Request_Reason_ID, Is_Delete, IsFromJobProfile)
            VALUES (1, 3, 2, 0, 0);
        """

        # Call the function to insert data and retrieve the new ID
        result, status = insert_and_get_id(query)

        if status != 200:
            return result, status

        request_id = result["NewID"]

        try:
            query = """
                INSERT INTO dbo.I_Core_Job_Title_Rec_Requests (Job_Title_ID, Request_ID, Create_Date, Last_Update_Date)
                VALUES (?, ?, GETDATE(), GETDATE());
            """
            params = (job_title_id, request_id)

            # Execute the query and return the result
            result, status = insert_and_get_id(query, params)  # Reusing the insert_and_get_id function to get the ID
            return result, status

        except Exception as exc:
            # Handle any errors that may occur
            return {"error": str(exc)}, 500

    