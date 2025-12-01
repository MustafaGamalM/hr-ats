from flask import render_template_string

UPLOAD_URL = "http://localhost:5678/webhook/upload-cv"


def candidate_request_page(app):
    """Register the candidate CV upload page."""

    @app.get("/pages/candidate-request")
    def candidate_request():
        return render_template_string(
            TEMPLATE,
            upload_url=UPLOAD_URL,
        )


TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Upload Candidate CV</title>
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
            width: min(640px, 100%);
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
        p {
            margin: 0 0 18px;
            color: var(--muted);
        }
        label {
            display: block;
            font-size: 14px;
            color: var(--muted);
            margin-bottom: 6px;
        }
        input[type="text"], input[type="file"] {
            width: 100%;
            padding: 12px 14px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.08);
            background: #0c1a28;
            color: var(--text);
            font-size: 15px;
            transition: border 120ms ease, box-shadow 120ms ease, opacity 120ms ease;
        }
        input:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(76,195,255,0.18);
        }
        button {
            width: 100%;
            padding: 12px 14px;
            border-radius: 10px;
            border: none;
            background: linear-gradient(90deg, var(--accent), #78d7ff);
            color: #081420;
            font-weight: 700;
            font-size: 15px;
            cursor: pointer;
            transition: opacity 120ms ease, transform 120ms ease;
        }
        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        .field {
            margin-bottom: 14px;
        }
        .status {
            margin-top: 12px;
            font-size: 13px;
            color: var(--muted);
        }
    </style>
</head>
<body>
    <div class="shell">
        <h1>Upload Candidate CV</h1>
        <p>Enter the candidate name, pick a CV file, and submit it to the webhook endpoint.</p>
        <form id="cvForm">
            <div class="field">
                <label for="candidateName">Candidate Name</label>
                <input id="candidateName" type="text" name="candidateName" placeholder="Jane Doe" autocomplete="name" required />
            </div>
            <div class="field">
                <label for="cvFile">CV File</label>
                <input id="cvFile" type="file" name="cv" accept=".pdf,.doc,.docx,.txt" required />
            </div>
            <button id="submitBtn" type="submit">Submit</button>
            <div class="status" id="status"></div>
        </form>
    </div>

    <script>
        const form = document.getElementById('cvForm');
        const nameInput = document.getElementById('candidateName');
        const fileInput = document.getElementById('cvFile');
        const submitBtn = document.getElementById('submitBtn');
        const status = document.getElementById('status');
        const uploadUrl = {{ upload_url | tojson }};

        const setStatus = (msg) => { status.textContent = msg || ''; };

        form.addEventListener('submit', async (event) => {
            event.preventDefault();

            const name = nameInput.value.trim();
            const file = fileInput.files[0];

            if (!name) {
                setStatus('Please enter a candidate name.');
                return;
            }
            if (!file) {
                setStatus('Please choose a CV file.');
                return;
            }

            const formData = new FormData();
            formData.append('candidateName', name);
            formData.append('cv', file);

            submitBtn.disabled = true;
            setStatus('Uploading...');

            try {
                const res = await fetch(uploadUrl, {
                    method: 'POST',
                    body: formData
                });

                if (!res.ok) {
                    const errText = await res.text();
                    throw new Error(errText || `Upload failed with status ${res.status}`);
                }

                setStatus('Uploaded successfully.');
                form.reset();
            } catch (err) {
                console.error(err);
                setStatus(err.message || 'Failed to upload CV.');
            } finally {
                submitBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""
