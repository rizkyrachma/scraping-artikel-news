"""
extract_content.py
Ekstraksi isi/konten teks artikel berita menggunakan trafilatura dengan fallback newspaper3k.
Mendukung resolusi/dekoding URL Google News RSS tahan rate limit (cache persisten,
adaptive throttling, circuit breaker, dan fallback berlapis), pembatasan panjang teks, dan deteksi artikel pendek.
"""

from collections import deque
from datetime import timedelta
import json
import os
import random
import re
import socket
import threading
import time
from urllib.parse import urlparse

import requests
import trafilatura
import urllib3
from newspaper import Article  # type: ignore
from rapidfuzz import fuzz

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cegah proses hanging tanpa batas di level socket OS
socket.setdefaulttimeout(15)

_DEFAULT_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

try:
    import googlenewsdecoder  # type: ignore
    _decoder_fn = (
        getattr(googlenewsdecoder, "gnewsdecoder", None)
        or getattr(googlenewsdecoder, "new_decoderv1", None)
    )
    _offline_decoder_fn = getattr(googlenewsdecoder, "decoderv1", None)
    _req_holder = getattr(
        getattr(getattr(googlenewsdecoder, "GoogleDecoder", None), "get_decoding_params", None),
        "__globals__",
        None,
    ) or getattr(_decoder_fn, "__globals__", {})
    g_req = _req_holder.get("requests") if isinstance(_req_holder, dict) else None
    if g_req and not getattr(g_req, "_patched_timeout", False):
        _orig_get = g_req.get
        _orig_post = g_req.post

        def _safe_get(*a, **kw):
            kw.setdefault("timeout", 10)
            kw.setdefault("headers", _DEFAULT_BROWSER_HEADERS)
            return _orig_get(*a, **kw)

        def _safe_post(*a, **kw):
            kw.setdefault("timeout", 10)
            return _orig_post(*a, **kw)

        g_req.get = _safe_get
        g_req.post = _safe_post
        g_req._patched_timeout = True
except ImportError:
    googlenewsdecoder = None
    _decoder_fn = None
    _offline_decoder_fn = None

try:
    from fetch_news import GoogleCaptchaBlockedError, is_valid_domain
except ImportError:
    try:
        from src.fetch_news import GoogleCaptchaBlockedError, is_valid_domain
    except ImportError:
        class GoogleCaptchaBlockedError(Exception):
            """Exception khusus jika Google News mengalihkan ke CAPTCHA gate (google.com/sorry/index)."""
            pass

        def is_valid_domain(url: str) -> bool:
            return bool(url)

try:
    from config import parse_to_wib
except ImportError:
    try:
        from src.config import parse_to_wib
    except ImportError:
        def parse_to_wib(val):
            return None


SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_NEWS_URL = "https://google.serper.dev/news"
EXA_SEARCH_URL = "https://api.exa.ai/search"
DEFAULT_DECODE_CACHE_FILE = os.path.join("hasil_scrapping", "cache_decode.json")

_BLOCKED_DECODED_HOSTS = {
    "news.google.com",
    "google.com",
    "www.google.com",
    "consent.google.com",
    "accounts.google.com",
    "support.google.com",
    "policies.google.com",
}


def normalize_google_news_url(url: str) -> str:
    """Menormalisasi URL artikel Google News menjadi kunci cache kanonik yang konsisten."""
    if not url:
        return ""
    raw = str(url).strip()
    try:
        parsed = urlparse(raw)
        host = parsed.netloc.lower().split(":")[0]
        if "news.google.com" in host:
            parts = [p for p in parsed.path.split("/") if p]
            for idx, seg in enumerate(parts[:-1]):
                if seg in ("articles", "read") and parts[idx + 1]:
                    return f"https://news.google.com/articles/{parts[idx + 1]}"
            clean_path = parsed.path.rstrip("/")
            return f"https://news.google.com{clean_path}" if clean_path else raw.split("?")[0].rstrip("/")
    except Exception:
        pass
    return raw.split("?")[0].rstrip("/")


