import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from analyzer import analyze_statements
from file_parser import parse_file
from report_generator import generate_report

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

UPLOAD_BASE = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXTENSIONS = {"pdf", "xlsx", "xls", "csv"}

# In-memory job store  {report_id: {...}}
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _cleanup_old() -> None:
    cutoff = datetime.now() - timedelta(hours=1)
    with _lock:
        stale = [rid for rid, j in _jobs.items() if j["created_at"] < cutoff]
    for rid in stale:
        with _lock:
            job = _jobs.pop(rid, {})
        upload_dir = job.get("upload_dir", "")
        if upload_dir and os.path.isdir(upload_dir):
            shutil.rmtree(upload_dir, ignore_errors=True)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    _cleanup_old()

    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "לא נבחרו קבצים"}), 400

    report_id = str(uuid.uuid4())
    upload_dir = os.path.join(UPLOAD_BASE, report_id)
    os.makedirs(upload_dir, exist_ok=True)

    saved: list[str] = []
    for f in files:
        if f and _allowed(f.filename):
            path = os.path.join(upload_dir, secure_filename(f.filename))
            f.save(path)
            saved.append(path)

    if not saved:
        shutil.rmtree(upload_dir, ignore_errors=True)
        return jsonify({"error": "לא נמצאו קבצים תקינים (PDF / Excel / CSV)"}), 400

    with _lock:
        _jobs[report_id] = {
            "status": "processing",
            "path": None,
            "error": None,
            "summary": "",
            "suspicious_count": 0,
            "upload_dir": upload_dir,
            "created_at": datetime.now(),
        }

    threading.Thread(target=_run_analysis, args=(report_id, saved, upload_dir), daemon=True).start()
    return jsonify({"report_id": report_id})


@app.route("/status/<report_id>")
def status(report_id: str):
    with _lock:
        job = _jobs.get(report_id)
    if job is None:
        return jsonify({"error": "לא נמצא"}), 404
    return jsonify({
        "status": job["status"],
        "error": job.get("error"),
        "summary": job.get("summary", ""),
        "suspicious_count": job.get("suspicious_count", 0),
    })


@app.route("/download/<report_id>")
def download(report_id: str):
    with _lock:
        job = _jobs.get(report_id)
    if job is None:
        return jsonify({"error": "לא נמצא"}), 404
    if job["status"] != "done" or not job.get("path"):
        return jsonify({"error": "הדוח עדיין לא מוכן"}), 400
    return send_file(
        job["path"],
        as_attachment=True,
        download_name="bank_analysis_report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Background worker ─────────────────────────────────────────────────────────

def _run_analysis(report_id: str, saved_paths: list[str], upload_dir: str) -> None:
    try:
        parsed = [
            {"filename": os.path.basename(p), "content": parse_file(p)}
            for p in saved_paths
        ]
        analysis = analyze_statements(parsed)
        report_path = os.path.join(upload_dir, "report.xlsx")
        generate_report(analysis, report_path)

        with _lock:
            _jobs[report_id].update({
                "status": "done",
                "path": report_path,
                "summary": analysis.get("summary", ""),
                "suspicious_count": len(analysis.get("suspicious", [])),
            })
    except Exception as exc:
        with _lock:
            _jobs[report_id].update({"status": "error", "error": str(exc)})


if __name__ == "__main__":
    os.makedirs(UPLOAD_BASE, exist_ok=True)
    app.run(debug=True, host="0.0.0.0", port=5000)
