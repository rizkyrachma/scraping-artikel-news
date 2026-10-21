"""
direct_crawl_agro.py
Modul penarik berita resmi dari portal Direktorat Jenderal Industri Agro,
Kementerian Perindustrian (https://agro.kemenperin.go.id).

Menyediakan:
1. fetch_agro_kemenperin(date_from, date_to, include_content=False) -> list[dict]
2. cocokkan_rilis_resmi(df, daftar_rilis_resmi, ambang=80) -> pd.DataFrame
3. integrate_agro_kemenperin_pipeline(df_or_articles, date_from, date_to, ...) -> pd.DataFrame
"""

import re
import time
import random
import logging
import urllib.parse
from datetime import datetime, date
import requests
from bs4 import BeautifulSoup
import urllib3
import pandas as pd
from rapidfuzz import fuzz

urllib3.disable_warnings()

logger = logging.getLogger("direct_crawl_agro")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

BASE_URL = "https://agro.kemenperin.go.id"
BERITA_URL = "https://agro.kemenperin.go.id/berita"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

INDONESIAN_MONTHS = {
    "januari": 1, "jan": 1,
    "februari": 2, "feb": 2,
    "maret": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "agustus": 8, "agu": 8, "ags": 8,
    "september": 9, "sep": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "desember": 12, "des": 12,
}


def parse_indonesian_date(date_str: str) -> datetime | None:
    """
    Mengurai format tanggal Indonesia, contoh: '01 Oktober 2026', 'Rabu, 7 Oktober 2026'.
    Mengembalikan objek datetime (pukul 00:00:00).
    """
    if not date_str:
        return None

    cleaned = date_str.strip().lower()
    # Hapus prefix nama hari jika ada, e.g., 'rabu, '
    cleaned = re.sub(r"^[a-z]+,\s*", "", cleaned)

    match = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", cleaned)
    if not match:
        return None

    day_s, month_s, year_s = match.groups()
    month_num = INDONESIAN_MONTHS.get(month_s)
    if not month_num:
        return None

    try:
        return datetime(int(year_s), month_num, int(day_s))
    except ValueError:
        return None


def normalize_url(raw_url: str | None, base: str = BASE_URL) -> str:
    """
    Menormalkan URL: membuat URL absolut, menghapus parameter tracking (utm_*), dan fragment (#).
    """
    if not raw_url:
        return ""

    abs_url = urllib.parse.urljoin(base, raw_url)
    parsed = urllib.parse.urlparse(abs_url)

    # Filter query parameters (buang semua utm_* dan parameter tracking)
    q_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_pairs = [
        (k, v) for k, v in q_pairs
        if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")
    ]
    new_query = urllib.parse.urlencode(filtered_pairs)

    clean_parsed = parsed._replace(query=new_query, fragment="")
    return urllib.parse.urlunparse(clean_parsed)


def fetch_with_retry(url: str, max_retries: int = 3, timeout: int = 20) -> str | None:
    """
    Mengambil isi teks halaman dengan retry exponential backoff dan timeout 20 detik.
    Jika error (timeout, 403, 404, situs down), mencatat log peringatan dan mengembalikan None.
    """
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, verify=False, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code in (404, 403):
                logger.warning(f"Gagal mengakses {url} (HTTP {resp.status_code}). Permintaan dihentikan.")
                return None
            else:
                logger.warning(f"HTTP {resp.status_code} saat mengakses {url} (percobaan {attempt}/{max_retries}).")
        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as err:
            logger.warning(f"Error jaringan/timeout saat mengakses {url}: {err} (percobaan {attempt}/{max_retries}).")

        if attempt < max_retries:
            backoff_sleep = 2 ** (attempt - 1)
            time.sleep(backoff_sleep)

    logger.warning(f"Gagal mengambil {url} setelah {max_retries} percobaan.")
    return None


