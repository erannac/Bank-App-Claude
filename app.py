import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context
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

os.makedirs(UPLOAD_BASE, exist_ok=True)


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _job_dir(report_id: str) -> str:
    return os.path.join(UPLOAD_BASE, report_id)


def _write_status(report_id: str, data: dict) -> None:
    path = os.path.join(_job_dir(report_id), "status.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_status(report_id: str) -> dict | None:
    path = os.path.join(_job_dir(report_id), "status.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cleanup_old() -> None:
    cutoff = datetime.now() - timedelta(hours=2)
    if not os.path.isdir(UPLOAD_BASE):
        return
    for rid in os.listdir(UPLOAD_BASE):
        job_dir = os.path.join(UPLOAD_BASE, rid)
        if not os.path.isdir(job_dir):
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(job_dir))
            if mtime < cutoff:
                shutil.rmtree(job_dir, ignore_errors=True)
        except Exception:
            pass


@app.errorhandler(Exception)
def handle_exception(e):
    print(f"[APP] unhandled exception: {e}")
    return jsonify({"error": f"שגיאת שרת: {type(e).__name__}: {e}"}), 500


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
    upload_dir = _job_dir(report_id)
    os.makedirs(upload_dir, exist_ok=True)

    saved: list[str] = []
    for f in files:
        if f and _allowed(f.filename):
            fname = secure_filename(f.filename)
            if not fname:
                continue
            path = os.path.join(upload_dir, fname)
            f.save(path)
            saved.append(path)

    if not saved:
        shutil.rmtree(upload_dir, ignore_errors=True)
        return jsonify({"error": "לא נמצאו קבצים תקינים (PDF / Excel / CSV)"}), 400

    result_box: dict = {}
    done_event = threading.Event()

    def worker() -> None:
        try:
            parsed = [
                {"filename": os.path.basename(p), "content": parse_file(p)}
                for p in saved
            ]
            analysis = analyze_statements(parsed)
            report_path = os.path.join(upload_dir, "report.xlsx")
            generate_report(analysis, report_path)
            data = {
                "status": "done",
                "report_id": report_id,
                "summary": analysis.get("summary", ""),
                "suspicious_count": len(analysis.get("suspicious", [])),
            }
            _write_status(report_id, data)
            result_box["ok"] = data
            print(f"[APP] {report_id[:8]} done")
        except Exception as exc:
            print(f"[APP] {report_id[:8]} error: {exc}")
            result_box["err"] = str(exc)
            shutil.rmtree(upload_dir, ignore_errors=True)
        finally:
            done_event.set()

    # daemon=False so the thread isn't killed during gunicorn graceful shutdown
    threading.Thread(target=worker, daemon=False).start()

    def stream():
        # Send a newline every 5 s to keep the connection alive through proxies
        while not done_event.wait(timeout=5):
            yield b"\n"
        if "err" in result_box:
            yield json.dumps({"error": result_box["err"]}, ensure_ascii=False).encode()
        else:
            yield json.dumps(result_box["ok"], ensure_ascii=False).encode()

    return Response(
        stream_with_context(stream()),
        content_type="application/json; charset=utf-8",
        headers={"X-Accel-Buffering": "no"},
    )


@app.route("/download/<report_id>")
def download(report_id: str):
    job = _read_status(report_id)
    if job is None or job.get("status") != "done":
        return jsonify({"error": "לא נמצא"}), 404
    report_path = os.path.join(_job_dir(report_id), "report.xlsx")
    if not os.path.exists(report_path):
        return jsonify({"error": "קובץ הדוח לא נמצא"}), 404
    return send_file(
        report_path,
        as_attachment=True,
        download_name="bank_analysis_report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