def is_valid_decoded_url(url: str) -> bool:
    """Memastikan hasil dekode adalah URL artikel penerbit yang valid (bukan Google/homepage kosong)."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if not u or any(ch.isspace() or ord(ch) < 32 for ch in u):
        return False
    try:
        parsed = urlparse(u)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.netloc.lower().split(":")[0]
    if not host or "." not in host:
        return False
    if host in _BLOCKED_DECODED_HOSTS or host.endswith(".google.com") and "news.google" in host:
        return False
    if "google.com/sorry" in u.lower():
        return False
    # Tolak homepage penerbit polos tanpa path artikel maupun query id
    if not parsed.path.strip("/") and not parsed.query:
        return False
    return is_valid_domain(u)


class DecodeCache:
    """Cache persisten JSON untuk pasangan URL Google News -> URL asli penerbit (tidak menyimpan kegagalan)."""

    def __init__(self, filepath: str | None = None):
        self.filepath = filepath or os.environ.get("DECODE_CACHE_FILE") or DEFAULT_DECODE_CACHE_FILE
        self._lock = threading.RLock()
        self._data: dict[str, str] = {}
        self._loaded_mtime: float = -1.0
        self._dirty = False
        self.load()

    def _reload_if_newer_locked(self) -> None:
        try:
            if os.path.exists(self.filepath):
                mtime = os.path.getmtime(self.filepath)
                if mtime > self._loaded_mtime:
                    self._load_locked()
        except Exception:
            pass

    def _load_locked(self) -> None:
        if not os.path.exists(self.filepath):
            self._loaded_mtime = 0.0
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                cleaned = {}
                for k, v in raw.items():
                    if isinstance(k, str) and isinstance(v, str) and "news.google.com" in k and is_valid_decoded_url(v):
                        cleaned[normalize_google_news_url(k)] = v.strip()
                # Pertahankan entri baru di memori yang belum sempat ditulis ke disk
                for k, v in self._data.items():
                    cleaned.setdefault(k, v)
                self._data = cleaned
            self._loaded_mtime = os.path.getmtime(self.filepath)
        except Exception:
            pass

    def load(self) -> None:
        with self._lock:
            self._load_locked()

    def get(self, url: str) -> str | None:
        if not url or "news.google.com" not in url:
            return None
        norm = normalize_google_news_url(url)
        with self._lock:
            self._reload_if_newer_locked()
            val = self._data.get(norm) or self._data.get(url.strip())
            if val and is_valid_decoded_url(val):
                return val
        return None

    def set(self, url: str, decoded_url: str) -> bool:
        if not url or "news.google.com" not in url or not is_valid_decoded_url(decoded_url):
            return False
        norm = normalize_google_news_url(url)
        val = decoded_url.strip()
        with self._lock:
            if self._data.get(norm) != val:
                self._data[norm] = val
                self._dirty = True
        return True

    def size(self) -> int:
        with self._lock:
            return len(self._data)

    def save(self, force: bool = False) -> None:
        with self._lock:
            if not force and not self._dirty:
                return
            snapshot = dict(self._data)
            target = self.filepath
            out_dir = os.path.dirname(target)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            tmp_path = f"{target}.tmp.{os.getpid()}.{threading.get_ident()}"
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, target)
                self._loaded_mtime = os.path.getmtime(target)
                self._dirty = False
            except Exception as e:
                print(f"  [Cache Decode Warning] Gagal menyimpan {target}: {e}", flush=True)
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass


class AdaptiveDecodeController:
    """Pengontrol laju request Google News dengan rolling failure window, exponential backoff, jitter, concurrency adaptif, dan circuit breaker."""

    def __init__(
        self,
        window_size: int = 20,
        failure_threshold: float = 0.50,
        min_samples: int = 5,
        base_interval: float = 0.4,
        max_interval: float = 4.0,
        backoff_base: float = 1.0,
        backoff_max: float = 8.0,
        circuit_pause: float = 12.0,
        circuit_cooldown: float = 60.0,
        base_workers: int = 6,
        min_workers: int = 1,
        time_fn=None,
        sleep_fn=None,
        jitter_fn=None,
    ):
        self.window_size = max(1, int(window_size))
        self.failure_threshold = float(failure_threshold)
        self.min_samples = max(1, int(min_samples))
        self.base_interval = float(base_interval)
        self.max_interval = float(max_interval)
        self.backoff_base = float(backoff_base)
        self.backoff_max = float(backoff_max)
        self.circuit_pause = float(circuit_pause)
        self.circuit_cooldown = float(circuit_cooldown)
        self.base_workers = max(1, int(base_workers))
        self.min_workers = max(1, int(min_workers))

        self._time_fn = time_fn or time.monotonic
        self._sleep_fn = sleep_fn or time.sleep
        self._jitter_fn = jitter_fn or random.uniform

        self._lock = threading.RLock()
        self._window: deque[bool] = deque(maxlen=self.window_size)
        self._state = "CLOSED"
        self._open_until = 0.0
        self._half_open_probing = False
        self._next_slot_time = 0.0
        self._consecutive_failures = 0
        self._circuit_trips = 0

    def failure_rate(self) -> float:
        with self._lock:
            return self._failure_rate_locked()

    def _failure_rate_locked(self) -> float:
        if not self._window:
            return 0.0
        failures = sum(1 for ok in self._window if not ok)
        return failures / len(self._window)

    def _sync_state_locked(self, now: float) -> None:
        if self._state == "OPEN" and now >= self._open_until:
            self._state = "HALF_OPEN"
            self._half_open_probing = False

    def state(self) -> str:
        with self._lock:
            self._sync_state_locked(self._time_fn())
            return self._state

    def recommended_workers(self, requested_max: int | None = None) -> int:
        req = self.base_workers if requested_max is None else max(1, int(requested_max))
        with self._lock:
            now = self._time_fn()
            self._sync_state_locked(now)
            if self._state in ("OPEN", "HALF_OPEN"):
                return min(req, self.min_workers)
            fr = self._failure_rate_locked()
            if len(self._window) >= self.min_samples and fr >= self.failure_threshold:
                return min(req, self.min_workers)
            if len(self._window) >= self.min_samples and fr >= (self.failure_threshold * 0.5):
                return min(req, max(self.min_workers, req // 2))
            return req

    def allow_google_decode(self) -> bool:
        with self._lock:
            now = self._time_fn()
            self._sync_state_locked(now)
            return self._state != "OPEN"

    def acquire_google_slot(self, min_interval_override: float | None = None) -> tuple[bool, str]:
        wait_seconds = 0.0
        mode = "closed"
        with self._lock:
            now = self._time_fn()
            self._sync_state_locked(now)

            if self._state == "OPEN":
                return False, "circuit_open"

            if self._state == "HALF_OPEN":
                if self._half_open_probing:
                    return False, "circuit_open"
                self._half_open_probing = True
                mode = "half_open_probe"

            base = self.base_interval if min_interval_override is None else float(min_interval_override)
            fr = self._failure_rate_locked()
            pressure = min(1.0, fr / max(self.failure_threshold, 1e-6)) if len(self._window) >= 3 else 0.0
            interval = base + (max(base, self.max_interval) - base) * pressure
            jittered = max(0.0, interval * float(self._jitter_fn(0.85, 1.35)))

            slot = max(now, self._next_slot_time)
            wait_seconds = max(0.0, slot - now)
            self._next_slot_time = slot + jittered

        if wait_seconds > 0:
            self._sleep_fn(wait_seconds)
        return True, mode

    def compute_backoff(self, attempt: int) -> float:
        exp = min(self.backoff_max, self.backoff_base * (2 ** max(0, int(attempt))))
        return max(0.0, exp * float(self._jitter_fn(0.85, 1.25)))

    def sleep_backoff(self, attempt: int) -> float:
        delay = self.compute_backoff(attempt)
        if delay > 0:
            self._sleep_fn(delay)
        return delay

    def record_success(self) -> None:
        with self._lock:
            self._window.append(True)
            self._consecutive_failures = 0
            if self._state == "HALF_OPEN":
                self._state = "CLOSED"
                self._half_open_probing = False

    def record_failure(self) -> bool:
        tripped = False
        pause_secs = 0.0
        fr_pct = 0.0
        win_len = 0
        trip_num = 0

        with self._lock:
            now = self._time_fn()
            self._window.append(False)
            self._consecutive_failures += 1
            fr = self._failure_rate_locked()
            win_len = len(self._window)

            should_trip = (
                self._state == "HALF_OPEN"
                or (self._state == "CLOSED" and win_len >= self.min_samples and fr >= self.failure_threshold)
            )
            if should_trip:
                self._state = "OPEN"
                self._half_open_probing = False
                self._circuit_trips += 1
                self._open_until = now + self.circuit_pause + self.circuit_cooldown
                tripped = True
                pause_secs = self.circuit_pause
                fr_pct = fr * 100.0
                trip_num = self._circuit_trips

        if tripped:
            print(
                f"  [Circuit Breaker OPEN #{trip_num}] Failure rate {fr_pct:.0f}% "
                f"(rolling {win_len} req) >= {self.failure_threshold * 100:.0f}%. "
                f"Pause {pause_secs:.1f}s lalu lanjut via fallback...",
                flush=True,
            )
            if pause_secs > 0:
                self._sleep_fn(pause_secs)
            with self._lock:
                if self._state == "OPEN":
                    self._open_until = self._time_fn() + self.circuit_cooldown
        return tripped

    def reset_for_retry_pass(self) -> None:
        """Membuka probe single-thread untuk antrean retry di akhir run."""
        with self._lock:
            if self._state == "OPEN":
                self._state = "HALF_OPEN"
            self._half_open_probing = False
            self._open_until = 0.0

    def snapshot(self) -> dict:
        with self._lock:
            now = self._time_fn()
            self._sync_state_locked(now)
            win_len = len(self._window)
            fails = sum(1 for ok in self._window if not ok)
            fr = (fails / win_len) if win_len else 0.0
            return {
                "state": self._state,
                "rolling_window_size": win_len,
                "rolling_failures": fails,
                "rolling_failure_rate": round(fr, 4),
                "circuit_trips": self._circuit_trips,
                "consecutive_failures": self._consecutive_failures,
                "recommended_workers": self.recommended_workers(),
            }


_DEFAULT_DECODE_CACHE: DecodeCache | None = None
_DEFAULT_DECODE_CONTROLLER: AdaptiveDecodeController | None = None
_SINGLETON_LOCK = threading.Lock()
_SEARCH_FALLBACK_LOCK = threading.Lock()
_SEARCH_FALLBACK_MEMO: dict[tuple[str, str], tuple[str | None, str, str]] = {}
_SERPER_EXHAUSTED = False
_EXA_EXHAUSTED = False
_LOGGED_DECODE_WARNINGS = 0


def get_decode_cache() -> DecodeCache:
    global _DEFAULT_DECODE_CACHE
    with _SINGLETON_LOCK:
        target = os.environ.get("DECODE_CACHE_FILE") or DEFAULT_DECODE_CACHE_FILE
        if _DEFAULT_DECODE_CACHE is None or _DEFAULT_DECODE_CACHE.filepath != target:
            _DEFAULT_DECODE_CACHE = DecodeCache(target)
        return _DEFAULT_DECODE_CACHE


def save_decode_cache(force: bool = False) -> None:
    if _DEFAULT_DECODE_CACHE is not None:
        _DEFAULT_DECODE_CACHE.save(force=force)


def get_decode_controller() -> AdaptiveDecodeController:
    global _DEFAULT_DECODE_CONTROLLER
    with _SINGLETON_LOCK:
        if _DEFAULT_DECODE_CONTROLLER is None:
            _DEFAULT_DECODE_CONTROLLER = AdaptiveDecodeController()
        return _DEFAULT_DECODE_CONTROLLER


def try_offline_base64_decode(url: str) -> str | None:
    """Mencoba dekode Google News URL format lama secara offline tanpa HTTP request."""
    if not url or "news.google.com" not in url or _offline_decoder_fn is None:
        return None
    try:
        res = _offline_decoder_fn(url)
        if isinstance(res, str) and res != url and res.startswith(("http://", "https://")) and is_valid_decoded_url(res):
            return res.strip()
    except Exception:
        pass
    return None


def fallback_url_from_metadata(item: dict) -> str | None:
    """Layer 2: mengambil URL artikel non-Google yang valid dari metadata item / RSS."""
    if not isinstance(item, dict):
        return None
    candidates: list[str] = []
    for key in ("resolved_url", "origin_url", "original_link"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())
    meta_list = item.get("rss_metadata_urls")
    if isinstance(meta_list, (list, tuple)):
        candidates.extend(str(u).strip() for u in meta_list if u)
    for link_obj in item.get("links") or []:
        if isinstance(link_obj, dict) and link_obj.get("href"):
            candidates.append(str(link_obj["href"]).strip())
    for html_field in (item.get("summary") or "", item.get("description") or ""):
        if html_field:
            candidates.extend(re.findall(r'href=["\'](https?://[^"\'\s<>]+)["\']', str(html_field)))
    src_u = item.get("source_url")
    if isinstance(src_u, str) and src_u.strip():
        candidates.append(src_u.strip())

    for cand in candidates:
        if is_valid_decoded_url(cand):
            return cand
    return None


def _clean_search_title(title: str, media_name: str = "") -> str:
    t = str(title or "").strip()
    if media_name:
        suffix = f" - {media_name.strip()}"
        while t.lower().endswith(suffix.lower()):
            t = t[:-len(suffix)].strip()
    return t


def _extract_expected_domain(item: dict) -> str:
    src_u = str(item.get("source_url") or "").strip()
    if src_u:
        try:
            host = urlparse(src_u).netloc.lower().split(":")[0]
            if host and "news.google" not in host:
                return host[4:] if host.startswith("www.") else host
        except Exception:
            pass
    return ""


def _hosts_match(candidate_url: str, expected_domain: str) -> bool:
    if not expected_domain:
        return False
    try:
        host = urlparse(candidate_url).netloc.lower().split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host == expected_domain or host.endswith(f".{expected_domain}") or expected_domain.endswith(f".{host}")
    except Exception:
        return False


def _score_search_candidate(
    clean_title: str,
    cand_title: str,
    cand_url: str,
    expected_domain: str,
    media_name: str,
) -> float:
    if not is_valid_decoded_url(cand_url):
        return -1.0
    a = clean_title.lower().strip()
    b = _clean_search_title(cand_title, media_name).lower().strip()
    if not a or not b:
        return -1.0
    r_full = fuzz.ratio(a, b)
    r_tok = fuzz.token_set_ratio(a, b)
    domain_ok = _hosts_match(cand_url, expected_domain)
    if domain_ok:
        if r_tok >= 72 or r_full >= 68:
            return float(r_full + 20)
        return -1.0
    # Tanpa kecocokan domain, syarat kemiripan judul dibuat ketat agar tidak salah artikel
    if r_full >= 88 or (r_tok >= 92 and len(a) >= 25):
        return float(r_full)
    return -1.0


def fallback_url_from_search(item: dict) -> tuple[str | None, str, str]:
    """Layer 3: mencari URL artikel asli melalui Serper.dev / Exa berdasarkan judul + nama sumber."""
    global _SERPER_EXHAUSTED, _EXA_EXHAUSTED
    if not isinstance(item, dict):
        return None, "", ""

    media_name = str(item.get("media_name") or item.get("source") or "").strip()
    clean_title = _clean_search_title(item.get("title", ""), media_name)
    if len(clean_title) < 12:
        return None, "", ""

    expected_domain = _extract_expected_domain(item)
    memo_key = (clean_title.lower(), expected_domain or media_name.lower())
    with _SEARCH_FALLBACK_LOCK:
        if memo_key in _SEARCH_FALLBACK_MEMO:
            return _SEARCH_FALLBACK_MEMO[memo_key]

    best_result: tuple[str | None, str, str] = (None, "", "")

    # 3A. Serper.dev (/search mendukung operator site:domain)
    serper_key = os.environ.get("SERPER_API_KEY", "").strip()
    if serper_key and not _SERPER_EXHAUSTED:
        try:
            q_str = f'"{clean_title}" site:{expected_domain}' if expected_domain else f'"{clean_title}" {media_name}'.strip()
            resp = requests.post(
                SERPER_SEARCH_URL,
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": q_str, "gl": "id", "hl": "id", "num": 5},
                timeout=12,
            )
            if resp.status_code in (402, 403):
                _SERPER_EXHAUSTED = True
                print(f"  [Fallback Serper] Kuota/key habis (HTTP {resp.status_code}), dinonaktifkan untuk sisa sesi.", flush=True)
            elif resp.status_code == 200:
                best_score = -1.0
                best_url = None
                for entry in resp.json().get("organic", []) or []:
                    cand_u = str(entry.get("link") or "").strip()
                    cand_t = str(entry.get("title") or "").strip()
                    sc = _score_search_candidate(clean_title, cand_t, cand_u, expected_domain, media_name)
                    if sc > best_score:
                        best_score = sc
                        best_url = cand_u
                if best_url:
                    best_result = (best_url, "fallback_serper", "")
        except Exception:
            pass

    # 3B. Exa Search fallback (juga menyertakan teks jika website sumber memblokir scraping langsung)
    exa_key = os.environ.get("EXA_API_KEY", "").strip()
    if not best_result[0] and exa_key and not _EXA_EXHAUSTED:
        try:
            payload: dict = {
                "query": clean_title if expected_domain else f"{clean_title} {media_name}".strip(),
                "type": "keyword",
                "category": "news",
                "numResults": 5,
                "contents": {"text": True},
            }
            if expected_domain:
                payload["includeDomains"] = [expected_domain]
            pub_ts = parse_to_wib(item.get("published"))
            if pub_ts is not None:
                d_day = pub_ts.date()
                payload["startPublishedDate"] = f"{(d_day - timedelta(days=2)).strftime('%Y-%m-%d')}T00:00:00.000Z"
                payload["endPublishedDate"] = f"{(d_day + timedelta(days=2)).strftime('%Y-%m-%d')}T23:59:59.999Z"

            resp = requests.post(
                EXA_SEARCH_URL,
                headers={"x-api-key": exa_key, "Content-Type": "application/json"},
                json=payload,
                timeout=15,
            )
            if resp.status_code in (402, 403):
                _EXA_EXHAUSTED = True
                print(f"  [Fallback Exa] Kuota/key habis (HTTP {resp.status_code}), dinonaktifkan untuk sisa sesi.", flush=True)
            elif resp.status_code == 200:
                best_score = -1.0
                best_url = None
                best_text = ""
                for entry in resp.json().get("results", []) or []:
                    cand_u = str(entry.get("url") or "").strip()
                    cand_t = str(entry.get("title") or "").strip()
                    sc = _score_search_candidate(clean_title, cand_t, cand_u, expected_domain, media_name)
                    if sc > best_score:
                        best_score = sc
                        best_url = cand_u
                        txt = str(entry.get("text") or "").strip()
                        best_text = txt[:8000] if len(txt) >= 300 else ""
                if best_url:
                    best_result = (best_url, "fallback_exa", best_text)
        except Exception:
            pass

    with _SEARCH_FALLBACK_LOCK:
        _SEARCH_FALLBACK_MEMO[memo_key] = best_result
    return best_result


def _resolve_gnews_local_only(
    url: str,
    min_interval: float | None = None,
    max_retries: int = 2,
    cache: DecodeCache | None = None,
    controller: AdaptiveDecodeController | None = None,
) -> tuple[str, str]:
    """Menjalankan Layer 1 (cache, decode offline v1, dan decode online GoogleDecoder dengan adaptive throttling)."""
    global _LOGGED_DECODE_WARNINGS
    if not url or "news.google.com" not in url:
        return url, "direct"

    cache = cache or get_decode_cache()
    controller = controller or get_decode_controller()

    cached = cache.get(url)
    if cached:
        return cached, "cache"

    offline = try_offline_base64_decode(url)
    if offline:
        cache.set(url, offline)
        return offline, "decode_offline"

    if _decoder_fn is None:
        return url, "failed"

    for attempt in range(max_retries + 1):
        allowed, _mode = controller.acquire_google_slot(min_interval_override=min_interval)
        if not allowed:
            return url, "circuit_skipped"

        try:
            res = _decoder_fn(url)
            if isinstance(res, dict):
                dec = str(res.get("decoded_url") or "").strip()
                if (res.get("status") or res.get("success")) and is_valid_decoded_url(dec):
                    controller.record_success()
                    cache.set(url, dec)
                    return dec, "decode_local"

                msg = str(res.get("message", ""))
                msg_low = msg.lower()
                if "sorry/index" in msg_low or "google.com/sorry" in msg_low:
                    raise GoogleCaptchaBlockedError(f"CAPTCHA gate terdeteksi ({msg[:120]}).")

                if _LOGGED_DECODE_WARNINGS < 5 and msg:
                    _LOGGED_DECODE_WARNINGS += 1
                    print(f"  [Decoder Warning] Gagal decode URL Google News: {msg[:150]}", flush=True)
            controller.record_failure()
        except GoogleCaptchaBlockedError:
            raise
        except Exception as e:
            if _LOGGED_DECODE_WARNINGS < 5:
                _LOGGED_DECODE_WARNINGS += 1
                print(f"  [Decoder Warning] Exception decode URL Google News: {e}", flush=True)
            controller.record_failure()

        if attempt < max_retries and controller.allow_google_decode():
            controller.sleep_backoff(attempt)
        elif not controller.allow_google_decode():
            break

    return url, "failed"


def resolve_article_with_fallback(
    item: dict,
    allow_search_fallback: bool = True,
    max_retries: int = 2,
    cache: DecodeCache | None = None,
    controller: AdaptiveDecodeController | None = None,
    search_fallback_fn=None,
) -> dict:
    """Resolusi URL Google News berlapis: (1) lokal, (2) metadata/RSS, (3) search Exa/Serper."""
    link = str(item.get("link") or item.get("Link Website") or "").strip()
    if not link or "news.google.com" not in link:
        return {
            "url": link,
            "resolved": bool(link),
            "method": "direct",
            "text": str(item.get("text") or ""),
        }

    cache = cache or get_decode_cache()
    controller = controller or get_decode_controller()

    dec_url, method = _resolve_gnews_local_only(
        link,
        max_retries=max_retries,
        cache=cache,
        controller=controller,
    )
    if method in ("cache", "decode_offline", "decode_local") and is_valid_decoded_url(dec_url):
        return {"url": dec_url, "resolved": True, "method": method, "text": ""}

    # Layer 2: metadata item / link RSS non-root
    meta_url = fallback_url_from_metadata(item)
    if meta_url:
        cache.set(link, meta_url)
        return {"url": meta_url, "resolved": True, "method": "fallback_meta", "text": ""}

    # Layer 3: fallback search (Serper / Exa) berdasar judul + media sumber
    if allow_search_fallback:
        s_fn = search_fallback_fn or fallback_url_from_search
        s_url, s_method, s_text = s_fn(item)
        if s_url and is_valid_decoded_url(s_url):
            cache.set(link, s_url)
            return {
                "url": s_url,
                "resolved": True,
                "method": s_method or "fallback_search",
                "text": s_text or "",
            }

    return {
        "url": link,
        "resolved": False,
        "method": "circuit_skipped" if method == "circuit_skipped" else "failed",
        "text": "",
    }


def resolve_article_url(url: str, min_interval: float = 0.4, max_retries: int = 2) -> str:
    """
    Menyelesaikan URL Google News (news.google.com/rss/articles/...)
    menjadi URL asli situs penerbit secara thread-safe, tahan rate limit, dengan cache persisten.
    """
    if not url or "news.google.com" not in url:
        return url
    resolved, _method = _resolve_gnews_local_only(
        url,
        min_interval=min_interval,
        max_retries=max_retries,
    )
    return resolved


def check_google_news_access(test_url: str | None = None) -> tuple[bool, str]:
    """
    Mengirim satu request test ringan untuk memastikan IP sudah tidak diblokir,
    SEBELUM menjalankan batch besar ke Google News RSS.
    Returns:
        (is_accessible: bool, message: str)
    """
    if _decoder_fn is None:
        return False, "Modul googlenewsdecoder tidak tersedia."

    if not test_url:
        import feedparser
        try:
            feed = feedparser.parse("https://news.google.com/rss/search?q=kopi&hl=id&gl=ID&ceid=ID:id")
            if not feed.entries:
                return False, "Gagal mengambil feed RSS Google News untuk pengetesan."
            test_url = feed.entries[0].link
        except Exception as e:
            return False, f"Gagal membaca RSS feed Google: {e}"

    try:
        res = _decoder_fn(test_url)
        if isinstance(res, dict):
            if (res.get("status") or res.get("success")) and res.get("decoded_url"):
                dec = res["decoded_url"]
                if "news.google.com" not in dec:
                    get_decode_cache().set(test_url, dec)
                    return True, f"Akses Google News bersih dan lancar. Target: {dec[:70]}"
            msg = str(res.get("message", ""))
            if "sorry/index" in msg or "429" in msg:
                return False, f"IP masih terblokir (429 / CAPTCHA Gate: {msg[:120]})"
            return False, f"Respon decoder tidak valid: {msg[:100]}"
    except Exception as e:
        return False, f"Error saat pengetesan koneksi: {e}"

    return False, "Status pengetesan tidak diketahui."


def is_suspiciously_short(text: str, min_length: int = 300) -> bool:
    """
    Memeriksa apakah hasil ekstraksi teks mencurigakan karena terlalu pendek (< 300 karakter).
    """
    if not text:
        return False
    return len(text.strip()) < min_length


def fetch_html_with_timeout(url: str, timeout: int = 8, max_retries: int = 1) -> str | None:
    """
    Fetch URL dengan timeout eksplisit dan retry.
    Mencegah proses hanging tanpa batas pada koneksi yang macet.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
            if resp.status_code == 200 and resp.text:
                return resp.text
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(0.5)
    return None