def fetch_agro_kemenperin(
    date_from,
    date_to,
    include_content: bool = False,
    base_url: str = BERITA_URL
) -> list[dict]:
    """
    Mengambil berita resmi dari situs Ditjen Industri Agro (https://agro.kemenperin.go.id).

    Parameter:
    - date_from: datetime, date, atau string ISO ('YYYY-MM-DD') batas awal rentang tanggal.
    - date_to: datetime, date, atau string ISO ('YYYY-MM-DD') batas akhir rentang tanggal.
    - include_content: jika True, mengambil teks isi artikel pada halaman detail (maks 1000 karakter).
    - base_url: URL awal daftar berita (default: https://agro.kemenperin.go.id/berita).

    Ketentuan:
    - Setiap item berisi kunci:
      'Tanggal' (datetime), 'Title', 'Link Website' (URL absolut),
      'Media Name' = 'Kemenperin (agro.kemenperin.go.id)', 'Unit Eselon' = 'IA',
      'Terkait Kemenperin' = 'Ya', 'Sumber Data' = 'agro.kemenperin.go.id',
      'Status Review' = '', 'Keywords' = '', 'Tone' = '', 'Spokesperson 1' = '', 'Spokesperson 2' = ''.
    - Jika include_content=True, ditambahkan kunci 'isi' berisi teks artikel (maks. 1000 karakter).
    - Paginasi berhenti begitu ditemukan berita yang tanggalnya lebih lama dari date_from.
    - Menggunakan jeda 1-2 detik antar request dan retry maksimal 3 kali.
    - Menangani error secara aman tanpa crash: mencatat log peringatan dan mengembalikan list kosong.
    """
    if isinstance(date_from, (tuple, list)):
        if len(date_from) > 1:
            date_to = date_from[1]
        date_from = date_from[0]
    if isinstance(date_to, (tuple, list)):
        date_to = date_to[-1]

    def to_datetime(d):
        if isinstance(d, datetime):
            return datetime(d.year, d.month, d.day)
        elif isinstance(d, date):
            return datetime(d.year, d.month, d.day)
        elif isinstance(d, str):
            dt = datetime.strptime(d.strip(), "%Y-%m-%d")
            return datetime(dt.year, dt.month, dt.day)
        raise ValueError(f"Format tanggal tidak dikenali: {d}")

    try:
        dt_from = to_datetime(date_from)
        dt_to = to_datetime(date_to)
    except Exception as e:
        logger.warning(f"Error parsing rentang tanggal ({date_from} s.d. {date_to}): {e}")
        return []

    if dt_from > dt_to:
        dt_from, dt_to = dt_to, dt_from

    results = []
    page = 1
    seen_links = set()

    while True:
        page_url = f"{base_url}?page={page}" if page > 1 else base_url
        logger.info(f"Mengambil daftar berita agro.kemenperin.go.id: page {page} ({page_url})")

        # Jeda 1-2 detik antar request
        time.sleep(random.uniform(1.0, 2.0))

        html = fetch_with_retry(page_url, max_retries=3, timeout=20)
        if not html:
            logger.warning(f"Halaman {page_url} tidak dapat diambil. Menghentikan scraping.")
            break

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("div.article-item")
        if not items:
            logger.info(f"Tidak ada lagi article-item di halaman {page}. Selesai.")
            break

        stop_pagination = False

        for it in items:
            date_div = it.find(class_="article-date")
            date_str = date_div.get_text(strip=True) if date_div else ""
            pub_dt = parse_indonesian_date(date_str)
            if not pub_dt:
                continue

            # Paginasi berhenti begitu ditemukan berita yang tanggalnya lebih lama dari date_from
            if pub_dt < dt_from:
                logger.info(f"Ditemukan berita bertanggal {pub_dt.strftime('%d %B %Y')} (< {dt_from.strftime('%d %B %Y')}). Menghentikan paginasi.")
                stop_pagination = True
                break

            # Jika tanggal berita lebih baru dari date_to, lewati berita ini dan lanjutkan
            if pub_dt > dt_to:
                continue

            title_a = it.find("a", class_="article-title")
            if not title_a:
                continue

            title = title_a.get_text(strip=True)
            raw_href = str(title_a.get("href") or "")
            clean_link = normalize_url(raw_href, base=BASE_URL)

            if not clean_link or clean_link in seen_links:
                continue
            seen_links.add(clean_link)

            article_record = {
                "Tanggal": pub_dt,
                "Title": title,
                "Link Website": clean_link,
                "Media Name": "Kemenperin (agro.kemenperin.go.id)",
                "Tone": "",
                "Spokesperson 1": "",
                "Spokesperson 2": "",
                "Unit Eselon": "IA",
                "Terkait Kemenperin": "Ya",
                "Status Review": "",
                "Keywords": "",
                "Sumber Data": "agro.kemenperin.go.id",
            }

            if include_content:
                time.sleep(random.uniform(1.0, 1.5))
                detail_html = fetch_with_retry(clean_link, max_retries=3, timeout=20)
                isi_text = ""
                if detail_html:
                    detail_soup = BeautifulSoup(detail_html, "html.parser")
                    content_div = detail_soup.find("div", class_="article-content")
                    if content_div:
                        isi_text = content_div.get_text(separator="\n", strip=True)
                    else:
                        paras = detail_soup.find_all("p")
                        isi_text = "\n".join(p.get_text(strip=True) for p in paras if p.get_text(strip=True))

                # Potong maksimal 1000 karakter
                article_record["isi"] = isi_text[:1000]

            results.append(article_record)

        if stop_pagination:
            break

        next_page_link = soup.find("a", href=re.compile(rf"page={page + 1}"))
        if not next_page_link:
            break

        page += 1

    return results


