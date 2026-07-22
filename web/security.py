"""Security: auth, CSRF, rate-limit, SSRF guard, headers."""
import os
import html
import ipaddress
import urllib.parse

from flask import request, jsonify, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv


class User(UserMixin):
    def __init__(self, name="admin"):
        self.id = name
        self.name = name


login_manager = LoginManager()
login_manager.login_view = "login"

ACTIVE_USERS = {}


@login_manager.user_loader
def load_user(user_id):
    return ACTIVE_USERS.get(user_id)


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Unauthorized - login required"}), 401
    return redirect(url_for("login"))


def get_dashboard_password():
    # 1. Try Environment variable
    pw = os.environ.get("DASHBOARD_PASSWORD")
    if pw:
        return pw.strip()
    # 2. Try .env file (load if not already loaded)
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=False)
        pw = os.environ.get("DASHBOARD_PASSWORD")
        if pw:
            return pw.strip()
    return None


def perform_login(password_attempt):
    expected = get_dashboard_password()
    if not expected:
        return False, "DASHBOARD_PASSWORD not configured"
    if password_attempt is None:
        return False, "Invalid password"
    if password_attempt.strip() == expected:
        u = User()
        ACTIVE_USERS[u.id] = u
        login_user(u, remember=False)
        return True, None
    return False, "Invalid password"


def perform_logout():
    ACTIVE_USERS.pop(current_user.id, None)
    logout_user()


PRIVATE_IP_PREFIXES = (
    "127.", "10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
    "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
    "169.254.", "::1", "fc", "fd", "fe80",
)


def is_ssrf_url(url):
    if not url:
        return True
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return True
    if parsed.scheme not in ("http", "https"):
        return True
    host = parsed.hostname or ""
    host = host.lower().strip("[]")
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    except ValueError:
        if host == "localhost" or any(host.startswith(p) for p in PRIVATE_IP_PREFIXES):
            return True
    if host.endswith(".internal") or host.endswith(".local"):
        return True
    return False


def escape_html_str(s):
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'"
    )
    return response
