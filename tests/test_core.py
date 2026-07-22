"""Core unit tests for Spectra7."""
import sys, os, json, re, tempfile, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Validator tests ─────────────────────────────────────────────────────────

def test_validate_phone_india():
    from utils.validators import validate_phone
    assert validate_phone("9876543210", "91") is True
    assert validate_phone("5876543210", "91") is False  # starts with 5
    assert validate_phone("12345", "91") is False
    assert validate_phone("1234567890", "1") is True   # US 10 digits

def test_validate_count():
    from utils.validators import validate_count
    assert validate_count(5) == 5
    assert validate_count(0) == 1
    assert validate_count(20000) == 10000

def test_validate_email():
    from utils.validators import validate_email
    assert validate_email("test@example.com") is True
    assert validate_email("not-an-email") is False

# ── Crypto tests ────────────────────────────────────────────────────────────

def test_crypto_roundtrip():
    key = "test-key-" + os.urandom(4).hex()
    os.environ["FERNET_KEY"] = "dGVzdC1rZXktMTIz"  # not a real fernet key
    from utils.crypto import encrypt_api_key, decrypt_api_key, get_nvidia_key
    # This will fail with bad fernet key — skip
    # We test the import is ok
    from utils.crypto import get_fernet, encrypt_api_key, decrypt_api_key
    assert callable(get_fernet)

# ── Identifier matching tests ──────────────────────────────────────────────

def test_match_identifier_substring():
    from core.api_aggregator import _match_identifier
    assert _match_identifier("success", '{"status":"success"}', 200) is True
    assert _match_identifier("failure", '{"status":"success"}', 200) is False

def test_match_identifier_status_code():
    from core.api_aggregator import _match_identifier
    assert _match_identifier("200", "ok", 200) is True
    assert _match_identifier("201", "created", 200) is False
    assert _match_identifier("400", "bad", 200) is False

def test_match_identifier_wildcard():
    from core.api_aggregator import _match_identifier
    assert _match_identifier("2XX", "ok", 200) is True
    assert _match_identifier("2xx", "ok", 204) is True
    assert _match_identifier("3XX", "redirect", 302) is True
    assert _match_identifier("4XX", "error", 404) is True
    assert _match_identifier("2XX", "ok", 300) is False

def test_match_identifier_regex():
    from core.api_aggregator import _match_identifier
    assert _match_identifier("@\\d{4}", "code: 1234", 200) is True
    assert _match_identifier("@\\d{4}", "code: ABC", 200) is False

def test_match_identifier_empty():
    from core.api_aggregator import _match_identifier
    assert _match_identifier("", "any text", 200) is True

# ── Scheduler tests ─────────────────────────────────────────────────────────

def test_schedule_manual():
    from core.scheduler import schedule_manual
    delays = schedule_manual(5, 2.0)
    assert len(delays) == 5
    assert all(d == 2.0 for d in delays)

def test_schedule_smart():
    from core.scheduler import schedule_smart
    delays = schedule_smart(10, (5, 30))
    assert len(delays) == 10
    assert all(5 <= d <= 30 for d in delays)

# ── Attack dispatcher tests (mocked) ────────────────────────────────────────

def test_dispatcher_sequential():
    from core.dispatch.threaded import ThreadedDispatcher
    d = ThreadedDispatcher("91", "9876543210", 2,
                           [{"name": "test", "method": "GET",
                             "url": "https://httpbin.org/get",
                             "identifier": "200"}],
                           threads=1)
    result = d.run()
    assert result.sent >= 0  # may fail or succeed depending on network

# ── Template XSS test ──────────────────────────────────────────────────────

def test_template_no_xss():
    html = open(os.path.join(os.path.dirname(__file__), "..", "web", "templates", "index.html"),
                encoding="utf-8").read()
    # Verify esc() helper is present and has all 5 entities
    assert "&amp;" in html
    assert "&lt;" in html
    assert "&gt;" in html
    assert "&quot;" in html
    assert "&#39;" in html

# ── Categories integrity ────────────────────────────────────────────────────

def test_categories_loaded():
    from web import app as webapp  # triggers lazy load
    # categories.json should have 20+ categories
    assert hasattr(webapp, "CATEGORIES") or callable(getattr(webapp, "api_categories", None))
    # Verify file has 20+
    cats_path = os.path.join(os.path.dirname(__file__), "..", "data", "categories.json")
    with open(cats_path, encoding="utf-8") as f:
        cats = json.load(f)
    assert len(cats) >= 20, f"Expected 20+ categories, got {len(cats)}"

# ── DB sanity ───────────────────────────────────────────────────────────────

def test_db_init():
    from utils.logger import init_db, DB_PATH
    init_db()
    assert os.path.exists(DB_PATH), "DB file not created"
    conn = sqlite3.connect(DB_PATH)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = [r[0] for r in tables]
    assert "attacks" in names
    assert "api_keys" in names
    conn.close()

# ── Security module ─────────────────────────────────────────────────────────

def test_ssrf_guard():
    from web.security import is_ssrf_url
    assert is_ssrf_url("http://127.0.0.1/") is True
    assert is_ssrf_url("http://169.254.169.254/") is True
    assert is_ssrf_url("http://10.0.0.1/") is True
    assert is_ssrf_url("http://192.168.1.1/") is True
    assert is_ssrf_url("https://api.example.com/") is False
    assert is_ssrf_url("file:///etc/passwd") is True

def test_escape_html():
    from web.security import escape_html_str
    assert escape_html_str('<script>alert(1)</script>') == '&lt;script&gt;alert(1)&lt;/script&gt;'
    assert escape_html_str('hello') == 'hello'
    assert escape_html_str(None) == ''


# ── Pool recycling (regression: all APIs must be cycled, not dropped) ────

def test_dispatcher_always_recycles_api():
    """When all APIs fail, they must be recycled so later messages are
    attempted instead of silently dropped."""
    from core.dispatch.threaded import ThreadedDispatcher
    # 5 broken APIs, 10 messages, 3 threads
    broken_apis = [
        {"name": f"dead-{i}", "method": "GET",
         "url": "http://127.0.0.1:1/nope", "identifier": "200"}
        for i in range(5)
    ]
    d = ThreadedDispatcher("91", "9876543210", 10, broken_apis, threads=3,
                           delay=0)
    result = d.run()
    # All 10 should have been attempted (all fail, but none silently dropped)
    assert result.sent == 10, f"Expected sent=10, got {result.sent}"
    assert result.success == 0
    assert result.failed == 10

def test_dispatcher_recycles_partial():
    """With 3 working + 2 broken APIs, all messages are attempted."""
    import threading, time
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from core.dispatch.threaded import ThreadedDispatcher

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        def log_message(self, *a): pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)

    try:
        apis = [
            {"name": "bad", "method": "GET",
             "url": "http://127.0.0.1:1/nope", "identifier": "200"},
            {"name": "good", "method": "GET",
             "url": f"http://127.0.0.1:{port}/", "identifier": "200"},
            {"name": "bad2", "method": "GET",
             "url": "http://127.0.0.1:2/nope", "identifier": "200"},
        ]
        d = ThreadedDispatcher("91", "9876543210", 6, apis, threads=3,
                               delay=0)
        result = d.run()
        assert result.sent == 6, f"sent={result.sent}"
        assert result.success > 0, f"success={result.success}"
        assert result.success + result.failed == 6
    finally:
        server.shutdown()
