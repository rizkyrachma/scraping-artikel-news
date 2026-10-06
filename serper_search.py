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


def search_serper_news(
    query: str,
    api_key: str | None = None,
    max_pages: int = 2,
    target_date: date | None = None,
) -> list[dict]:
    """
    Mencari berita via Serper.dev (https://google.serper.dev/news).
    Membersihkan operator 'site:' atau '-site:' jika ada, karena akun gratis Serper
    menolak dork query tersebut (HTTP 400). Penyaringan domain tetap dilakukan 100%
    secara presisi di kode Python via is_valid_domain().
    
    Mendukung ekspansi grup varian untuk komoditas dan 13 nama pejabat Kemenperin.
    Mendukung filter tanggal target YYYY-MM-DD via after/before operator.
    API key dibaca dari parameter atau environment variable 'SERPER_API_KEY'.
    Jika API key tidak ditemukan, fungsi nonaktif secara aman (skip, return [], tidak crash).
    """
    key = (api_key or os.environ.get("SERPER_API_KEY", "")).strip()
    if not key:
        return []

    import re
    from datetime import timedelta

    base_kw = query.strip()

    # Khusus pejabat Kemenperin umum: panggil chunk nama pejabat
    if base_kw.lower() in ("pejabat_kemenperin", "pejabat kemenperin", "kemenperin_pejabat"):
        from config import get_officials_query_variants
        chunks = get_officials_query_variants()
        all_res = []
        for chunk in chunks:
            q_chunk = "(" + " OR ".join(f'"{n}"' for n in chunk) + ")"
            sub_res = search_serper_news(q_chunk, api_key=key, max_pages=max_pages, target_date=target_date)
            for r in sub_res:
                r["keyword"] = "pejabat_kemenperin"
            all_res.extend(sub_res)
        return dedup_by_link(all_res)

    # Perluas query jika berupa kata dasar komoditas yang memiliki varian
    from config import build_keyword_groups
    groups = build_keyword_groups()
    if base_kw.lower() in groups and len(groups[base_kw.lower()]) > 1:
        variants = groups[base_kw.lower()]
        clean_q = "(" + " OR ".join(f'"{v}"' if ' ' in v else v for v in variants) + ")"
    else:
        # Bersihkan dork site: yang memicu HTTP 400 di Serper free account
        clean_q = re.sub(r"-?site:[^\s]+", "", base_kw)
        clean_q = " ".join(clean_q.split()).strip()
        if not clean_q:
            clean_q = base_kw

    # Sisipkan rentang tanggal target jika diberikan
    if target_date is not None:
        start_d, end_d = get_date_range(target_date)
        prev_d = start_d - timedelta(days=1)
        next_d = end_d + timedelta(days=1)
        clean_q = f"{clean_q} after:{prev_d.strftime('%Y-%m-%d')} before:{next_d.strftime('%Y-%m-%d')}"

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
            "keyword": base_kw,
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
