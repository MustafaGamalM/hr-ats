from flask import jsonify, render_template, request


def score_results_page(app, fetch_rows):
    """
    Register an endpoint to list candidate scores with optional sorting.

    Query params:
      - order: "asc" | "desc" (defaults to "desc")
    Joins Core_CvScore with Core_CandidateJobRequests and Core_CvCandidate
    to return candidate name + summed score per candidate request.
    """

    @app.get("/pages/score-results")
    @app.get("/score-results")
    def score_results_page_view():
        return render_template("score_results.html")

    @app.get("/api/score-results")
    def get_score_results():
        # Normalize order while preventing SQL injection by restricting to allowed tokens.
        order_param = (request.args.get("order") or "desc").strip().lower()
        order_sql = "ASC" if order_param == "asc" else "DESC"

        query = f"""
            SELECT
                cand.Id AS CandidateId,
                cand.CandidateName,
                cjr.id AS CandidateRequestId,
                cjr.jobRequestId AS JobRequestId,
                SUM(score.score) AS TotalScore
            FROM dbo.Core_CvScore AS score
            INNER JOIN dbo.Core_CandidateJobRequests AS cjr
                ON cjr.id = score.candidateRequestId
            LEFT JOIN dbo.Core_CvCandidate AS cand
                ON cand.Id = cjr.candidateId
            GROUP BY cand.Id, cand.CandidateName, cjr.id, cjr.jobRequestId
            ORDER BY TotalScore {order_sql}, cand.CandidateName ASC;
        """

        data, status = fetch_rows(query, ())
        return jsonify(data), status

    @app.get("/api/score-results/<int:candidate_request_id>")
    def get_score_breakdown(candidate_request_id: int):
        """
        Return subcategory-level scores for a given candidate request.
        """
        query = """
            SELECT
                score.SubCat_ID AS SubCat_ID,
                sc.En_Name AS SubCategoryName,
                score.score AS Score
            FROM dbo.Core_CvScore AS score
            LEFT JOIN dbo.Core_CVPointsSubCategory AS sc
                ON sc.ID = score.SubCat_ID
            WHERE score.candidateRequestId = ?
            ORDER BY sc.En_Name ASC, score.SubCat_ID ASC;
        """
        data, status = fetch_rows(query, (candidate_request_id,))
        return jsonify(data), status

    return app