def fetch_gov_html_with_retry(url: str, max_retries: int = 2, timeout: int = 20) -> str | None:
    """Kompatibilitas: alias untuk fetch_html_with_timeout dengan timeout 20s."""
    return fetch_html_with_timeout(url, timeout=timeout, max_retries=max_retries)


def extract_article_text(url: str, max_length: int = 8000) -> str:
    """
    Mengekstrak teks isi berita dari URL.
    Menggunakan requests dengan strict timeout (12s untuk media, 20s untuk .go.id),
    diikuti parsing in-memory trafilatura dan newspaper3k tanpa second network request.
    """
    target_url = resolve_article_url(url)
    if not target_url or "news.google.com" in target_url:
        return ""

    # Router: jika URL adalah file PDF atau dari endpoint dokumen download,
    # blokir langsung (jangan diekstrak dan jangan proses OCR/pypdf)
    is_pdf_url = any(p in target_url.lower() for p in [".pdf", "/pdf/", "digivla.id", "/unduh/", "/download/"])
    if is_pdf_url:
        return ""

    raw_text = ""
    is_gov = ".go.id" in target_url.lower()
    req_timeout = 10 if is_gov else 8

    # Fetch HTML dengan strict timeout
    downloaded = fetch_html_with_timeout(target_url, timeout=req_timeout, max_retries=1)

    # Cek apakah response berupa file PDF biner (meski URL tidak berakhiran .pdf)
    if downloaded and downloaded.startswith("%PDF-"):
        return ""

    # 1. Ekstraksi utama dengan trafilatura (in-memory dari downloaded HTML)
    if downloaded:
        try:
            text = trafilatura.extract(downloaded, favor_precision=True)
            if text and text.strip():
                raw_text = text.strip()
        except Exception:
            pass

    # 2. Fallback dengan newspaper3k jika trafilatura kosong (in-memory tanpa network call baru)
    if not raw_text and downloaded:
        try:
            article = Article(target_url, language="id")
            article.set_html(downloaded)
            article.parse()
            if article.text and article.text.strip():
                raw_text = article.text.strip()
        except Exception:
            pass

    if not raw_text:
        return ""

    # 3. Content Length Cap (default 8000 karakter)
    if len(raw_text) > max_length:
        print(f"[WARNING] Konten artikel ({len(raw_text)} chars) melebihi batas {max_length}. Dipotong untuk URL: {target_url}")
        return raw_text[:max_length]

    return raw_text