def cocokkan_rilis_resmi(df: pd.DataFrame, daftar_rilis_resmi: list, ambang: int = 80) -> pd.DataFrame:
    """
    Melakukan verifikasi silang untuk berita media lain terhadap rilis resmi agro.kemenperin.go.id.
    - Membandingkan Title berita media lain dengan judul rilis resmi menggunakan rapidfuzz token_set_ratio.
    - Jika skor >= ambang: set Terkait Kemenperin = 'Ya' dan beri tanda kolom 'Cocok Rilis Resmi' = 'Ya'.
    - Tidak mengubah status relevan/buang dari Gemini untuk berita yang tidak cocok.
    - Tidak menimpa nilai Terkait Kemenperin yang sudah 'Ya'.
    """
    df_out = df.copy()

    official_titles = []
    for item in daftar_rilis_resmi:
        if isinstance(item, dict):
            t = item.get("Title") or item.get("title") or ""
        else:
            t = str(item)
        t_clean = t.strip()
        if t_clean:
            official_titles.append(t_clean)

    if "Cocok Rilis Resmi" not in df_out.columns:
        df_out["Cocok Rilis Resmi"] = ""

    if not official_titles:
        return df_out

    for idx in df_out.index:
        media_name = str(df_out.loc[idx, "Media Name"] if "Media Name" in df_out.columns else "").strip()
        if media_name == "Kemenperin (agro.kemenperin.go.id)":
            continue

        title = str(df_out.loc[idx, "Title"] if "Title" in df_out.columns else "").strip()
        if not title:
            continue

        best_score = 0
        for off_title in official_titles:
            score = fuzz.token_set_ratio(title, off_title)
            if score > best_score:
                best_score = score

        if best_score >= ambang:
            df_out.loc[idx, "Terkait Kemenperin"] = "Ya"
            df_out.loc[idx, "Cocok Rilis Resmi"] = "Ya"

    return df_out


def integrate_agro_kemenperin_pipeline(
    df_or_articles,
    date_from,
    date_to,
    include_content: bool = False,
    ambang_cocok: int = 80,
) -> pd.DataFrame:
    """
    Mengintegrasikan berita dari agro.kemenperin.go.id ke dalam dataset/DataFrame berita yang ada:
    1. Mengambil berita rilis resmi dari agro.kemenperin.go.id.
    2. Menggabungkan hasil ke DataFrame berita.
    3. Deduplikasi HANYA berdasarkan Link Website.
    4. Melakukan verifikasi silang dengan cocokkan_rilis_resmi.
    5. Mengurutkan hasil akhir berdasarkan Tanggal secara menurun (descending).
    """
    # 1. Fetch rilis resmi agro.kemenperin.go.id
    agro_items = fetch_agro_kemenperin(date_from=date_from, date_to=date_to, include_content=include_content)
    df_agro = pd.DataFrame(agro_items)

    # 2. Konversi dataset yang ada ke DataFrame
    if isinstance(df_or_articles, pd.DataFrame):
        df_base = df_or_articles.copy()
    elif isinstance(df_or_articles, list):
        df_base = pd.DataFrame(df_or_articles)
    else:
        df_base = pd.DataFrame()

    # 3. Gabungkan kedua DataFrame
    if not df_agro.empty and not df_base.empty:
        df_combined = pd.concat([df_base, df_agro], ignore_index=True)
    elif not df_agro.empty:
        df_combined = df_agro.copy()
    else:
        df_combined = df_base.copy()

    if df_combined.empty:
        return df_combined

    # 4. Deduplikasi HANYA berdasarkan Link Website (URL yang sama persis setelah normalisasi)
    df_deduped = df_combined.drop_duplicates(subset=["Link Website"], keep="first").reset_index(drop=True)

    # 5. Verifikasi silang judul media lain dengan rilis resmi agro.kemenperin.go.id
    if agro_items:
        df_deduped = cocokkan_rilis_resmi(df_deduped, agro_items, ambang=ambang_cocok)

    # 6. Urutkan berdasarkan Tanggal menurun
    if "Tanggal" in df_deduped.columns:
        # Konversi sementara ke datetime untuk pengurutan yang akurat
        df_deduped["_sort_dt"] = pd.to_datetime(df_deduped["Tanggal"], errors="coerce")
        df_deduped = df_deduped.sort_values(by="_sort_dt", ascending=False).drop(columns=["_sort_dt"]).reset_index(drop=True)

    return df_deduped
