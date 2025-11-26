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
            .table-card {
                margin-top: 20px;
                background: #0c1a28;
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 12px;
                padding: 14px;
            }
            .table-head {
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                margin-bottom: 8px;
                gap: 8px;
            }
            .table-head h2 {
                margin: 0;
                font-size: 18px;
            }
            .hint {
                color: var(--muted);
                font-size: 13px;
            }
            .totals {
                display: flex;
                justify-content: flex-end;
                align-items: center;
                gap: 6px;
                margin-top: 8px;
                color: var(--muted);
                font-size: 14px;
            }
            table {
                width: 100%;
                border-collapse: collapse;
            }
            th, td {
                text-align: left;
                padding: 10px;
            }
            thead {
                background: rgba(255,255,255,0.03);
            }
            tbody tr:nth-child(odd) {
                background: rgba(255,255,255,0.02);
            }
            tbody tr:nth-child(even) {
                background: rgba(255,255,255,0.04);
            }
            .pill {
                color: var(--accent);
                font-weight: 600;
            }
            .ghost {
                padding: 6px 10px;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.25);
                background: transparent;
                color: var(--text);
                cursor: pointer;
                transition: border 120ms ease, color 120ms ease, transform 120ms ease;
            }
            .ghost:hover {
                border-color: var(--accent);
                color: var(--accent);
                transform: translateY(-1px);
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
            <h1>Job Matching: Full Lists</h1>
            <p class="lede">Pick from any dropdown to add it to the table. Remove a row to clear that dropdown.</p>
            <div class="grid">
                <div>
                    <label for="category">Category</label>
                    <select id="category"></select>
                </div>
                <div>
                    <label for="subcategory">SubCategory</label>
                    <select id="subcategory"></select>
                </div>
                <div>
                    <label for="criteria">Criteria</label>
                    <select id="criteria"></select>
                </div>
                <div>
                    <label for="jobTitle">Job Title</label>
                    <select id="jobTitle"></select>
                </div>
            </div>
            <div class="table-card">
                <div class="table-head">
                    <h2>Selections</h2>
                    <span class="hint">Each dropdown can have one active choice.</span>
                </div>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Source</th>
                                <th>English</th>
                                <th>Arabic</th>
                                <th>Score</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody id="selectionBody">
                            <tr id="emptyRow"><td colspan="5" class="hint">Selections will appear here.</td></tr>
                        </tbody>
                    </table>
                </div>
                <div class="totals">
                    <span>Total score:</span>
                    <strong id="totalScore">0</strong>
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
            const selectionBody = document.getElementById('selectionBody');
            const emptyRow = document.getElementById('emptyRow');
            const totalScoreEl = document.getElementById('totalScore');

            const selectMap = {
                category: categorySel,
                subcategory: subcategorySel,
                criteria: criteriaSel,
                jobTitle: jobTitleSel,
            };
            const selectLabels = {
                category: 'Category',
                subcategory: 'Subcategory',
                criteria: 'Criteria',
                jobTitle: 'Job Title',
            };

            const setStatus = (msg) => { status.textContent = msg || ''; };

            const resetSelect = (selectEl, placeholder) => {
                selectEl.innerHTML = '';
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = placeholder;
                selectEl.appendChild(opt);
            };

            const fetchJSON = async (url) => {
                const res = await fetch(url);
                if (!res.ok) throw new Error(`Request failed with status ${res.status}`);
                return res.json();
            };

            const fillSelect = (selectEl, placeholder, rows) => {
                resetSelect(selectEl, placeholder);
                rows.forEach(row => {
                    const opt = document.createElement('option');
                    opt.value = row.ID;
                    opt.textContent = row.En_Name || row.Ar_Name || `Item ${row.ID}`;
                    if (row.En_Name) opt.dataset.en = row.En_Name;
                    if (row.Ar_Name) opt.dataset.ar = row.Ar_Name;
                    if (row.Score !== undefined && row.Score !== null) opt.dataset.score = row.Score;
                    selectEl.appendChild(opt);
                });
            };

            const updateEmptyRow = () => {
                const hasRows = selectionBody.querySelectorAll('tr[data-kind]').length > 0;
                emptyRow.style.display = hasRows ? 'none' : 'table-row';
            };

            const updateTotals = () => {
                let total = 0;
                selectionBody.querySelectorAll('tr[data-kind]').forEach(row => {
                    const val = parseFloat(row.querySelector('.score')?.textContent || '0');
                    if (!Number.isNaN(val)) total += val;
                });
                totalScoreEl.textContent = total;
                updateEmptyRow();
            };

            const removeRow = (kind) => {
                const row = selectionBody.querySelector(`tr[data-kind="${kind}"]`);
                if (row) row.remove();
            };

            const clearSelection = (kind) => {
                const selectEl = selectMap[kind];
                selectEl.value = '';
                removeRow(kind);
                updateTotals();
            };

            const upsertRow = (kind, opt) => {
                let row = selectionBody.querySelector(`tr[data-kind="${kind}"]`);
                if (!row) {
                    row = document.createElement('tr');
                    row.dataset.kind = kind;
                    row.innerHTML = `
                        <td class="pill"></td>
                        <td class="en"></td>
                        <td class="ar"></td>
                        <td class="score"></td>
                        <td class="actions"><button type="button" class="ghost">Remove</button></td>
                    `;
                    row.querySelector('button').addEventListener('click', () => clearSelection(kind));
                    selectionBody.appendChild(row);
                }
                row.querySelector('.pill').textContent = selectLabels[kind];
                row.querySelector('.en').textContent = opt.dataset.en || opt.textContent || '--';
                row.querySelector('.ar').textContent = opt.dataset.ar || '--';
                row.querySelector('.score').textContent = opt.dataset.score || '--';
                updateTotals();
            };

            const handleChange = (kind, selectEl) => {
                const opt = selectEl.selectedOptions[0];
                if (!opt || !opt.value) {
                    removeRow(kind);
                    updateTotals();
                    return;
                }
                upsertRow(kind, opt);
            };

            async function loadAllOptions() {
                setStatus('Loading all dropdown data...');
                try {
                    const [categories, subcategories, criteria, jobTitles] = await Promise.all([
                        fetchJSON('/api/categories'),
                        fetchJSON('/api/subcategories'),
                        fetchJSON('/api/criteria'),
                        fetchJSON('/api/job-titles'),
                    ]);
                    fillSelect(categorySel, 'Choose category', categories);
                    fillSelect(subcategorySel, 'Choose subcategory', subcategories);
                    fillSelect(criteriaSel, 'Choose criteria', criteria);
                    fillSelect(jobTitleSel, 'Choose job title', jobTitles);
                    setStatus('');
                } catch (err) {
                    console.error(err);
                    setStatus('Failed to load dropdown data. Check server logs.');
                }
            }

            Object.entries(selectMap).forEach(([kind, selectEl]) => {
                selectEl.addEventListener('change', () => handleChange(kind, selectEl));
            });

            loadAllOptions();
        </script>
    </body>
    </html>
    """

    @classmethod
    def render(cls):
        return render_template_string(cls.template)
