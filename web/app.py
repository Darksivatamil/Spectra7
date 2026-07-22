import os
import sys
import re
import threading
import json
import time
import csv
import io
import traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit

from utils.logger import init_db, log_attack, update_attack, log_api_call, DB_PATH
from utils.validators import validate_count, validate_phone
from core.bomber import bomber, is_valid_phone, cancel_attack, AVAILABLE_MODES
from core.api_aggregator import load_apis, get_apis_for_type, add_api as agg_add_api, remove_api
from core.rotator import get_scorer, get_proxy_pool, record_api_result
from web.security import (
    login_manager, perform_login, perform_logout, is_ssrf_url,
    escape_html_str, add_security_headers,
)
import html as _html

init_db()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "spectra7_dev_key")
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_CHECK_DEFAULT"] = True
app.config["WTF_CSRF_SSL_STRICT"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

login_manager.init_app(app)
csrf = CSRFProtect(app)

# SocketIO for real-time updates (async_mode='threading' for Windows compat)
socketio = SocketIO(app, cors_allowed_origins="*" if os.getenv("CORS_ORIGINS", "").strip() else [], async_mode="threading", logger=False, engineio_logger=False)

storage_uri = os.getenv("REDIS_URL") or "memory://"
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=storage_uri,
    default_limits=["1000 per hour"],
    strategy="fixed-window",
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

with open(os.path.join(DATA_DIR, "categories.json"), "r", encoding="utf-8") as f:
    CATEGORIES = json.load(f)

attack_progress = {}
progress_lock = threading.Lock()


# ── Auth helpers ────────────────────────────────────────────────────────────

def _require_auth():
    from flask_login import current_user
    return current_user.is_authenticated


# ── Login routes ────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour")
def login():
    if request.method == "POST":
        csrf.protect()
        password = request.form.get("password") or (request.json or {}).get("password", "")
        ok, err = perform_login(password)
        if ok:
            return redirect(url_for("index"))
        return render_template("login.html", error=err or "Login failed"), 401
    return render_template("login.html", error=None)


@app.route("/logout", methods=["POST"])
def logout():
    perform_logout()
    return redirect(url_for("login"))


# ── Main page ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if not _require_auth():
        return redirect(url_for("login"))
    return render_template(
        "index.html",
        categories=list(CATEGORIES.keys()),
        modes=AVAILABLE_MODES,
        csrf_token=lambda: "",
    )


# ── Health / info ───────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "auth_required": True})

@app.route("/api/health/detailed")
def health_detailed():
    if not _require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    scorer = get_scorer()
    apis = load_apis()
    total_apis = sum(len(v) for atype in apis.values() for v in atype.values())
    alive_count = 0
    dead_count = 0
    apis_status = []
    for atype in ["sms", "call", "email"]:
        pool = apis.get(atype, {})
        for cc_key, entries in pool.items():
            for entry in entries:
                sc = scorer.score(entry["url"])
                apis_status.append({
                    "name": entry.get("name", "?"), "url": entry.get("url", ""),
                    "type": atype, "score": round(sc, 1),
                })
                if sc > 30:
                    alive_count += 1
                else:
                    dead_count += 1
    proxy_count = get_proxy_pool().count()
    return jsonify({
        "total_apis": total_apis, "alive": alive_count, "dead": dead_count,
        "proxies": proxy_count, "apis": sorted(apis_status, key=lambda x: -x["score"])[:50],
    })

@app.route("/api/categories")
def api_categories():
    return jsonify(list(CATEGORIES.keys()))

@app.route("/api/category/<name>")
def api_category_messages(name):
    msgs = CATEGORIES.get(name, [])
    return jsonify(msgs)


# ── CAPTCHA solver helpers ──────────────────────────────────────────────────

_CAPTCHA_PATTERNS = [
    re.compile(r"captcha|recaptcha|verify|security.check|bot.detection", re.I),
    re.compile(r"g-recaptcha|hcaptcha|turnstile", re.I),
    re.compile(r"please.verify|are.you.a.robot|unusual.traffic", re.I),
]

def detect_captcha(api_name, response_text):
    for pat in _CAPTCHA_PATTERNS:
        if pat.search(response_text):
            return True
    return False


# ── Attack launch ───────────────────────────────────────────────────────────

@app.route("/api/attack", methods=["POST"])
@csrf.exempt
@limiter.limit("10 per minute; 60 per hour")
def api_attack():
    try:
        if not _require_auth():
            return jsonify({"error": "Unauthorized"}), 401

        data = request.json or {}
        attack_type = data.get("type", "sms")
        cc = data.get("cc", "91")
        count = validate_count(data.get("count", 10))
        delay = float(data.get("delay", 2))
        threads = int(data.get("threads", 5))
        smart = data.get("smart_schedule", False)
        messages = data.get("messages", [])
        category = data.get("category") or None
        engine_mode = data.get("engine_mode", "auto")

        # Multi-target support
        targets_raw = data.get("targets", data.get("target", "")).strip()
        target_list = [re.sub(r"^\+?91", "", t.strip()) for t in targets_raw.replace(",", " ").split() if t.strip()]
        if not target_list:
            return jsonify({"error": "No target(s) provided"}), 400

        proxies_str = data.get("proxies", "").strip()
        if proxies_str:
            for p in proxies_str.replace(",", " ").split():
                if p.strip():
                    get_proxy_pool().add(p.strip())

        # Validate all targets
        for target in target_list:
            if not validate_phone(target, cc):
                return jsonify({"error": f"Invalid phone number: {target}"}), 400

        # ── Ethical guardrails ────────────────────────────────────────────
        allowlist_raw = os.getenv("ALLOWLIST_TARGETS", "")
        if allowlist_raw:
            allowed = [x.strip() for x in allowlist_raw.split(",") if x.strip()]
            allowed_normalized = [re.sub(r"^\+?91", "", a) for a in allowed]
            for target in target_list:
                if allowed and target not in allowed and target not in allowed_normalized:
                    return jsonify({"error": f"Target {target} not in ALLOWLIST_TARGETS"}), 403

        max_per_day = int(os.getenv("MAX_PER_TARGET_PER_DAY", "250"))
        if max_per_day > 0:
            from utils.logger import get_target_count_today
            for target in target_list:
                today_count = get_target_count_today(target)
                if today_count + count > max_per_day:
                    count = max(0, max_per_day - today_count)

        if count <= 0:
            return jsonify({"error": "Daily limit reached for all targets"}), 429

        if count > 100 and category == "hate":
            return jsonify({"error": "Abuse pattern: hate category + high volume"}), 403

        attack_ids = []
        for target in target_list:
            attack_id = log_attack(attack_type, target, count)
            attack_ids.append(attack_id)

            with progress_lock:
                attack_progress[attack_id] = {
                    "mode": "direct", "sent": 0, "success": 0, "fail": 0,
                    "total": count, "last_message": "", "last_text": "",
                    "status": "running", "ts": time.time(),
                }

            thread = threading.Thread(
                target=_run_attack,
                args=(attack_id, attack_type, cc, target, count,
                      delay, threads, smart, None, messages, category,
                      engine_mode),
                daemon=True,
            )
            thread.start()

        return jsonify({"attack_ids": attack_ids, "status": "started", "engine": engine_mode, "target_count": len(target_list)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _run_attack(attack_id, attack_type, cc, target, count,
                delay, threads, smart, _on_progress, messages, category=None,
                engine_mode="auto"):
    def on_progress(sent, success, failed, total, api_name="", last_msg=""):
        with progress_lock:
            attack_progress[attack_id] = {
                "mode": "direct", "sent": sent, "success": success, "fail": failed,
                "total": total, "last_message": api_name, "last_text": last_msg,
                "status": "running", "ts": time.time(),
            }
        socketio.emit("attack_update", {
            "attack_id": attack_id, "sent": sent, "success": success, "fail": failed,
            "total": total, "last_message": api_name, "last_text": last_msg, "status": "running",
        }, room=f"attack_{attack_id}")

    def ai_gen(idx=0, total=1):
        return messages[idx] if idx < len(messages) else (messages[-1] if messages else "")

    try:
        pool = get_apis_for_type(attack_type, cc)
        results = bomber(
            cc=cc, target=target, count=count, api_pool=pool,
            delay=delay, mode="direct", ai_gen=ai_gen, category=category,
            on_progress=on_progress, threads=threads, attack_id=attack_id,
            use_smart=smart, engine_mode=engine_mode,
        )
        with progress_lock:
            if attack_id in attack_progress:
                attack_progress[attack_id].update(results)
                attack_progress[attack_id]["status"] = "completed"
        socketio.emit("attack_update", {
            "attack_id": attack_id, "status": "completed", **results,
        }, room=f"attack_{attack_id}")
        update_attack(attack_id, results.get("success", 0), results.get("failed", 0), "completed")
    except Exception as e:
        traceback.print_exc()
        with progress_lock:
            if attack_id in attack_progress:
                attack_progress[attack_id]["status"] = "error"
                attack_progress[attack_id]["error"] = str(e)
        socketio.emit("attack_update", {
            "attack_id": attack_id, "status": "error", "error": str(e),
        }, room=f"attack_{attack_id}")
        update_attack(attack_id, 0, count, "error")


@app.route("/api/attack/<int:attack_id>/stop", methods=["POST"])
@csrf.exempt
def api_stop_attack(attack_id):
    if not _require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    ok = cancel_attack(attack_id)
    if ok:
        with progress_lock:
            if attack_id in attack_progress:
                attack_progress[attack_id]["status"] = "cancelled"
        update_attack(attack_id, 0, 0, "cancelled")
        return jsonify({"status": "cancelled"})
    return jsonify({"status": "not_found"}), 404


@app.route("/api/attack/<int:attack_id>/status")
def attack_status(attack_id):
    # GC stale progress entries older than 1h
    now = time.time()
    stale = []
    with progress_lock:
        for aid, p in list(attack_progress.items()):
            if now - p.get("ts", now) > 3600 and p.get("status") in ("completed", "error", "cancelled"):
                stale.append(aid)
        for aid in stale:
            attack_progress.pop(aid, None)
        p = attack_progress.get(attack_id, {})
    return jsonify(p)


@app.route("/api/attack/<int:attack_id>/export")
def attack_export(attack_id):
    if not _require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    fmt = request.args.get("format", "json").lower()
    conn = sqlite3.connect(DB_PATH)
    try:
        attack = conn.execute("SELECT * FROM attacks WHERE id=?", (attack_id,)).fetchone()
        logs = conn.execute(
            "SELECT * FROM logs WHERE attack_id=? ORDER BY timestamp", (attack_id,)
        ).fetchall()
    finally:
        conn.close()
    if not attack:
        return jsonify({"error": "Not found"}), 404
    cols_a = ["id", "attack_type", "target", "message_count", "success", "fail", "status", "started_at", "finished_at"]
    cols_l = ["id", "attack_id", "api_name", "target", "status", "response", "timestamp"]
    data = {"attack": dict(zip(cols_a, attack)), "logs": [dict(zip(cols_l, r)) for r in logs]}
    if fmt == "csv":
        si = io.StringIO()
        w = csv.writer(si)
        w.writerow(["type", "target", "api", "status", "timestamp"])
        for row in data["logs"]:
            w.writerow([row.get("api_name", ""), row.get("target", ""), row.get("api_name", ""), row.get("status", ""), row.get("timestamp", "")])
        return si.getvalue(), 200, {"Content-Type": "text/csv"}
    return jsonify(data)


# ── API Manager ─────────────────────────────────────────────────────────────

@app.route("/api/apis", methods=["GET"])
def api_list_apis():
    apis = load_apis()
    flat = []
    for atype in ["sms", "call", "email"]:
        pool = apis.get(atype, {})
        for cc_key, entries in pool.items():
            for entry in entries:
                flat.append({
                    "type": atype, "cc": cc_key,
                    "name": _html.escape(entry.get("name", "")),
                    "url": _html.escape(entry.get("url", "")),
                    "method": entry.get("method", "GET"),
                    "identifier": entry.get("identifier", ""),
                })
    return jsonify(flat)


@app.route("/api/apis", methods=["POST"])
@csrf.exempt
def api_add_api():
    if not _require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    url = data.get("url", "")
    if is_ssrf_url(url):
        return jsonify({"error": "URL rejected by SSRF guard"}), 400
    payload = {"name": data.get("name", ""), "method": data.get("method", "GET"), "url": url}
    if data.get("data"):
        try:
            payload["data"] = json.loads(data["data"]) if isinstance(data["data"], str) else data["data"]
        except json.JSONDecodeError:
            return jsonify({"error": "data must be valid JSON"}), 400
    if data.get("params"): payload["params"] = data["params"]
    if data.get("headers"): payload["headers"] = data["headers"]
    if data.get("json_body"):
        try:
            payload["json"] = json.loads(data["json_body"]) if isinstance(data["json_body"], str) else data["json_body"]
        except json.JSONDecodeError:
            return jsonify({"error": "json_body must be valid JSON"}), 400
    if data.get("identifier"): payload["identifier"] = data["identifier"]
    agg_add_api(data.get("type", "sms"), payload, data.get("cc", "91"))
    return jsonify({"status": "added"})


@app.route("/api/apis/<api_type>/<cc>/<int:index>", methods=["DELETE"])
@csrf.exempt
def api_remove_api_route(api_type, cc, index):
    if not _require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    remove_api(api_type, cc, index)
    return jsonify({"status": "removed"})



@socketio.on("connect")
def _socket_connect():
    emit("connected", {"status": "ok"})


@socketio.on("subscribe_attack")
def _subscribe_attack(data):
    """Client subscribes to an attack_id for real-time updates."""
    attack_id = data.get("attack_id")
    if attack_id:
        # Join a room named after the attack
        from flask_socketio import join_room
        join_room(f"attack_{attack_id}")
        emit("subscribed", {"attack_id": attack_id})


# ── Security headers ────────────────────────────────────────────────────────

@app.after_request
def _apply_security_headers(resp):
    return add_security_headers(resp)


@app.errorhandler(404)
def _not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(429)
def _rate_limited(e):
    return jsonify({"error": "Rate limit exceeded", "retry_after": str(e.description)}), 429

@app.errorhandler(500)
def _server_error(e):
    return jsonify({"error": "Internal server error"}), 500


# ── Standalone ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 5000))
    from waitress import serve
    serve(app, host=os.getenv("HOST", "0.0.0.0"), port=port)
