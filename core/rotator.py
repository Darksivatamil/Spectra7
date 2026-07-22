"""Smart API rotator — ML-inspired scoring, rate-limit avoidance, proxy rotation."""
import time, random, threading, json, os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SCORE_FILE = os.path.join(DATA_DIR, "api_scores.json")
_lock = threading.Lock()

DEFAULT_PROXIES = []


class APIScorer:
    """Tracks per-API success/failure and computes a score."""

    def __init__(self):
        self.scores = self._load()
        self._ttl = 300  # 5 min between score flushes

    def _load(self):
        try:
            if os.path.exists(SCORE_FILE):
                with open(SCORE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save(self):
        with _lock:
            with open(SCORE_FILE, "w") as f:
                json.dump(self.scores, f, indent=2)

    def record(self, api_url, success, elapsed):
        now = time.time()
        with _lock:
            if api_url not in self.scores:
                self.scores[api_url] = {"ok": 0, "fail": 0, "total": 0, "avg_ms": 0, "last": 0}
            s = self.scores[api_url]
            s["total"] += 1
            s["last"] = now
            if success:
                s["ok"] += 1
            else:
                s["fail"] += 1
            s["avg_ms"] = (s["avg_ms"] * (s["total"] - 1) + elapsed * 1000) / s["total"]

    def score(self, api_url):
        """Return 0-100 score. Higher = better."""
        s = self.scores.get(api_url)
        if not s or s["total"] < 1:
            return 50  # untested = neutral
        rate = s["ok"] / max(s["total"], 1)
        # Penalize for failures, boost for speed
        score = rate * 70  # success rate contributes 70 points max
        # Speed bonus: under 2s = 30 points, 2-5s = 15, >5s = 0
        if s["avg_ms"] < 2000:
            score += 30
        elif s["avg_ms"] < 5000:
            score += 15
        # Recency bonus: checked in last hour = +10
        if time.time() - s["last"] < 3600:
            score += 10
        return min(100, max(0, score))

    def best(self, apis, top_n=5):
        """Return top N API configs sorted by score."""
        scored = [(self.score(a["url"]), a) for a in apis]
        scored.sort(key=lambda x: -x[0])
        return [a for _, a in scored[:top_n]]

    def flush(self):
        self._save()


class ProxyPool:
    """Rotating proxy pool."""

    def __init__(self):
        self.proxies = list(DEFAULT_PROXIES)
        self._idx = 0
        self._lock = threading.Lock()

    def add(self, proxy_url):
        with self._lock:
            if proxy_url not in self.proxies:
                self.proxies.append(proxy_url)

    def remove(self, proxy_url):
        with self._lock:
            if proxy_url in self.proxies:
                self.proxies.remove(proxy_url)

    def next(self):
        with self._lock:
            if not self.proxies:
                return None
            p = self.proxies[self._idx % len(self.proxies)]
            self._idx += 1
            return p

    def count(self):
        return len(self.proxies)


# Singleton
_scorer = APIScorer()
_proxy_pool = ProxyPool()


def get_scorer():
    return _scorer


def get_proxy_pool():
    return _proxy_pool


def record_api_result(api_url, success, elapsed):
    _scorer.record(api_url, success, elapsed)


def get_best_apis(apis, top_n=5):
    return _scorer.best(apis, top_n)
