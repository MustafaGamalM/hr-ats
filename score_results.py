from flask import jsonify, render_template, request


def score_results_page(app, fetch_rows):
    """
    Register an endpoint to list candidate scores with optional sorting.

    Query params:
      - order: "asc" | "desc" (defaults to "desc")
    Joins Core_CvScore with Core_CvCandidate to return candidate name + total score.
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
                cand.ID AS CandidateId,
                cand.CandidateName,
                ISNULL(score.TotalScore, 0) AS TotalScore
            FROM dbo.Core_CvScore AS score
            INNER JOIN dbo.Core_CvCandidate AS cand
                ON cand.ID = score.CandidateId
            ORDER BY score.TotalScore {order_sql}, cand.CandidateName ASC;
        """

        data, status = fetch_rows(query, ())
        return jsonify(data), status

    return app
