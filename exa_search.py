"""
exa_search.py
Integrasi pencarian berita menggunakan Exa Search API (https://api.exa.ai/search)
sebagai sumber PELENGKAP permanen untuk keyword satu kata dengan batasan domain Indonesia (.id / .co.id).
"""

import os
import time
import requests
from datetime import datetime, date, timedelta
from urllib.parse import urlparse

from config import get_date_range, is_published_yesterday
from fetch_news import is_valid_domain

EXA_SEARCH_URL = "https://api.exa.ai/search"


def is_allowed_id_domain(url: str) -> bool:
    """
    Hanya menerima URL yang berakhiran .id atau .co.id (case-insensitive).
    Semua domain lain (.com, .org, .co, .net, dll.) ditolak untuk membuang noise asing.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower().split(":")[0]
        return netloc.endswith(".id") or netloc.endswith(".co.id")
    except Exception:
        return False


def search_exa(
    query: str,
    api_key: str | None = None,
    start_published_date: str = "2026-09-13T17:00:00.000Z",
    end_published_date: str = "2026-09-14T23:59:59.999Z",
    search_type: str = "keyword",
    num_results: int = 25,
    timeout: int = 35,
    max_retries: int = 2,
) -> list[dict]:
    """
    Memanggil Exa Search API tingkat rendah dengan aturan ketat:
    - search_type: 'keyword' (lexical/literal match, BUKAN neural/deep agent, hemat kredit)
    - startPublishedDate & endPublishedDate: membatasi tanggal publikasi tepat pada hari evaluasi
    - contents: {"text": True} untuk ekstraksi isi teks langsung
    - num_results: 25 (optimal menghindari 504 gateway timeout pada backend Exa)
    """
    key = (api_key or os.environ.get("EXA_API_KEY", "")).strip()
    if not key:
        raise ValueError("EXA_API_KEY tidak ditemukan. Harap set environment variable EXA_API_KEY di file .env.")

    headers = {
        "x-api-key": key,
        "Content-Type": "application/json",
    }

    payload = {
        "query": query,
        "type": search_type,
        "category": "news",
        "startPublishedDate": start_published_date,
        "endPublishedDate": end_published_date,
        "numResults": num_results,
        "contents": {
            "text": True
        }
    }

    resp = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(EXA_SEARCH_URL, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                break
            elif resp.status_code == 504 and attempt < max_retries:
                time.sleep(2.0)
                continue
            else:
                raise RuntimeError(f"Exa API Error (HTTP {resp.status_code}): {resp.text}")
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                time.sleep(2.0)
                continue
            raise

    if resp is None or resp.status_code != 200:
        raise RuntimeError("Gagal mendapatkan respons dari Exa Search API setelah retry.")

    data = resp.json()
    results = data.get("results", [])

    articles = []
    for item in results:
        title = (item.get("title") or "").strip()
        link = (item.get("url") or "").strip()
        pub_date = item.get("publishedDate") or ""
        text = (item.get("text") or "").strip()

        parsed = urlparse(link)
        netloc = parsed.netloc.lower()
        media_name = netloc.replace("www.", "")

        articles.append({
            "title": title,
            "link": link,
            "published": pub_date,
            "text": text,
            "media_name": media_name,
            "author": item.get("author") or "",
        })

    return articles


def search_exa_news(
    keyword: str,
    api_key: str | None = None,
    target_date: date | None = None,
    max_results: int = 25,
) -> list[dict]:
    """
    Fungsi antarmuka utama pipeline untuk mencari berita pelengkap melalui Exa:
    - BUKAN Exa Agent/Deep Search (hemat kredit, mode keyword search)
    - Filter tanggal tepat 'kemarin' via parameter start/end published date Exa
    - WAJIB filter domain: hanya terima URL yang berakhiran .id atau .co.id
    - Mengembalikan format yang SAMA seperti fetch_news.py
    - Baca API key dari EXA_API_KEY (jika kosong, skip tanpa error)
    """
    key = (api_key or os.environ.get("EXA_API_KEY", "")).strip()
    if not key:
        return []

    eval_date = target_date if target_date is not None else get_date_range()[0]
    prev_day = eval_date - timedelta(days=1)
    start_utc = f"{prev_day.strftime('%Y-%m-%d')}T17:00:00.000Z"
    end_utc = f"{eval_date.strftime('%Y-%m-%d')}T23:59:59.999Z"

    try:
        raw_items = search_exa(
            query=keyword,
            api_key=key,
            start_published_date=start_utc,
            end_published_date=end_utc,
            search_type="keyword",
            num_results=max_results,
        )
    except Exception as e:
        print(f"      -> [Peringatan Exa] Gagal fetch: {e}")
        return []

    valid_results = []
    for item in raw_items:
        link = item.get("link", "").strip()
        pub = item.get("published", "")
        title = item.get("title", "").strip()
        text = item.get("text", "").strip()

        # 1. Filter domain: WAJIB berakhiran .id atau .co.id
        if not is_allowed_id_domain(link):
            continue

        # 2. Filter domain pipeline (marketplace, asset host, sosmed, loker)
        if not is_valid_domain(link):
            continue

        # 3. Filter tanggal publikasi tepat 'kemarin'
        if not is_published_yesterday(pub, target_date=eval_date):
            continue

        media_name = item.get("media_name", "")
        if not media_name:
            netloc = urlparse(link).netloc.lower().replace("www.", "")
            media_name = netloc

        valid_results.append({
            "title": title,
            "link": link,
            "media_name": media_name,
            "source": media_name,
            "source_url": link,
            "published": pub,
            "text": text,
            "sumber_data": "Exa",
            "keyword": keyword,
        })

    return valid_results
