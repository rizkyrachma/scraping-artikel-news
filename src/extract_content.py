"""
extract_content.py
Ekstraksi isi/konten teks artikel berita menggunakan trafilatura dengan fallback newspaper3k.
Mendukung resolusi/dekoding URL Google News RSS, pembatasan panjang teks (capping), dan deteksi artikel pendek.
"""

import trafilatura
from newspaper import Article  # type: ignore

import threading
import time
import socket

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
            kw.setdefault("timeout", 6)
            kw.setdefault("headers", _DEFAULT_BROWSER_HEADERS)
            return _orig_get(*a, **kw)
        def _safe_post(*a, **kw):
            kw.setdefault("timeout", 6)
            return _orig_post(*a, **kw)
        g_req.get = _safe_get
        g_req.post = _safe_post
        g_req._patched_timeout = True
except ImportError:
    googlenewsdecoder = None
    _decoder_fn = None

try:
    from fetch_news import GoogleCaptchaBlockedError
except ImportError:
    class GoogleCaptchaBlockedError(Exception):
        """Exception khusus jika Google News mengalihkan ke CAPTCHA gate (google.com/sorry/index)."""
        pass


_DECODED_URL_CACHE: dict[str, str] = {}
_DECODER_LOCK = threading.Lock()
_LAST_DECODE_TIME = 0.0
_LOGGED_DECODE_ERROR = False


def resolve_article_url(url: str, min_interval: float = 0.4, max_retries: int = 1) -> str:
    """
    Menyelesaikan URL Google News (news.google.com/rss/articles/...)
    menjadi URL asli situs penerbit secara thread-safe, cepat, dan anti-hanging.
    """
    global _LAST_DECODE_TIME, _LOGGED_DECODE_ERROR
    if not url or "news.google.com" not in url or _decoder_fn is None:
        return url

    with _DECODER_LOCK:
        if url in _DECODED_URL_CACHE:
            return _DECODED_URL_CACHE[url]

    decoded = url
    for attempt in range(max_retries + 1):
        with _DECODER_LOCK:
            now = time.time()
            elapsed = now - _LAST_DECODE_TIME
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            _LAST_DECODE_TIME = time.time()

        try:
            res = _decoder_fn(url)
            if isinstance(res, dict):
                if (res.get("status") or res.get("success")) and res.get("decoded_url"):
                    decoded = res["decoded_url"]
                    break
                msg = str(res.get("message", ""))
                if "sorry/index" in msg or "sorry" in msg.lower():
                    raise GoogleCaptchaBlockedError(
                        f"CAPTCHA gate terdeteksi ({msg[:120]})."
                    )
                if not _LOGGED_DECODE_ERROR and msg:
                    _LOGGED_DECODE_ERROR = True
                    print(f"  [Decoder Warning] Gagal decode URL Google News: {msg[:150]}", flush=True)
                if attempt < max_retries and ("429" in msg or "failed" in msg.lower()):
                    time.sleep(1.5)
                    continue
        except GoogleCaptchaBlockedError:
            raise
        except Exception as e:
            if not _LOGGED_DECODE_ERROR:
                _LOGGED_DECODE_ERROR = True
                print(f"  [Decoder Warning] Exception decode URL Google News: {e}", flush=True)
        break

    with _DECODER_LOCK:
        _DECODED_URL_CACHE[url] = decoded
    return decoded


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


import time
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
