"""
pdf_search.py
Modul pencarian dokumen dan kliping PDF publik via Google Dork (filetype:pdf) menggunakan Serper.dev API.
Mengintegrasikan pencarian PDF dengan filter tanggal (tbs), domain filter, dan ekstraksi otomatis via pdf_ocr.py.
"""

import os
import re
from datetime import date, datetime
from urllib.parse import urlparse
import requests

from config import load_env_file, get_date_range

load_env_file()

SERPER_SEARCH_URL = "https://google.serper.dev/search"

# Domain repositori skripsi/tugas akhir kampus yang sering menjadi noise pencarian dokumen industri
ACADEMIC_REPO_SUBDOMAINS = [
    "repo.", "repository.", "eprint.", "eprints.", "dspace.", "etd.", "digilib.",
    "jurnal.", "journal.", "ojs", "portalgaruda.", "garuda.", "neliti.",
    "scholar.", "academia.", "researchgate.", "sciencedirect.",
]

ACADEMIC_PATH_PATTERNS = [
    "/eprint/", "/eprints/", "/article/download/", "/bitstream/", "/handle/",
    "/thesis/", "/skripsi/", "/disertasi/", "/jurusan/",
]

MARKETPLACE_EXCLUDES = [
    "shopee.co.id", "tokopedia.com", "bukalapak.com", "lazada.co.id", "blibli.com",
]


def is_academic_repository(url: str) -> bool:
    """Mendeteksi apakah URL berasal dari repositori skripsi/tesis/jurnal mahasiswa kampus."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()

        # 1. Tolak seluruh domain universitas (.ac.id dan .edu) untuk pencarian dokumen PDF industri
        if netloc.endswith(".ac.id") or ".ac.id" in netloc or netloc.endswith(".edu"):
            return True

        # 2. Tolak subdomain repositori/jurnal akademik
        if any(netloc.startswith(prefix) or f".{prefix}" in netloc or prefix in netloc for prefix in ACADEMIC_REPO_SUBDOMAINS):
            return True

        # 3. Tolak pola path skripsi / eprint / download jurnal
        if any(p in path for p in ACADEMIC_PATH_PATTERNS):
            return True

        return False
    except Exception:
        return False


def build_pdf_dork_query(keyword: str) -> str:
    """
    Menyusun query pencarian Google Dork khusus file PDF industri Indonesia:
    q = "{keyword}" filetype:pdf (site:.co.id OR site:.id) -site:ac.id -site:shopee.co.id ...
    """
    clean_kw = keyword.strip()
    excludes = MARKETPLACE_EXCLUDES + ["ac.id"]
    excludes_str = " ".join([f"-site:{s}" for s in excludes])
    # Untuk 1 kata gunakan tanda kutip, untuk multi-kata gunakan pencocokan fleksibel
    kw_expr = f'"{clean_kw}"' if len(clean_kw.split()) == 1 else clean_kw
    query = f'{kw_expr} filetype:pdf (site:.co.id OR site:.id) {excludes_str}'
    return query


def search_pdf_documents(
    keyword: str,
    target_date: date | None = None,
    api_key: str | None = None,
    max_results: int = 10,
    include_academic: bool = False,
    timeout: int = 15,
) -> list[dict]:
    """
    Mencari dokumen PDF publik di Google via Serper.dev menggunakan dork filetype:pdf.
    CATATAN: Dokumen PDF telah dinonaktifkan / diblokir total sesuai instruksi.
    """
    return []

    if target_date is None:
        target_date, _ = get_date_range()

    query = build_pdf_dork_query(keyword)

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "q": query,
        "gl": "id",
        "hl": "id",
        "num": max_results,
    }

    # Atur filter rentang tanggal Google Search (tbs parameter)
    if target_date:
        m = target_date.month
        d = target_date.day
        y = target_date.year
        payload["tbs"] = f"cdr:1,cd_min:{m}/{d}/{y},cd_max:{m}/{d}/{y}"

    candidates = []
    try:
        resp = requests.post(SERPER_SEARCH_URL, headers=headers, json=payload, timeout=timeout)
        organic_items = []
        if resp.status_code == 200:
            organic_items = resp.json().get("organic", [])

        # Fallback jika pencarian single-day hari libur/Minggu kosong: coba filter 24 jam / 1 minggu
        if not organic_items and target_date:
            fallback_payload = dict(payload)
            fallback_payload["tbs"] = "qdr:w"
            fb_resp = requests.post(SERPER_SEARCH_URL, headers=headers, json=fallback_payload, timeout=timeout)
            if fb_resp.status_code == 200:
                organic_items = fb_resp.json().get("organic", [])

        if organic_items:
            for item in organic_items:
                link = item.get("link", "").strip()
                if not link:
                    continue

                # Filter repositori skripsi/tugas akhir mahasiswa jika tidak diizinkan
                if not include_academic and is_academic_repository(link):
                    continue

                # Bersihkan label [PDF] di judul
                raw_title = item.get("title", "")
                clean_title = re.sub(r"^\[PDF\]\s*", "", raw_title, flags=re.IGNORECASE).strip()

                parsed = urlparse(link)
                netloc = parsed.netloc

                # Ekstrak perkiraan waktu rilis atau fallback ke target_date
                pub_date = target_date.strftime("%Y-%m-%d 10:00:00") if target_date else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                candidates.append({
                    "title": clean_title,
                    "raw_title": raw_title,
                    "link": link,
                    "url": link,
                    "media_name": netloc,
                    "published": pub_date,
                    "keyword": keyword,
                    "sumber_data": "PDF",
                    "snippet": item.get("snippet", ""),
                })
        else:
            print(f"[PDF Search Warning] Serper HTTP {resp.status_code}: {resp.text[:150]}")
    except Exception as err:
        print(f"[PDF Search Error] Gagal melakukan pencarian PDF untuk '{keyword}': {err}")

    return candidates


if __name__ == "__main__":
    assert is_academic_repository("https://ojs3.unpatti.ac.id/index.php/pakem/article/download/26623/13377/") is True
    assert is_academic_repository("https://repo.ukitoraja.ac.id/id/eprint/1601/3/Bab%20II%20-%20Julsa%20Datu.pdf") is True
    assert is_academic_repository("https://kemenperin.go.id/download/123/siaran_pers.pdf") is False
    print("All pdf_search self-checks passed successfully!")
