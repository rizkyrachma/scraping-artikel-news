"""
fetch_news.py
Pengambilan data Google News RSS feed, verifikasi denylist domain & ekstensi aset, serta deduplikasi artikel.
"""

import os
import json
import time
import random
import requests
from datetime import date, datetime
from urllib.parse import urlparse, parse_qs
import feedparser  # type: ignore

from query_builder import build_media_query, build_gov_query, build_rss_url
from config import (
    MARKETPLACE_BLOCKLIST,
    ASSET_HOST_BLOCKLIST,
    SOCIAL_MEDIA_BLOCKLIST,
    JOB_PORTAL_BLOCKLIST,
    ASSET_EXTENSION_BLOCKLIST,
    JOB_URL_PATTERNS,
    GOV_DOMAIN_SUFFIX,
    get_date_folder,
)
from relevance_filter import is_likely_relevant
from rapidfuzz import fuzz


class GoogleCaptchaBlockedError(Exception):
    """Exception khusus jika Google News mengalihkan ke CAPTCHA gate (google.com/sorry/index)."""
    pass


# 7. Header User-Agent standar browser dan Accept-Language id-ID (traffic menyerupai browser manusia)
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
}

_LAST_RSS_REQUEST_TIME = 0.0


def get_progress_filepath(target_date: date | None = None) -> str:
    """Mengembalikan path lengkap file progress.json di dalam folder tanggal yang sesuai."""
    folder = get_date_folder(target_date)
    return os.path.join(folder, "progress.json")


PROGRESS_FILE = os.path.join("hasil_scrapping", "progress.json")


# 5. Tes koneksi ringan sebelum mulai batch
def check_google_news_access() -> tuple[bool, str]:
    """
    Mengirim SATU request test ringan ke Google News RSS sebelum memulai batch.
    Jika status 429 atau dialihkan ke CAPTCHA gate (google.com/sorry/index), mengembalikan (False, pesan).
    Jika status 200 dan XML valid, mengembalikan (True, pesan sukses).
    HANYA dipanggil manual sebelum memulai sesi batch baru, BUKAN cron/otomatis berkala.
    """
    test_url = "https://news.google.com/rss/search?q=ekonomi&hl=id&gl=ID&ceid=ID:id"
    try:
        resp = requests.get(test_url, headers=BROWSER_HEADERS, timeout=15, allow_redirects=True)
        if "sorry/index" in resp.url or "google.com/sorry/index" in resp.text:
            return False, "Terdeteksi CAPTCHA gate (google.com/sorry/index). IP diblokir oleh Google."
        if resp.status_code == 429:
            return False, "HTTP 429 Too Many Requests terdeteksi dari Google News RSS."
        if resp.status_code == 200:
            feed = feedparser.parse(resp.content)
            if feed.entries:
                return True, f"Akses Google News RSS aman dan normal (HTTP 200, {len(feed.entries)} entri terbaca)."
            return True, "Akses Google News RSS terhubung normal (HTTP 200, feed kosong)."
        return False, f"Akses Google News RSS menghasilkan HTTP {resp.status_code}."
    except Exception as e:
        return False, f"Gagal menghubungi Google News RSS: {e}"


def determine_session_source(force_serper: bool = False, skip_check: bool = False) -> tuple[bool, str]:
    """
    Pengecekan status Google News RSS di setiap awal sesi baru (BUKAN polling berkala / cron):
    - Jika force_serper=True: Memaksa mode Serper.
    - Jika skip_check=True: Menggunakan status konfigurasi env saat ini.
    - Selain itu: Mengirim 1 request tes ringan via check_google_news_access().
      * Begitu RSS normal (HTTP 200), otomatis kembali pakai Google News RSS sebagai SUMBER UTAMA (USE_SERPER_ONLY=False).
      * Jika RSS terganggu (429/503/CAPTCHA), otomatis beralih ke Serper.dev sebagai CADANGAN DARURAT (USE_SERPER_ONLY=True).
    """
    if force_serper:
        os.environ["USE_SERPER_ONLY"] = "true"
        return True, "Mode Serper.dev dipaksa aktif via argumen --serper-only."

    if skip_check:
        is_serper = os.environ.get("USE_SERPER_ONLY", "false").lower() in ("true", "1", "yes")
        return is_serper, f"Pengecekan RSS awal sesi dilewati (Mode aktif: {'Serper.dev' if is_serper else 'Google News RSS'})."

    is_ok, msg = check_google_news_access()
    if is_ok:
        os.environ["USE_SERPER_ONLY"] = "false"
        return False, f"Akses RSS pulih/normal: {msg}. Otomatis kembali menggunakan Google News RSS sebagai SUMBER UTAMA (Serper = cadangan darurat)."
    else:
        os.environ["USE_SERPER_ONLY"] = "true"
        return True, f"Akses RSS terganggu: {msg}. Otomatis beralih menggunakan Serper.dev sebagai CADANGAN DARURAT untuk sesi ini."


