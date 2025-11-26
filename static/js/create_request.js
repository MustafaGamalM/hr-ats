// static/js/create_request.js

document.addEventListener('DOMContentLoaded', () => {
  const submitButton = document.getElementById('submitButton');
  const jobTitleSel = document.getElementById('jobTitle');
  const genderSel = document.getElementById('gender');
  const numApplicantsInput = document.getElementById('numApplicants');
  const neededByInput = document.getElementById('neededBy');

  submitButton.addEventListener('click', async () => {
    // Safely get job title id + name
    const jobTitleId = jobTitleSel.value || "";
    let jobTitleName = null;
    if (jobTitleSel.selectedOptions && jobTitleSel.selectedOptions.length > 0) {
      const fullText = jobTitleSel.selectedOptions[0].text || "";
      jobTitleName = fullText.includes(":") ? fullText.split(":")[1].trim() : fullText.trim();
      if (jobTitleName === "") jobTitleName = null;
    }

    // Parse/validate numeric inputs
    const numApplicants = parseInt(numApplicantsInput.value, 10);
    const neededBy = neededByInput.value ? neededByInput.value.trim() : "";

    // Basic validation
    if (!jobTitleId) {
      alert("Please select a job title.");
      return;
    }
    if (!jobTitleName) {
      // not fatal — you can allow null, but warn the user
      console.warn("jobTitleName not found for selected option");
    }
    if (Number.isNaN(numApplicants) || numApplicants < 1) {
      alert("Please enter a valid number of applicants (minimum 1).");
      return;
    }
    if (!neededBy) {
      alert("Please select the 'Needed By' date.");
      return;
    }

    const payload = {
      jobTitleId: jobTitleId,
      jobTitleName: jobTitleName,
      gender: genderSel.value || "Any",
      numApplicants: numApplicants,
      neededBy: neededBy
    };

    const { jsonConditions, sqlWhere } = buildJobRequestConditions(payload);

    // Disable button to prevent duplicate submissions
    submitButton.disabled = true;
    submitButton.textContent = "Submitting...";

    try {
      const resp = await fetch('/api/submit-request', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          jobTitleId: parseInt(payload.jobTitleId, 10),
          neededBy: payload.neededBy,
          jsonConditions: jsonConditions,
          sqlWhere: sqlWhere
        })
      });

      // Better error handling: try to extract JSON error body if status is not ok
      if (!resp.ok) {
        let errBody = null;
        try {
          errBody = await resp.json();
        } catch (_) {
          // ignore parse error
        }
        const msg = errBody && (errBody.error || errBody.message) ? (errBody.error || errBody.message) : `Server returned ${resp.status}`;
        throw new Error(msg);
      }

      const data = await resp.json();
      console.log('Success:', data);
      setTableData();
      alert('Request submitted successfully');
    } catch (err) {
      console.error('Error submitting request:', err);
      alert(`Submit failed: ${err.message || err}`);
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Submit";
    }
  });
});

/**
 * Builds the JSON-like conditions object and SQL WHERE string
 * based on the UI payload. Gender map is case-insensitive.
 */
function buildJobRequestConditions(payload) {
  // Case-insensitive gender map
  const genderMap = {
    "male": [1],
    "female": [2],
    "any": [1, 2]
  };

  const genderKey = (payload.gender || "Any").toString().trim().toLowerCase();
  const genderArr = genderMap[genderKey] || [1, 2];

  // JSON CONDITIONS OBJECT
  const jsonConditions = {
    job_Title_ID: payload.jobTitleId ? [parseInt(payload.jobTitleId, 10)] : null,
    job_Title: payload.jobTitleName || null,
    numOfApplicants: payload.numApplicants,
    gender_ID: genderArr
  };

  // SQL WHERE STRING (only gender and numOfApplicants, per your spec)
  const sqlParts = [
    `gender_ID in (${genderArr.join(",")})`,
    `numOfApplicants = ${Number(payload.numApplicants)}`
  ];
  const sqlWhere = sqlParts.join(" and ");

  return { jsonConditions, sqlWhere };
}

