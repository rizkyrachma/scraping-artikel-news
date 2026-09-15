"""
serper_search.py
Integrasi pencarian berita alternatif menggunakan API Serper.dev (https://google.serper.dev/news).
Digunakan saat Google News RSS terkena rate limit / CAPTCHA gate.
Mengembalikan format data yang identik dengan fetch_news.py sehingga kompatibel 100%
dengan seluruh pipeline NLP dan ekspor Excel.
"""

import os
import json
import requests
from urllib.parse import urlparse

from query_builder import build_media_query, build_gov_query
from config import (
    is_published_yesterday,
    get_date_range,
)
from fetch_news import (
    is_valid_domain,
    clean_title_suffix,
    dedup_by_link,
    dedup_by_title,
)
from relevance_filter import is_likely_relevant

SERPER_NEWS_URL = "https://google.serper.dev/news"


def search_serper_query(query: str, api_key: str, page: int = 1, timeout: int = 15) -> list[dict]:
    """
    Memanggil endpoint Serper.dev /news untuk satu query string dan nomor halaman.
    Mengembalikan list entri 'news' mentah dari respons Serper.
    """
    if not api_key:
        return []

    headers = {
        "X-API-KEY": api_key.strip(),
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "gl": "id",
        "hl": "id",
        "page": page,
    }

    try:
        resp = requests.post(SERPER_NEWS_URL, headers=headers, json=payload, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("news", [])
        elif resp.status_code == 403:
            print(f"[Serper Error] API Key tidak valid atau kuota habis (HTTP 403): {resp.text[:150]}")
            return []
        else:
            print(f"[Serper Warning] HTTP {resp.status_code}: {resp.text[:150]}")
            return []
    except Exception as e:
        print(f"[Serper Request Exception] Gagal menghubungi serper.dev: {e}")
        return []


def search_serper_news(query: str, api_key: str | None = None, max_pages: int = 2) -> list[dict]:
    """
    Mencari berita via Serper.dev (https://google.serper.dev/news).
    Membersihkan operator 'site:' atau '-site:' jika ada, karena akun gratis Serper
    menolak dork query tersebut (HTTP 400). Penyaringan domain tetap dilakukan 100%
    secara presisi di kode Python via is_valid_domain().
    
    API key dibaca dari parameter atau environment variable 'SERPER_API_KEY'.
    Jika API key tidak ditemukan, fungsi nonaktif secara aman (skip, return [], tidak crash).
    
    Mengembalikan format dict yang identik dengan fetch_news.py:
    - keyword
    - title
    - raw_title
    - link (DIRECT publisher URL, bukan token news.google.com!)
    - media_name
    - source
    - source_url
    - published
    """
    key = (api_key or os.environ.get("SERPER_API_KEY", "")).strip()
    if not key:
        return []

    import re
    # Bersihkan dork site: yang memicu HTTP 400 di Serper free account
    clean_q = re.sub(r"-?site:[^\s]+", "", query)
    clean_q = " ".join(clean_q.split()).strip()
    if not clean_q:
        clean_q = query.strip()

    raw_items = []
    for p in range(1, max_pages + 1):
        items = search_serper_query(clean_q, api_key=key, page=p)
        if not items:
            break
        raw_items.extend(items)

    results = []
    for item in raw_items:
        link = item.get("link", "").strip()
        raw_title = item.get("title", "").strip()
        source_title = item.get("source", "").strip() or None
        date_str = item.get("date", "").strip()

        # 1. Validasi domain & pola URL (exclude marketplace, media sosial, job portal, aset)
        if not is_valid_domain(link):
            continue

        # 2. Bersihkan suffix nama media dari judul
        clean_title = clean_title_suffix(raw_title, source_title)

        # 3. Filter relevansi judul
        if not is_likely_relevant(clean_title):
            continue

        results.append({
            "keyword": clean_q,
            "title": clean_title,
            "raw_title": raw_title,
            "link": link,
            "media_name": source_title or "",
            "source": source_title or "",
            "source_url": "",
            "published": date_str,
            "snippet": item.get("snippet", ""),
        })

    # Deduplikasi berbasis URL link
    return dedup_by_link(results)