# 2. Jeda antar-keyword
def sleep_between_keywords():
    """
    Jeda tambahan 10-15 detik (random.uniform(10, 15)) sebelum pindah ke keyword berikutnya.
    """
    delay = random.uniform(10.0, 15.0)
    print(f"  [Jeda Antar-Keyword] Istirahat {delay:.2f} detik sebelum keyword berikutnya...", flush=True)
    time.sleep(delay)


# 6. Checkpoint per keyword terorganisir per folder tanggal
def load_progress(target_date: date | None = None) -> dict:
    """Membaca progress.json per-tanggal jika ada, atau mengembalikan struktur awal."""
    pfile = get_progress_filepath(target_date)
    if os.path.exists(pfile):
        try:
            with open(pfile, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  [WARNING] Gagal membaca {pfile}: {e}", flush=True)
    return {
        "completed_keywords": [],
        "keyword_reports": {},
        "articles": [],
        "last_updated": None,
    }


def is_keyword_completed(keyword: str, target_date: date | None = None) -> bool:
    """Mengecek apakah keyword sudah tercatat selesai di progress.json tanggal tersebut."""
    prog = load_progress(target_date)
    target = keyword.strip().lower()
    return target in [k.strip().lower() for k in prog.get("completed_keywords", [])]


def save_keyword_progress(
    keyword: str,
    new_articles: list[dict],
    report_data: dict | None = None,
    target_date: date | None = None,
):
    """
    Menyimpan checkpoint progress setelah SATU keyword selesai ke folder tanggalnya:
    hasil_scrapping/<tanggal>/progress.json
    Deduplikasi artikel berbasis URL link dan update list completed_keywords secara aman.
    """
    pfile = get_progress_filepath(target_date)
    out_dir = os.path.dirname(pfile)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    prog = load_progress(target_date)
    completed = set(prog.get("completed_keywords", []))
    completed.add(keyword)
    prog["completed_keywords"] = sorted(list(completed))

    if report_data:
        if "keyword_reports" not in prog:
            prog["keyword_reports"] = {}
        prog["keyword_reports"][keyword] = report_data

    existing_articles = prog.get("articles", [])
    combined = existing_articles + new_articles
    prog["articles"] = dedup_by_link(combined)
    prog["last_updated"] = datetime.now().isoformat()

    tmp_file = f"{pfile}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(prog, f, indent=2, ensure_ascii=False)
    if os.path.exists(pfile):
        os.remove(pfile)
    os.rename(tmp_file, pfile)
    print(f"  [Checkpoint] Keyword '{keyword}' tersimpan di {pfile} (Total artikel unik: {len(prog['articles'])}).", flush=True)



# 1, 3, 4. Fetcher aman dengan jeda acak 3-5 detik, exponential backoff 429, dan deteksi CAPTCHA gate
def fetch_google_news_rss(url: str, keyword: str = "") -> feedparser.FeedParserDict:
    """
    Mengambil data RSS dari Google News dengan proteksi anti-CAPTCHA lengkap:
    - User-Agent standar browser & Accept-Language: id-ID
    - Deteksi instan CAPTCHA gate (google.com/sorry/index) -> raise GoogleCaptchaBlockedError (NO RETRY)
    - Exponential backoff untuk HTTP 429: [30s, 60s, 120s] maks 3 percobaan
    - Jeda dasar antar-request 3-5 detik (random.uniform(3, 5))
    """
    global _LAST_RSS_REQUEST_TIME

    # 1. Jeda dasar antar-request (random 3-5 detik)
    now = time.time()
    elapsed = now - _LAST_RSS_REQUEST_TIME
    needed_delay = random.uniform(3.0, 5.0)
    if elapsed < needed_delay:
        time.sleep(needed_delay - elapsed)

    backoff_delays = [30, 60, 120]
    max_retries = len(backoff_delays)

    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=25, allow_redirects=True)
            _LAST_RSS_REQUEST_TIME = time.time()

            # 4. Deteksi CAPTCHA gate (google.com/sorry/index)
            if "sorry/index" in resp.url or "google.com/sorry/index" in resp.text:
                print(f"\n[CRITICAL CAPTCHA GATE] Terdeteksi google.com/sorry/index pada query '{keyword}'!", flush=True)
                raise GoogleCaptchaBlockedError(f"Terdeteksi CAPTCHA gate (google.com/sorry/index) pada query '{keyword}'. IP diblokir.")

            # 3. Penanganan HTTP 429
            if resp.status_code == 429:
                if attempt < max_retries:
                    wait_time = backoff_delays[attempt]
                    print(f"  [HTTP 429] Rate limit saat query '{keyword}'. Menunggu {wait_time}s (Percobaan {attempt+1}/{max_retries})...", flush=True)
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  [GAGAL, DILEWATI] HTTP 429 berturut-turut pada query '{keyword}'. Dilewati.", flush=True)
                    return feedparser.FeedParserDict(entries=[])

            if resp.status_code == 200:
                if "sorry/index" in resp.text:
                    raise GoogleCaptchaBlockedError(f"Terdeteksi CAPTCHA gate dalam isi respons pada query '{keyword}'.")
                return feedparser.parse(resp.content)
            else:
                print(f"  [PERINGATAN] HTTP {resp.status_code} saat fetch RSS '{keyword}'.", flush=True)
                return feedparser.FeedParserDict(entries=[])

        except GoogleCaptchaBlockedError:
            raise
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                wait_time = backoff_delays[attempt]
                print(f"  [KONEKSI ERROR] {e}. Menunggu {wait_time}s (Percobaan {attempt+1}/{max_retries})...", flush=True)
                time.sleep(wait_time)
                continue
            else:
                print(f"  [GAGAL, DILEWATI] Gagal koneksi pada query '{keyword}': {e}. Dilewati.", flush=True)
                return feedparser.FeedParserDict(entries=[])
        finally:
            _LAST_RSS_REQUEST_TIME = time.time()

    return feedparser.FeedParserDict(entries=[])


