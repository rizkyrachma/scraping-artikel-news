"""
extract_content.py
Ekstraksi isi/konten teks artikel berita menggunakan trafilatura dengan fallback newspaper3k.
Mendukung resolusi/dekoding URL Google News RSS, pembatasan panjang teks (capping), dan deteksi artikel pendek.
"""

import trafilatura
from newspaper import Article  # type: ignore

try:
    import googlenewsdecoder  # type: ignore
except ImportError:
    googlenewsdecoder = None


def resolve_article_url(url: str) -> str:
    """
    Menyelesaikan URL Google News (news.google.com/rss/articles/...)
    menjadi URL asli situs penerbit.
    """
    if "news.google.com" in url and googlenewsdecoder is not None:
        try:
            res = googlenewsdecoder.new_decoderv1(url)
            if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
                return res["decoded_url"]
        except Exception:
            pass
    return url


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


def fetch_gov_html_with_retry(url: str, max_retries: int = 2, timeout: int = 20) -> str | None:
    """
    Fetch URL dengan timeout toleran (20s) dan retry khusus untuk domain .go.id
    yang sering mengalami latency atau SSL timeout.
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
                time.sleep(1)
    return None


def extract_article_text(url: str, max_length: int = 8000) -> str:
    """
    Mengekstrak teks isi berita dari URL.
    Menggunakan trafilatura sebagai parser utama, dan newspaper3k sebagai fallback.
    Memotong teks ke max_length karakter jika melebihi batas dan mencetak warning log.
    Menerapkan retry dengan timeout 20s khusus untuk domain .go.id.
    """
    target_url = resolve_article_url(url)
    raw_text = ""
    is_gov = ".go.id" in target_url.lower()

    downloaded = None
    # Khusus domain .go.id: coba fetch dengan requests retry timeout 20s terlebih dahulu
    if is_gov:
        downloaded = fetch_gov_html_with_retry(target_url, max_retries=2, timeout=20)

    # 1. Ekstraksi utama dengan trafilatura
    if not downloaded:
        try:
            downloaded = trafilatura.fetch_url(target_url)
        except Exception:
            pass

    if downloaded:
        try:
            text = trafilatura.extract(downloaded, favor_precision=True)
            if text and text.strip():
                raw_text = text.strip()
        except Exception:
            pass

    # 2. Fallback dengan newspaper3k jika trafilatura gagal / kosong
    if not raw_text:
        try:
            req_timeout = 20 if is_gov else 10
            article = Article(target_url, language="id", request_timeout=req_timeout)
            article.download()
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