const reqGridEl = document.querySelector('#requestGrid');
const jobReqGridEl = document.querySelector('#jobTitleRequestGrid');

const reqColumnDefs = [
  { headerName: 'ID', field: 'ID', sortable: true, filter: true, resizable: true },
  { headerName: 'From Date', field: 'From_Date', sortable: true, filter: true, resizable: true },
  { headerName: 'To Date', field: 'To_Date', sortable: true, filter: true, resizable: true },
  { headerName: 'SearchCriteria', field: 'SearchCriteria', sortable: false, filter: true, resizable: true },
  { headerName: 'SearchCriteriaJson', field: 'SearchCriteriaJson', sortable: false, filter: true, resizable: true }
];

const jobReqColumnDefs = [
  { headerName: 'Job Title ID', field: 'Job_Title_ID', sortable: true, filter: true, resizable: true },
  { headerName: 'Request ID', field: 'Request_ID', sortable: true, filter: true, resizable: true }
];

// Use page size = 10 and include it in the selector to avoid AG Grid warnings.
const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50];

const reqGridOptions = {
  columnDefs: reqColumnDefs,
  rowData: [],
  defaultColDef: { sortable: true, filter: true, resizable: true },
  animateRows: true,
  pagination: true,
  paginationPageSize: DEFAULT_PAGE_SIZE,
  paginationPageSizeSelector: PAGE_SIZE_OPTIONS
};

const jobReqGridOptions = {
  columnDefs: jobReqColumnDefs,
  rowData: [],
  defaultColDef: { sortable: true, filter: true, resizable: true },
  animateRows: true,
  pagination: true,
  paginationPageSize: DEFAULT_PAGE_SIZE,
  paginationPageSizeSelector: PAGE_SIZE_OPTIONS
};

let reqGridApi = agGrid.createGrid(reqGridEl, reqGridOptions);
let jobReqGridApi = agGrid.createGrid(jobReqGridEl, jobReqGridOptions);

async function setTableData() {
  const resp = await fetch('/api/get-tables', {
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  });

  if (!resp.ok) {
    const errBody = await resp.text();
    throw new Error(`Server returned ${resp.status}: ${errBody}`);
  }

  const payload = await resp.json();

  // ---- FORMAT DATA DIRECTLY HERE ----

  // Format jobTitleRequests → rowData
  const jobTitleRowData = (payload.jobTitleRequests || []).map(item => ({
    Job_Title_ID: item.Job_Title_ID != null ? Number(item.Job_Title_ID) : null,
    Request_ID: item.Request_ID != null ? Number(item.Request_ID) : null
  }));

  // Helper: convert dates
  const fmtDate = v => {
    if (!v) return null;
    const d = new Date(v);
    return isNaN(d.getTime()) ? v : d.toLocaleDateString();  // format: "11/26/2025"
  };

  // Format requests → rowData
  const requestRowData = (payload.requests || []).map(r => {
    let prettyJson = null;

    if (r.SearchCriteriaJson) {
      try {
        const parsed = typeof r.SearchCriteriaJson === "string"
          ? JSON.parse(r.SearchCriteriaJson)
          : r.SearchCriteriaJson;
        prettyJson = JSON.stringify(parsed, null, 2);
      } catch {
        prettyJson = r.SearchCriteriaJson;
      }
    }

    return {
      ID: r.ID != null ? Number(r.ID) : null,
      From_Date: fmtDate(r.From_Date),
      To_Date: fmtDate(r.To_Date),
      SearchCriteria: r.SearchCriteria ?? null,
      SearchCriteriaJson: prettyJson
    };
  });

  reqGridApi.setGridOption('rowData', requestRowData)
  jobReqGridApi.setGridOption('rowData', jobTitleRowData)
}

setTableData();