def is_domain_in_blocklist(netloc: str, blocklist: list[str]) -> bool:
    """Mengecek apakah domain sama persis atau merupakan subdomain dari blocklist."""
    for domain in blocklist:
        d = domain.lower()
        if netloc == d or netloc.endswith(f".{d}"):
            return True
    return False


def is_valid_domain(url: str) -> bool:
    """
    Validasi domain dan ekstensi URL dengan strategi denylist-first:
    - Tolak jika path berakhiran ekstensi aset (ASSET_EXTENSION_BLOCKLIST)
    - Tolak jika URL mengandung pola URL lowongan kerja (JOB_URL_PATTERNS)
    - Domain .go.id otomatis lolos (jalur terpisah)
    - Tolak jika netloc match MARKETPLACE_BLOCKLIST, ASSET_HOST_BLOCKLIST, SOCIAL_MEDIA_BLOCKLIST, atau JOB_PORTAL_BLOCKLIST
    - Terima domain lainnya
    """
    if not url:
        return False

    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    full_url = url.lower()

    # 1. Tolak jika match ekstensi aset non-artikel (.pdf, .mp4, dll.)
    if any(path.endswith(ext.lower()) for ext in ASSET_EXTENSION_BLOCKLIST):
        return False

    # 2. Tolak pola path/URL lowongan kerja
    if any(p in full_url for p in JOB_URL_PATTERNS):
        return False

    # 3. Domain non-berita lokal (sekolah / desa)
    if netloc.endswith(".sch.id") or netloc.endswith(".desa.id"):
        return False

    # 4. Domain .go.id tetap otomatis lolos (jalur terpisah)
    if netloc.endswith(GOV_DOMAIN_SUFFIX) or f"{GOV_DOMAIN_SUFFIX}:" in netloc:
        return True

    # 4. Tolak jika domain atau subdomain match marketplace, host aset, media sosial, atau portal loker
    if is_domain_in_blocklist(netloc, MARKETPLACE_BLOCKLIST):
        return False
    if is_domain_in_blocklist(netloc, ASSET_HOST_BLOCKLIST):
        return False
    if is_domain_in_blocklist(netloc, SOCIAL_MEDIA_BLOCKLIST):
        return False
    if is_domain_in_blocklist(netloc, JOB_PORTAL_BLOCKLIST):
        return False

    # 5. Terima domain media apa pun yang tersisa
    return True


