'use strict';

const dropZone    = document.getElementById('drop-zone');
const fileInput   = document.getElementById('file-input');
const fileList    = document.getElementById('file-list');
const analyzeBtn  = document.getElementById('analyze-btn');
const btnLabel    = document.getElementById('btn-label');

const progressSection = document.getElementById('progress-section');
const progressBar     = document.getElementById('progress-bar');
const progressLabel   = document.getElementById('progress-label');

const resultsSection  = document.getElementById('results-section');
const summaryText     = document.getElementById('summary-text');
const statsRow        = document.getElementById('stats-row');
const downloadBtn     = document.getElementById('download-btn');

const errorSection = document.getElementById('error-section');
const errorText    = document.getElementById('error-text');

let selectedFiles = [];   // File objects
let currentReportId = null;
let pollTimer = null;

// ── Drag & Drop ────────────────────────────────────────────────────────────

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
['dragleave', 'dragend'].forEach(ev =>
  dropZone.addEventListener(ev, () => dropZone.classList.remove('drag-over'))
);
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  addFiles([...e.dataTransfer.files]);
});
fileInput.addEventListener('change', () => {
  addFiles([...fileInput.files]);
  fileInput.value = '';
});

// ── File management ────────────────────────────────────────────────────────

function addFiles(incoming) {
  const allowed = ['pdf', 'xlsx', 'xls', 'csv'];
  incoming.forEach(f => {
    const ext = f.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) return;
    if (selectedFiles.some(x => x.name === f.name && x.size === f.size)) return;
    selectedFiles.push(f);
  });
  renderFileList();
}

function removeFile(idx) {
  selectedFiles.splice(idx, 1);
  renderFileList();
}

function renderFileList() {
  if (selectedFiles.length === 0) {
    fileList.classList.add('hidden');
    fileList.innerHTML = '';
    analyzeBtn.disabled = true;
    return;
  }
  fileList.classList.remove('hidden');
  fileList.innerHTML = selectedFiles.map((f, i) => {
    const ext = f.name.split('.').pop().toLowerCase();
    const size = f.size < 1024 * 1024
      ? `${(f.size / 1024).toFixed(0)} KB`
      : `${(f.size / 1024 / 1024).toFixed(1)} MB`;
    return `
      <li class="file-item">
        <div class="file-icon ${ext}">${ext.toUpperCase()}</div>
        <span class="file-name">${f.name}</span>
        <span class="file-size">${size}</span>
        <button class="remove-btn" onclick="removeFile(${i})" title="הסר">
          <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </li>`;
  }).join('');
  analyzeBtn.disabled = false;
}

// ── Upload & Analyze ───────────────────────────────────────────────────────

analyzeBtn.addEventListener('click', startAnalysis);

async function startAnalysis() {
  if (selectedFiles.length === 0) return;

  // Reset UI
  hide(resultsSection);
  hide(errorSection);
  show(progressSection);
  setProgress(15, 'מעלה קבצים...');
  analyzeBtn.disabled = true;
  btnLabel.textContent = 'מנתח...';

  const form = new FormData();
  selectedFiles.forEach(f => form.append('files', f));

  let reportId;
  try {
    const res = await fetch('/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'שגיאה בהעלאה');
    reportId = data.report_id;
    currentReportId = reportId;
  } catch (err) {
    showError(err.message);
    return;
  }

  setProgress(40, 'מנתח תנועות עם Claude AI...');
  pollTimer = setInterval(() => pollStatus(reportId), 2000);
}

async function pollStatus(reportId) {
  try {
    const res = await fetch(`/status/${reportId}`);
    const data = await res.json();

    if (data.status === 'done') {
      clearInterval(pollTimer);
      setProgress(100, 'הניתוח הושלם!');
      setTimeout(() => {
        hide(progressSection);
        showResults(data, reportId);
      }, 600);
    } else if (data.status === 'error') {
      clearInterval(pollTimer);
      showError(data.error || 'שגיאה לא צפויה');
    } else {
      // Still processing — advance bar gently
      const bar = parseInt(progressBar.style.width, 10);
      if (bar < 90) setProgress(bar + 5, 'מנתח תנועות עם Claude AI...');
    }
  } catch {
    // Network hiccup — keep polling
  }
}

// ── Results ────────────────────────────────────────────────────────────────

function showResults(data, reportId) {
  summaryText.textContent = data.summary || 'הניתוח הושלם בהצלחה.';

  statsRow.innerHTML = `
    <div class="stat-card">
      <div class="stat-value text-red-400">${data.suspicious_count}</div>
      <div class="stat-label">ממצאים חשודים</div>
    </div>
    <div class="stat-card">
      <div class="stat-value text-green-400">✓</div>
      <div class="stat-label">הדוח מוכן להורדה</div>
    </div>`;

  downloadBtn.onclick = () => {
    window.location.href = `/download/${reportId}`;
  };

  show(resultsSection);
  analyzeBtn.disabled = false;
  btnLabel.textContent = 'נתח קבצים';
}

// ── Helpers ────────────────────────────────────────────────────────────────

function setProgress(pct, label) {
  progressBar.style.width = `${pct}%`;
  progressLabel.textContent = label;
}

function showError(msg) {
  clearInterval(pollTimer);
  hide(progressSection);
  errorText.textContent = msg;
  show(errorSection);
  analyzeBtn.disabled = false;
  btnLabel.textContent = 'נתח קבצים';
}

function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }
