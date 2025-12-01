from flask import render_template_string


class CVScreen:
    """Encapsulates the full HTML for the CV points selector screen."""

    template = """
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
            .lede {
                margin: 0 0 18px;
                color: var(--muted);
            }
            .grid {
                display: grid;
                gap: 14px;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            }
            label {
                display: block;
                font-size: 14px;
                color: var(--muted);
                margin-bottom: 6px;
            }
            select, input, button {
                width: 100%;
                padding: 12px 14px;
                border-radius: 10px;
                border: 1px solid rgba(255,255,255,0.08);
                background: #0c1a28;
                color: var(--text);
                font-size: 15px;
                transition: border 120ms ease, box-shadow 120ms ease, opacity 120ms ease;
            }
            select:focus, input:focus, button:focus {
                outline: none;
                border-color: var(--accent);
                box-shadow: 0 0 0 3px rgba(76,195,255,0.18);
            }
            button {
                background: linear-gradient(90deg, var(--accent), #78d7ff);
                color: #081420;
                font-weight: 700;
                cursor: pointer;
            }
            button.primary {
                border: none;
            }
            button:disabled, select:disabled, input:disabled {
                opacity: 0.55;
                cursor: not-allowed;
            }
            .row {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 14px;
            }
            .hint {
                color: var(--muted);
                font-size: 13px;
            }
            .status {
                margin-top: 16px;
                font-size: 13px;
                color: var(--muted);
            }
            .button-cell {
                display: flex;
                align-items: flex-end;
            }
        </style>
    </head>
    <body>
        <div class="shell">
            <h1>Job Title Scoring</h1>
            <p class="lede">Pick a job title, drill down Category → Subcategory → Criteria, enter a score, and insert it.</p>
            <div class="grid">
                <div>
                    <label for="jobTitle">Job Title</label>
                    <select id="jobTitle"></select>
                </div>
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
                    <label for="score">Score</label>
                    <input id="score" type="number" min="0" step="1" placeholder="Enter score" />
                </div>
                <div class="button-cell">
                    <label>&nbsp;</label>
                    <button id="addRow" class="primary">Insert</button>
                </div>
            </div>
            <div class="status" id="status"></div>
        </div>

        <script>
            const jobTitleSel = document.getElementById('jobTitle');
            const categorySel = document.getElementById('category');
            const subcategorySel = document.getElementById('subcategory');
            const criteriaSel = document.getElementById('criteria');
            const scoreInput = document.getElementById('score');
            const addRowBtn = document.getElementById('addRow');
            const status = document.getElementById('status');

            const setStatus = (msg) => { status.textContent = msg || ''; };

            const resetSelect = (selectEl, placeholder, disabled = false) => {
                selectEl.innerHTML = '';
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = placeholder;
                selectEl.appendChild(opt);
                selectEl.disabled = disabled;
            };

            const fetchJSON = async (url) => {
                const res = await fetch(url);
                const body = await res.json();
                if (!res.ok) {
                    const err = body?.error || `Request failed with status ${res.status}`;
                    throw new Error(err);
                }
                return body;
            };

            const fillSelect = (selectEl, placeholder, rows, enabled = true) => {
                resetSelect(selectEl, placeholder, !enabled);
                if (!enabled) return;
                rows.forEach(row => {
                    const opt = document.createElement('option');
                    opt.value = row.ID;
                    opt.textContent = row.En_Name || row.Ar_Name || `Item ${row.ID}`;
                    if (row.En_Name) opt.dataset.en = row.En_Name;
                    if (row.Ar_Name) opt.dataset.ar = row.Ar_Name;
                    selectEl.appendChild(opt);
                });
                selectEl.disabled = false;
            };

            const readOption = (selectEl) => {
                const opt = selectEl.selectedOptions[0];
                if (!opt || !opt.value) return null;
                return {
                    id: Number(opt.value),
                    en: opt.dataset.en || opt.textContent,
                    ar: opt.dataset.ar || ''
                };
            };

            const loadJobTitles = async () => {
                const rows = await fetchJSON('/api/job-titles');
                fillSelect(jobTitleSel, 'Choose job title', rows, true);
            };

            const loadCategories = async () => {
                const rows = await fetchJSON('/api/categories');
                fillSelect(categorySel, 'Choose category', rows, true);
            };

            const loadSubcategories = async (categoryId) => {
                resetSelect(subcategorySel, categoryId ? 'Choose subcategory' : 'Pick category first', true);
                resetSelect(criteriaSel, 'Pick subcategory first', true);
                if (!categoryId) return;
                const rows = await fetchJSON(`/api/subcategories?categoryId=${categoryId}`);
                fillSelect(subcategorySel, 'Choose subcategory', rows, true);
            };

            const loadCriteria = async (subcategoryId) => {
                resetSelect(criteriaSel, subcategoryId ? 'Choose criteria' : 'Pick subcategory first', true);
                if (!subcategoryId) return;
                const rows = await fetchJSON(`/api/criteria?subcategoryId=${subcategoryId}`);
                fillSelect(criteriaSel, 'Choose criteria', rows, true);
            };

            const validateSelection = (selection) => {
                if (!selection.jobTitle) return 'Please select a job title';
                if (!selection.category) return 'Please select a category';
                if (!selection.subcategory) return 'Please select a subcategory';
                if (!selection.criteria) return 'Please select a criteria';
                if (Number.isNaN(selection.score)) return 'Please enter a numeric score';
                return '';
            };

            addRowBtn.addEventListener('click', async () => {
                const selection = {
                    jobTitle: readOption(jobTitleSel),
                    category: readOption(categorySel),
                    subcategory: readOption(subcategorySel),
                    criteria: readOption(criteriaSel),
                    score: parseFloat(scoreInput.value)
                };

                const error = validateSelection(selection);
                if (error) {
                    setStatus(error);
                    return;
                }

                setStatus('Saving...');
                try {
                    const res = await fetch('/api/job-title-criteria', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            jobTitleId: selection.jobTitle.id,
                            criteriaId: selection.criteria.id,
                            fullScore: selection.score
                        })
                    });
                    const body = await res.json();
                    if (!res.ok) {
                        throw new Error(body?.error || 'Failed to insert row');
                    }

                    scoreInput.value = '';
                    setStatus('Inserted successfully');
                } catch (err) {
                    console.error(err);
                    setStatus(err.message);
                }
            });

            jobTitleSel.addEventListener('change', () => setStatus(''));
            categorySel.addEventListener('change', (e) => {
                setStatus('');
                loadSubcategories(Number(e.target.value));
            });
            subcategorySel.addEventListener('change', (e) => {
                setStatus('');
                loadCriteria(Number(e.target.value));
            });
            criteriaSel.addEventListener('change', () => setStatus(''));

            (async function init() {
                setStatus('Loading dropdowns...');
                try {
                    await Promise.all([loadJobTitles(), loadCategories()]);
                    resetSelect(subcategorySel, 'Pick category first', true);
                    resetSelect(criteriaSel, 'Pick subcategory first', true);
                    setStatus('');
                } catch (err) {
                    console.error(err);
                    setStatus('Failed to load dropdown data. Check server logs.');
                }
            })();
        </script>
    </body>
    </html>
    """

    @classmethod
    def render(cls):
        return render_template_string(cls.template)