def clean_title_suffix(raw_title: str, source_title: str | None) -> str:
    """
    Menghapus suffix ' - <source_title>' dari judul mentah jika ada.
    Menggunakan pencocokan exact suffix berdasarkan entry.source.title dari feedparser,
    BUKAN split ' - ' membabi-buta, sehingga nama media yang mengandung tanda strip
    (contoh: 'DINAS PERPUSTAKAAN DAN KEARSIPAN - Kabupaten Sidoarjo') tidak terpotong keliru.
    """
    if not raw_title:
        return ""
    title = raw_title.strip()
    if source_title:
        clean_source = source_title.strip()
        suffix = f" - {clean_source}"
        while title.endswith(suffix) or title.lower().endswith(suffix.lower()):
            title = title[:-len(suffix)].strip()
    return title


_KEYWORD_GROUPS_CACHE: dict[str, list[str]] | None = None


def get_cached_keyword_groups() -> dict[str, list[str]]:
    """Mengambil cache grup keyword untuk mencegah re-read disk berulang."""
    global _KEYWORD_GROUPS_CACHE
    if _KEYWORD_GROUPS_CACHE is None:
        from config import build_keyword_groups
        _KEYWORD_GROUPS_CACHE = build_keyword_groups()
    return _KEYWORD_GROUPS_CACHE


def search_keyword(keyword: str | list[str], delay: float | None = None, target_date: date | None = None) -> list[dict]:
    """
    Mengambil berita untuk satu keyword atau grup keyword dari Google News RSS (media query dan gov query).
    Jika keyword berupa komoditas (misal 'gula'), otomatis digabungkan dengan variannya ('industri gula', 'industri gula rafinasi')
    menjadi SATU query OR: ("gula" OR "industri gula" OR "industri gula rafinasi").
    Jika keyword adalah 'pejabat_kemenperin', otomatis menggunakan 13 nama pejabat Kemenperin dalam 1 query OR.
    Menerapkan validasi domain, ekstraksi media_name, pembersihan title, serta filter relevansi.
    Proteksi jeda acak 3-5 detik otomatis diterapkan di fetch_google_news_rss.
    Jika target_date diberikan, menyertakan parameter after/before di query RSS untuk mencari tanggal spesifik.
    """
    results = []
    from datetime import timedelta
    from query_builder import format_keyword_query
    from config import get_officials_query_variants

    if isinstance(keyword, str) and keyword.lower() in ("pejabat_kemenperin", "pejabat kemenperin", "kemenperin_pejabat"):
        variants_list = get_officials_query_variants()
        base_label = "pejabat_kemenperin"
    elif isinstance(keyword, (list, tuple)):
        # Jika berupa list of list (chunks)
        if keyword and isinstance(keyword[0], (list, tuple)):
            variants_list = list(keyword)
            base_label = str(variants_list[0][0]) if variants_list[0] else "unknown"
        else:
            variants_list = [list(keyword)]
            base_label = str(keyword[0]) if keyword else "unknown"
    else:
        base_label = str(keyword).strip()
        groups = get_cached_keyword_groups()
        variants_list = [groups.get(base_label.lower(), [base_label])]

    for variants in variants_list:
        kw_expr = format_keyword_query(variants)
        query_kw = kw_expr
        if target_date is not None:
            from config import get_date_range
            start_d, end_d = get_date_range(target_date)
            prev_d = start_d - timedelta(days=1)
            next_d = end_d + timedelta(days=1)
            query_kw = f"{kw_expr} after:{prev_d.strftime('%Y-%m-%d')} before:{next_d.strftime('%Y-%m-%d')}"

        for query_fn in (build_media_query, build_gov_query):
            encoded = query_fn(query_kw)
            rss_url = build_rss_url(encoded)
            feed = fetch_google_news_rss(rss_url, keyword=base_label)

            for entry in feed.entries:
                link = entry.get("link", "")
                source_info = entry.get("source", {})
                source_href = source_info.get("href", "") if isinstance(source_info, dict) else ""
                raw_source_title = source_info.get("title") if isinstance(source_info, dict) else None
                source_title = str(raw_source_title).strip() if raw_source_title else None

                # 1. Validasi URL link dan URL domain asli penerbit
                if not is_valid_domain(link) or (source_href and not is_valid_domain(source_href)):
                    continue

                # 2. Bersihkan suffix nama media dari judul mentah
                raw_title = entry.get("title", "")
                clean_title = clean_title_suffix(raw_title, source_title)

                # 3. Filter relevansi berbasis judul (buang topik kesehatan/lifestyle murni)
                if not is_likely_relevant(clean_title):
                    continue

                results.append({
                    "keyword": base_label,
                    "title": clean_title,
                    "raw_title": raw_title,
                    "link": link,
                    "media_name": source_title,
                    "source": source_title or "",
                    "source_url": source_href,
                    "published": entry.get("published", ""),
                    "sumber_data": "RSS",
                })

    return results


def search_pejabat_presisi(
    pejabat_list: list[dict] | None = None,
    target_date: date | None = None,
    chunk_size: int = 4,
    use_serper: bool | None = None,
) -> list[dict]:
    """
    Melakukan pencarian presisi pejabat Kemenperin berbasis pemetaan pejabat_keyword_mapping.csv:
    Format query: ("Nama Pejabat") (keyword1 OR keyword2 OR ...) (site:... OR ...)
    Merupakan lapisan tambahan di atas pencarian institusi umum.
    Hanya menjalankan 9 pejabat Agro + Menteri/Wamen/Sekjen/Irjen (4 pejabat non-Agro dikecualikan).
    Tiap hasil ditandai dengan keyword 'pejabat_presisi' dan Terkait Kemenperin otomatis 'Ya'.
    Mendukung mode Serper.dev maupun Google News RSS.
    """
    from datetime import timedelta
    from config import load_pejabat_precision_mapping
    from query_builder import build_media_query, build_gov_query, build_rss_url

    if pejabat_list is None:
        pejabat_list = load_pejabat_precision_mapping(active_only=True)

    use_serper_active = (
        use_serper
        if use_serper is not None
        else (os.environ.get("USE_SERPER_ONLY", "false").lower() in ("true", "1", "yes"))
    )

    results = []
    seen_links = set()

    for p in pejabat_list:
        nama = p.get("nama", "").strip()
        keywords = p.get("keywords", [])
        if not keywords:
            continue

        # Alias nama pencarian efektif
        search_name = nama
        if "Muhammad Sarmuji" in nama or "Sarmuji" in nama:
            search_name = "Sarmuji"
        elif "Agus Gumiwang" in nama:
            search_name = "Agus Gumiwang"
        elif "Eko S.A. Cahyanto" in nama:
            search_name = "Eko Cahyanto"
        elif "Citra Rapati" in nama:
            search_name = "Citra Rapati"

        chunks = [keywords[i : i + chunk_size] for i in range(0, len(keywords), chunk_size)]
        for chunk in chunks:
            clean_chunk = [f'"{k}"' if not (k.startswith('"') and k.endswith('"')) else k for k in chunk]
            kw_or = " OR ".join(clean_chunk)
            base_kw_expr = f'"{search_name}" ({kw_or})'

            if use_serper_active:
                from serper_search import search_serper_news
                serper_items = search_serper_news(base_kw_expr, target_date=target_date)
                for item in serper_items:
                    link = item.get("link", "")
                    if not link or link in seen_links:
                        continue

                    source_title = item.get("source", "") or item.get("media_name", "")
                    raw_title = item.get("raw_title", "") or item.get("title", "")
                    clean_title = clean_title_suffix(raw_title, source_title)

                    if not is_likely_relevant(clean_title):
                        continue

                    seen_links.add(link)
                    matched_kws = [k for k in chunk if k.lower() in clean_title.lower()]
                    kw_label = f"{', '.join(matched_kws)}, pejabat_presisi" if matched_kws else "pejabat_presisi"

                    results.append({
                        "keyword": kw_label,
                        "title": clean_title,
                        "raw_title": raw_title,
                        "link": link,
                        "media_name": source_title,
                        "source": source_title or "",
                        "source_url": item.get("source_url", ""),
                        "published": item.get("published", ""),
                        "sumber_data": "Serper",
                        "terkait_kemenperin": "Ya",
                        "kemenperin_signal_type": "Pejabat Presisi",
                        "kemenperin_signal_detail": nama,
                    })
            else:
                query_kw = base_kw_expr
                if target_date is not None:
                    from config import get_date_range
                    start_d, end_d = get_date_range(target_date)
                    prev_d = start_d - timedelta(days=1)
                    next_d = end_d + timedelta(days=1)
                    query_kw = f"{base_kw_expr} after:{prev_d.strftime('%Y-%m-%d')} before:{next_d.strftime('%Y-%m-%d')}"

                for query_fn in (build_media_query, build_gov_query):
                    encoded = query_fn(query_kw)
                    rss_url = build_rss_url(encoded)
                    feed = fetch_google_news_rss(rss_url, keyword=f"presisi_{search_name}")

                    for entry in feed.entries:
                        link = entry.get("link", "")
                        if not link or link in seen_links:
                            continue

                        source_info = entry.get("source", {})
                        source_href = source_info.get("href", "") if isinstance(source_info, dict) else ""
                        raw_source_title = source_info.get("title") if isinstance(source_info, dict) else None
                        source_title = str(raw_source_title).strip() if raw_source_title else None

                        if not is_valid_domain(link) or (source_href and not is_valid_domain(source_href)):
                            continue

                        raw_title = entry.get("title", "")
                        clean_title = clean_title_suffix(raw_title, source_title)

                        if not is_likely_relevant(clean_title):
                            continue

                        seen_links.add(link)
                        matched_kws = [k for k in chunk if k.lower() in clean_title.lower()]
                        kw_label = f"{', '.join(matched_kws)}, pejabat_presisi" if matched_kws else "pejabat_presisi"

                        results.append({
                            "keyword": kw_label,
                            "title": clean_title,
                            "raw_title": raw_title,
                            "link": link,
                            "media_name": source_title,
                            "source": source_title or "",
                            "source_url": source_href,
                            "published": entry.get("published", ""),
                            "sumber_data": "RSS",
                            "terkait_kemenperin": "Ya",
                            "kemenperin_signal_type": "Pejabat Presisi",
                            "kemenperin_signal_detail": nama,
                        })

    return results



def merge_keywords(kw_a: str, kw_b: str) -> str:
    """
    Menggabungkan dua string keyword menjadi satu string terurut rapi dipisahkan koma,
    tanpa duplikasi kata (case-insensitive deduplication).
    Contoh: merge_keywords("gula", "kelapa") -> "gula, kelapa"
    """
    if not kw_a:
        return kw_b or ""
    if not kw_b:
        return kw_a or ""

    seen = set()
    result = []
    for part in f"{kw_a}, {kw_b}".split(","):
        k = part.strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            result.append(k)
    return ", ".join(result)


def dedup_by_link(items: list[dict]) -> list[dict]:
    """
    Deduplikasi hasil berdasarkan URL link (tanpa parameter query string).
    Jika URL sama ditemukan, gabungkan keyword-nya.
    """
    url_map = {}
    for item in items:
        raw_link = (
            item.get("link")
            or item.get("Link Website")
            or item.get("url")
            or item.get("resolved_url")
            or ""
        )
        if raw_link is None or (isinstance(raw_link, float) and str(raw_link) == "nan"):
            link = ""
        else:
            link = str(raw_link).strip()
            if link.lower() in ("nan", "none"):
                link = ""

        if "youtube.com/watch" in link.lower():
            parsed_u = urlparse(link)
            qs = parse_qs(parsed_u.query)
            vid = qs.get("v", [""])[0]
            key = f"https://www.youtube.com/watch?v={vid}" if vid else link
        elif "youtu.be/" in link.lower():
            key = link.split("?")[0].rstrip("/")
        else:
            key = link.split("?")[0].rstrip("/") if link else f"__no_link_{id(item)}__"
        if key not in url_map:
            url_map[key] = dict(item)
        else:
            existing_kw = url_map[key].get("keyword") or url_map[key].get("Keywords") or ""
            new_kw = item.get("keyword") or item.get("Keywords") or ""
            merged = merge_keywords(existing_kw, new_kw)
            url_map[key]["keyword"] = merged
            if "Keywords" in url_map[key]:
                url_map[key]["Keywords"] = merged
            # Jika salah satu sumber_data adalah RSS, prioritaskan label RSS
            if item.get("sumber_data") == "RSS" or url_map[key].get("sumber_data") == "RSS":
                url_map[key]["sumber_data"] = "RSS"
            elif not url_map[key].get("sumber_data") and item.get("sumber_data"):
                url_map[key]["sumber_data"] = item["sumber_data"]
    return list(url_map.values())


def is_near_duplicate_title(title_a: str, title_b: str, threshold: int = 85) -> bool:
    """
    Mengecek apakah dua judul artikel hampir duplikat menggunakan rapidfuzz.fuzz.ratio().
    Memeriksa kemiripan judul asli dan judul setelah dibersihkan dari suffix sumber berita (' - Media').
    Aman terhadap float / NaN / None.
    """
    if not title_a or not title_b or isinstance(title_a, float) or isinstance(title_b, float):
        return False

    str_a = str(title_a).strip()
    str_b = str(title_b).strip()
    if not str_a or not str_b or str_a.lower() in ("nan", "none") or str_b.lower() in ("nan", "none"):
        return False

    # 1. Kemiripan judul asli
    if fuzz.ratio(str_a.lower(), str_b.lower()) >= threshold:
        return True

    # 2. Kemiripan judul setelah strip nama penerbit Google News (" - <Media>")
    def clean(t: str) -> str:
        return t.rsplit(" - ", 1)[0].strip() if " - " in t else t.strip()

    if fuzz.ratio(clean(str_a).lower(), clean(str_b).lower()) >= threshold:
        return True

    return False


def clean_title_media_suffix(title: str) -> str:
    """Membersihkan suffix nama media penerbit Google News (' - <Media>') dari judul."""
    if not title or isinstance(title, float):
        return ""
    s = str(title).strip()
    return s.rsplit(" - ", 1)[0].strip() if " - " in s else s


def dedup_by_title(items: list[dict], threshold: int = 85) -> list[dict]:
    """
    Mengelompokkan artikel berbasis kemiripan judul (rapidfuzz >= threshold).
    Alih-alih membuang artikel sindikasi siaran pers, seluruh artikel TETAP DISIMPAN
    dan diberi nilai kolom 'Isu' yang sama (mengambil judul representasi dari artikel
    paling lengkap/panjang di grup tersebut).
    """
    if not items:
        return []

    clusters: list[list[dict]] = []

    for item in items:
        title = item.get("title") or item.get("Title") or ""
        matched_cluster_idx = -1

        for c_idx, cluster in enumerate(clusters):
            # Cek kecocokan kemiripan judul dengan representasi klaster
            rep_article = cluster[0]
            rep_title = rep_article.get("title") or rep_article.get("Title") or ""
            if is_near_duplicate_title(title, rep_title, threshold=threshold):
                matched_cluster_idx = c_idx
                break
            for existing in cluster[1:]:
                ex_title = existing.get("title") or existing.get("Title") or ""
                if is_near_duplicate_title(title, ex_title, threshold=threshold):
                    matched_cluster_idx = c_idx
                    break
            if matched_cluster_idx != -1:
                break

        item_copy = dict(item)
        if matched_cluster_idx == -1:
            clusters.append([item_copy])
        else:
            clusters[matched_cluster_idx].append(item_copy)

    # Untuk tiap klaster, tetapkan 'Isu' dari artikel paling lengkap (teks terpanjang)
    result: list[dict] = []
    for cluster in clusters:
        best_art = max(cluster, key=lambda a: len(str(a.get("text") or "")))
        best_title = best_art.get("title") or best_art.get("Title") or ""
        isu_name = clean_title_media_suffix(best_title) or best_title

        for art in cluster:
            art["Isu"] = isu_name
            art["isu"] = isu_name
            result.append(art)

    return result


def dedup_across_keywords(articles: list[dict], threshold: int = 85) -> list[dict]:
    """
    Deduplikasi komprehensif lintas keyword:
    1. Menggabungkan artikel dengan URL yang persis sama (strip query param), menggabungkan kolom keyword-nya.
    2. Mengelompokkan artikel dengan kemiripan judul >= threshold, mempertahankan seluruh baris,
       dan memberi nilai kolom 'Isu' yang seragam per kelompok sindikasi.
    """
    url_deduped = dedup_by_link(articles)
    return dedup_by_title(url_deduped, threshold=threshold)




def collect_all(keywords: list[str]) -> list[dict]:
    """
    Mengumpulkan dan menduplikasi hasil pencarian untuk seluruh daftar keyword
    dengan jeda antar-keyword 10-15 detik otomatis.
    """
    all_results = []
    for idx, kw in enumerate(keywords):
        if idx > 0:
            sleep_between_keywords()
        all_results.extend(search_keyword(kw))
    link_deduped = dedup_by_link(all_results)
    return dedup_by_title(link_deduped)

