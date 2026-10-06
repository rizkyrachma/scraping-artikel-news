"""
run_all_batches.py
Menjalankan seluruh 46 keyword komoditas dari keyword_data.txt secara batch (5-6 keyword per sesi)
dengan proteksi anti-CAPTCHA lengkap, checkpoint per keyword ke progress.json, dan integrasi Exa.
"""

import os
import json
import time
import random
import argparse
from datetime import date
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    load_spokesperson_map,
    get_date_range,
    is_published_yesterday,
    is_single_word_keyword,
    get_date_folder,
    log_granular,
    start_heartbeat,
    format_display_url,
    load_pejabat_precision_mapping,
    INDUSTRY_EVENT_KEYWORDS,
    INSTITUTIONAL_KEYWORDS,
)
from fetch_news import (
    search_keyword,
    search_pejabat_presisi,
    dedup_by_link,
    dedup_by_title,
    dedup_across_keywords,
    check_google_news_access,
    determine_session_source,
    sleep_between_keywords,
    load_progress,
    is_keyword_completed,
    save_keyword_progress,
    GoogleCaptchaBlockedError,
    get_progress_filepath,
)
from exa_search import search_exa_news
from extract_content import extract_article_text, resolve_article_url
from main import filter_valid_articles, extract_one_article, extract_single_article_with_timer
from relevance_filter import get_kemenperin_signal, is_agro_relevant_content
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel
from serper_search import search_serper_news
from youtube_search import search_youtube_videos, get_kemenperin_channel_videos, get_youtube_quota_used
from pdf_search import search_pdf_documents
from pdf_ocr import process_pdf_input_folder
from direct_crawl_kemenperin import crawl_kemenperin_siaran_pers
from config import ENABLE_YOUTUBE

USE_SERPER_ONLY = os.environ.get("USE_SERPER_ONLY", "false").lower() in ("true", "1", "yes")

OUTPUT_DIR = "hasil_scrapping"
os.makedirs(OUTPUT_DIR, exist_ok=True)
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "batch_progress_checkpoint.json")

# 41 Keyword sisa yang belum dijalankan (di luar 5 keyword besar)
BATCHES = [
    ["mamin", "kelapa", "gula rafinasi", "tepung", "terigu"],
    ["tapioka", "sagu", "rumput laut", "alga", "spirulina"],
    ["olahan daging", "mi instan", "ikan kaleng", "makanan kemasan", "biskuit"],
    ["pulp", "mebel", "furniture", "atsiri", "karet"],
    ["kayu lapis", "hasil tembakau", "kakao", "cokelat", "minuman beralkohol"],
    ["minuman berpemanis", "nikotin", "tar", "teh", "susu"],
    ["amdk", "air minum dalam kemasan", "galon guna ulang", "kopi", "cpo"],
    ["minyak sawit", "pome", "fame", "biodiesel", "bioethanol", "pakan ternak"],
]

FIVE_BIG_KEYWORDS = [
    "industri agro", "makanan dan minuman", "sawit", "kertas",
    "djbc rokok ilegal", "rokok tanpa pita cukai", "bnn rokok elektrik",
]
ALL_46_KEYWORDS = [kw for b in BATCHES for kw in b] + FIVE_BIG_KEYWORDS
ALL_KEYWORDS = ALL_46_KEYWORDS

_EXTRACTED_CACHE: dict[str, dict] = {}


def get_cached_article(url: str) -> dict | None:
    if not url:
        return None
    key = str(url).strip().split("?")[0].rstrip("/").lower()
    return _EXTRACTED_CACHE.get(key)


def cache_article(art: dict) -> None:
    link = (art.get("link") or art.get("Link Website") or art.get("url") or art.get("resolved_url") or "").strip()
    text = str(art.get("text") or "").strip()
    if link and text and len(text) >= 300:
        key = str(link).split("?")[0].rstrip("/").lower()
        _EXTRACTED_CACHE[key] = {
            "text": text,
            "title": art.get("title") or art.get("Title") or "",
            "media_name": art.get("media_name") or art.get("Media Name") or "",
            "resolved_url": art.get("resolved_url") or link,
        }


def process_keyword(kw: str, name_map: dict, serper_only: bool = False, target_date: date | tuple | list | None = None) -> dict:
    """Memproses satu keyword dengan 6 sub-tahap granular, live extraction progress, dan timeout warning."""
    t_start = time.time()
    use_serper = serper_only or USE_SERPER_ONLY

    if target_date is None:
        target_date, _ = get_date_range()

    log_granular(f"  [>] Memproses keyword: '{kw}'...")

    # [1/6] Fetch RSS / Serper (media + gov)
    if use_serper:
        raw = search_serper_news(kw, target_date=target_date)
    else:
        raw = search_keyword(kw, target_date=target_date)
    mode_str = "Serper" if use_serper else "RSS (media + gov)"
    log_granular(f"     [1/6] Fetch {mode_str}...          -> selesai, {len(raw)} kandidat")

    for item in raw:
        if "sumber_data" not in item or not item["sumber_data"]:
            item["sumber_data"] = "Serper" if use_serper else "RSS"

    # [2/6] Fetch Exa (jika keyword 1 kata)
    if is_single_word_keyword(kw):
        exa_items = search_exa_news(kw, target_date=target_date)
        if exa_items:
            for item in exa_items:
                item["sumber_data"] = "Exa"
            log_granular(f"     [2/6] Fetch Exa (jika keyword 1 kata)...  -> selesai, {len(exa_items)} kandidat")
            raw = raw + exa_items
        else:
            log_granular(f"     [2/6] Fetch Exa (jika keyword 1 kata)...  -> selesai, 0 kandidat")
    else:
        log_granular(f"     [2/6] Fetch Exa (jika keyword 1 kata)...  -> dilewati (keyword > 1 kata)")

    # Fetch YouTube (1x per keyword, hemat kuota: 100 unit)
    if ENABLE_YOUTUBE:
        yt_items = search_youtube_videos(kw, target_date=target_date)
        if yt_items:
            log_granular(f"     [+] Fetch YouTube (search 1x)...          -> selesai, {len(yt_items)} video")
            raw = raw + yt_items
        else:
            log_granular(f"     [-] Fetch YouTube (search 1x)...          -> 0 video (atau API key kosong)")
    else:
        log_granular(f"     [-] Fetch YouTube (search 1x)...          -> dilewati (ENABLE_YOUTUBE=False)")

    # Fetch PDF Publik via Google Dork (filetype:pdf) - DIBLOKIR / DINONAKTIFKAN
    # Dokumen PDF tidak lagi diambil sesuai instruksi user
    # pdf_items = search_pdf_documents(kw, target_date=target_date, max_results=5)

    candidates = dedup_by_link(raw)
    initial_count = len(candidates)

    # [3/6] Filter tanggal kemarin
    yesterday_items = [c for c in candidates if is_published_yesterday(c.get("published", ""), target_date=target_date)]
    date_dropped = initial_count - len(yesterday_items)
    log_granular(f"     [3/6] Filter tanggal kemarin...            -> {len(yesterday_items)} lolos")

    # [4/6] Ekstraksi konten
    total_yest = len(yesterday_items)
    log_granular(f"     [4/6] Ekstraksi konten ({total_yest} artikel)...")
    extracted = []
    if yesterday_items:
        for it in yesterday_items:
            cached = get_cached_article(it.get("link", ""))
            if cached:
                it["text"] = cached["text"]
                if cached.get("resolved_url"):
                    it["resolved_url"] = cached["resolved_url"]

        workers = 8
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(extract_single_article_with_timer, item) for item in yesterday_items]
            completed = 0
            for f in as_completed(futures):
                completed += 1
                try:
                    res, disp_url = f.result(timeout=35)
                    extracted.append(res)
                    cache_article(res)
                except GoogleCaptchaBlockedError:
                    raise
                except Exception:
                    disp_url = "url"
                log_granular(f"       -> mengekstrak artikel {completed}/{total_yest}: {disp_url}")
    else:
        log_granular(f"       -> tidak ada artikel tanggal kemarin untuk diekstrak")

    # [5/6] Filter relevansi & dedup
    content_valid, discarded = filter_valid_articles(extracted, min_length=300, default_keyword=kw)
    log_granular(f"     [5/6] Filter relevansi & dedup...          -> {len(content_valid)} lolos")

    # [6/6] Sentiment & entity mapping
    kemenperin_yes = 0
    flagged = []
    for art in content_valid:
        title = art.get("title", "")
        text = art.get("text", "")
        # Jika sesi pejabat Kemenperin umum, buang topik non-agro untuk pejabat lintas-direktorat
        if kw == "pejabat_kemenperin":
            sp1_chk, _, _ = find_spokespersons(f"{title} {text}", name_map)
            is_spec_agro = (sp1_chk.lower() in {
                "putu juli ardika", "merrijantij punguan", "dyan garneta",
                "rr citra rapati", "krisna septiningrum",
            })
            if not is_spec_agro and not is_agro_relevant_content(title, text):
                continue

        is_rel, sig_type, sig_det = get_kemenperin_signal(title, text, name_map)
        item_copy = dict(art)
        item_copy["keyword"] = kw
        item_copy["terkait_kemenperin"] = "Ya" if is_rel else "Tidak"
        item_copy["kemenperin_signal_type"] = sig_type
        item_copy["kemenperin_signal_detail"] = sig_det
        flagged.append(item_copy)
        if is_rel:
            kemenperin_yes += 1

    log_granular(f"     [6/6] Sentiment & entity mapping...        -> selesai")
    duration = time.time() - t_start
    log_granular(f"   [OK] '{kw}' selesai: {len(content_valid)} artikel final. (durasi: {duration:.0f} detik)")


    return {
        "keyword": kw,
        "initial": initial_count,
        "date_valid": len(yesterday_items),
        "date_dropped": date_dropped,
        "final_valid": len(content_valid),
        "kemenperin_yes": kemenperin_yes,
        "kemenperin_no": len(content_valid) - kemenperin_yes,
        "articles": flagged,
    }


def process_pejabat_presisi(
    name_map: dict,
    target_date: date | None = None,
    specific_pejabat: list[dict] | None = None,
    serper_only: bool = False,
) -> dict:
    """
    Memproses sesi pencarian presisi pejabat Kemenperin berbasis pejabat_keyword_mapping.csv:
    1. Fetch Google News RSS / Serper per chunk (nama pejabat + OR kelompok komoditas)
    2. Filter tanggal publikasi kemarin / target_date
    3. Ekstraksi teks artikel
    4. Filter relevansi & panjang konten
    5. Sentiment classification & entity mapping
    Semua artikel otomatis ditandai keyword 'pejabat_presisi' dan Terkait Kemenperin = 'Ya'.
    """
    t_start = time.time()
    if target_date is None:
        target_date, _ = get_date_range()

    use_serper = serper_only or USE_SERPER_ONLY
    log_granular("  [>] Memproses Sesi Pencarian Presisi Pejabat Agro Kemenperin...")

    raw = search_pejabat_presisi(pejabat_list=specific_pejabat, target_date=target_date, use_serper=use_serper)
    mode_str = "Serper" if use_serper else "RSS"
    log_granular(f"     [1/5] Fetch {mode_str} Presisi...                -> selesai, {len(raw)} kandidat")

    candidates = dedup_by_link(raw)
    initial_count = len(candidates)

    yesterday_items = [c for c in candidates if is_published_yesterday(c.get("published", ""), target_date=target_date)]
    date_dropped = initial_count - len(yesterday_items)
    log_granular(f"     [2/5] Filter tanggal target...            -> {len(yesterday_items)} lolos")

    total_yest = len(yesterday_items)
    log_granular(f"     [3/5] Ekstraksi konten ({total_yest} artikel)...")
    extracted = []
    if yesterday_items:
        for it in yesterday_items:
            cached = get_cached_article(it.get("link", ""))
            if cached:
                it["text"] = cached["text"]
                if cached.get("resolved_url"):
                    it["resolved_url"] = cached["resolved_url"]

        workers = 8
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(extract_single_article_with_timer, item) for item in yesterday_items]
            completed = 0
            for f in as_completed(futures):
                completed += 1
                try:
                    res, disp_url = f.result(timeout=35)
                    extracted.append(res)
                    cache_article(res)
                except GoogleCaptchaBlockedError:
                    raise
                except Exception:
                    disp_url = "url"
                log_granular(f"       -> mengekstrak artikel {completed}/{total_yest}: {disp_url}")

    content_valid, discarded = filter_valid_articles(extracted, min_length=300, default_keyword="pejabat_presisi")
    log_granular(f"     [4/5] Filter relevansi & dedup...          -> {len(content_valid)} lolos")

    flagged = []
    for art in content_valid:
        title = art.get("title", "")
        text = art.get("text", "")
        sp1, sp2, unit = find_spokespersons(f"{title} {text}", name_map)
        is_spec_agro = (sp1.lower() in {
            "putu juli ardika", "merrijantij punguan", "dyan garneta",
            "rr citra rapati", "krisna septiningrum",
        })
        # Filter kedua: wajib substantif Agro jika bukan pejabat spesifik Ditjen Agro
        if not is_spec_agro and not is_agro_relevant_content(title, text):
            continue

        item_copy = dict(art)
        if "pejabat_presisi" not in item_copy.get("keyword", ""):
            item_copy["keyword"] = f"{item_copy.get('keyword', '')}, pejabat_presisi".strip(", ")
        item_copy["terkait_kemenperin"] = "Ya"
        item_copy["kemenperin_signal_type"] = "Pejabat Presisi"
        item_copy["kemenperin_signal_detail"] = art.get("kemenperin_signal_detail", sp1 or "Pejabat Kemenperin")
        item_copy["Spokesperson 1"] = sp1 or art.get("kemenperin_signal_detail", "")
        item_copy["Spokesperson 2"] = sp2
        item_copy["Unit Eselon"] = unit
        item_copy["Tone"] = classify_tone(art.get("text", ""), art.get("title", ""))
        flagged.append(item_copy)

    log_granular("     [5/5] Sentiment & entity mapping...        -> selesai")
    duration = time.time() - t_start
    log_granular(f"   [OK] Pejabat Presisi selesai: {len(content_valid)} artikel final. (durasi: {duration:.0f} detik)")

    return {
        "keyword": "pejabat_presisi",
        "initial": initial_count,
        "date_valid": len(yesterday_items),
        "date_dropped": date_dropped,
        "final_valid": len(content_valid),
        "kemenperin_yes": len(content_valid),
        "kemenperin_no": 0,
        "articles": flagged,
    }



def run_remaining_via_exa(
    remaining_keywords: list[str],
    name_map: dict,
    target_date: date | None = None,
) -> list[dict]:
    """Fallback otomatis jika CAPTCHA gate terdeteksi dan EXA_API_KEY tersedia."""
    print(f"\n" + "=" * 70)
    print(f"=== MENGALIHKAN SISA {len(remaining_keywords)} KEYWORD KE EXA SEARCH ===")
    print("=" * 70, flush=True)
    results = []
    for kw in remaining_keywords:
        if is_keyword_completed(kw, target_date=target_date):
            print(f"  [SKIP] Keyword '{kw}' sudah selesai di progress.json.", flush=True)
            continue

        print(f"  [Exa Fallback] Memproses keyword: '{kw}'...", flush=True)
        exa_items = search_exa_news(kw, target_date=target_date, max_results=25)
        yesterday_items = [c for c in exa_items if is_published_yesterday(c.get("published", ""), target_date=target_date)]

        extracted = []
        for item in yesterday_items:
            extracted.append(extract_one_article(item))

        content_valid, discarded = filter_valid_articles(extracted, min_length=300, default_keyword=kw)
        flagged = []
        kemenperin_yes = 0
        for art in content_valid:
            is_rel, sig_type, sig_det = get_kemenperin_signal(art["title"], art["text"], name_map)
            item_copy = dict(art)
            item_copy["keyword"] = kw
            item_copy["terkait_kemenperin"] = "Ya" if is_rel else "Tidak"
            item_copy["kemenperin_signal_type"] = sig_type
            item_copy["kemenperin_signal_detail"] = sig_det
            flagged.append(item_copy)
            if is_rel:
                kemenperin_yes += 1

        save_keyword_progress(
            kw,
            flagged,
            report_data={
                "initial": len(exa_items),
                "date_valid": len(yesterday_items),
                "final_valid": len(content_valid),
                "kemenperin_yes": kemenperin_yes,
                "kemenperin_no": len(content_valid) - kemenperin_yes,
                "source": "Exa_Fallback",
            },
            target_date=target_date,
        )
        results.extend(flagged)
        time.sleep(2.0)

    return results


def main():
    parser = argparse.ArgumentParser(description="Batch Scraping Runner dengan Proteksi Anti-CAPTCHA Lengkap")
    parser.add_argument("--serper-only", action="store_true", help="Pakai Serper.dev SAJA (bypass Google News RSS)")
    parser.add_argument("--api-key", type=str, default=None, help="Serper.dev API Key")
    parser.add_argument("--batches", type=str, default=None, help="Nomor batch yang ingin dijalankan (contoh: 1,2)")
    parser.add_argument("--batch-delay", type=float, default=None, help="Jeda antar-batch dalam detik (default: 25-35s)")
    parser.add_argument("--date", "--target-date", dest="target_date", type=str, default=None, help="Tanggal target evaluasi YYYY-MM-DD atau range YYYY-MM-DD:YYYY-MM-DD")
    parser.add_argument("--start-date", type=str, default=None, help="Tanggal awal rentang evaluasi YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default=None, help="Tanggal akhir rentang evaluasi YYYY-MM-DD")
    parser.add_argument("--skip-access-check", action="store_true", help="Lewati tes awal akses Google News")
    parser.add_argument("--force", action="store_true", help="Paksa jalankan ulang keyword meskipun sudah ada di progress.json")
    args = parser.parse_args()

    if args.api_key:
        os.environ["SERPER_API_KEY"] = args.api_key.strip()

    global USE_SERPER_ONLY
    USE_SERPER_ONLY, source_msg = determine_session_source(
        force_serper=args.serper_only,
        skip_check=args.skip_access_check,
    )

    from datetime import datetime
    if args.start_date and args.end_date:
        d1 = datetime.strptime(args.start_date.strip(), "%Y-%m-%d").date()
        d2 = datetime.strptime(args.end_date.strip(), "%Y-%m-%d").date()
        yesterday_date = (d1, d2)
    elif args.target_date:
        t_raw = args.target_date.strip()
        parsed_range = None
        for sep in [":", "..", "_sd_", "_to_", " to ", " - "]:
            if sep in t_raw:
                parts = t_raw.split(sep, 1)
                d1 = datetime.strptime(parts[0].strip(), "%Y-%m-%d").date()
                d2 = datetime.strptime(parts[1].strip(), "%Y-%m-%d").date()
                parsed_range = (d1, d2)
                break
        if parsed_range:
            yesterday_date = parsed_range
        else:
            yesterday_date = datetime.strptime(t_raw, "%Y-%m-%d").date()
    else:
        yesterday_date, _ = get_date_range()

    if isinstance(yesterday_date, (tuple, list)):
        d1, d2 = yesterday_date[0], yesterday_date[1]
        date_str = f"{d1.strftime('%Y-%m-%d')}_sd_{d2.strftime('%Y-%m-%d')}" if d1 != d2 else d1.strftime('%Y-%m-%d')
    else:
        date_str = yesterday_date.strftime("%Y-%m-%d")
    date_folder = get_date_folder(yesterday_date)

    print(f"================================================================================")
    print(f"=== BATCH SCRAPING 46 KEYWORD (MODE: {'SERPER.DEV CADANGAN' if USE_SERPER_ONLY else 'GOOGLE NEWS RSS + EXA'}) ===")
    print(f"================================================================================")
    print(f"Tanggal evaluasi : {yesterday_date}")
    print(f"Folder Output    : {date_folder}")
    name_map = load_spokesperson_map("keyword_nama.xlsx")
    print(f"Daftar Pejabat   : {len(name_map)} nama")
    print(f"Status Sumber    : {source_msg}\n")

    start_heartbeat()

    # Preload cache ekstraksi dari progress file yang ada agar URL yang pernah diekstrak tidak diulang
    for p_candidate in [
        os.path.join(date_folder, "progress.json"),
        "hasil_scrapping/2026-10-01_sd_2026-10-04/progress.json",
        "hasil_scrapping/2026-10-01/progress.json",
        "hasil_scrapping/2026-09-30/progress.json",
    ]:
        if os.path.exists(p_candidate):
            try:
                with open(p_candidate, "r", encoding="utf-8") as f:
                    p_data = json.load(f)
                    for a in p_data.get("articles", []):
                        cache_article(a)
            except Exception:
                pass
    if _EXTRACTED_CACHE:
        print(f"[Cache Preload] Siap menggunakan cache teks untuk {len(_EXTRACTED_CACHE)} URL.")

    # Seeding progress artikel awal jika range baru dibuat dan ada data dari 2026-10-01
    prog_file = get_progress_filepath(yesterday_date)
    if not os.path.exists(prog_file) and isinstance(yesterday_date, (tuple, list)):
        seed_source = "hasil_scrapping/2026-10-01/progress.json"
        if os.path.exists(seed_source):
            try:
                with open(seed_source, "r", encoding="utf-8") as f:
                    seed_data = json.load(f)
                seed_articles = seed_data.get("articles", [])
                if seed_articles:
                    initial_prog = {
                        "completed_keywords": [],
                        "keyword_reports": {},
                        "articles": seed_articles,
                        "last_updated": datetime.now().isoformat(),
                    }
                    os.makedirs(os.path.dirname(prog_file), exist_ok=True)
                    with open(prog_file, "w", encoding="utf-8") as f:
                        json.dump(initial_prog, f, indent=2, ensure_ascii=False)
                    print(f"[Seed Progress] Berhasil menyalin {len(seed_articles)} artikel tervalidasi dari 2026-10-01 ke {prog_file}")
            except Exception as e:
                print(f"[Warning] Gagal seeding progress: {e}")

    # 3. Cek apakah folder tanggal & progress.json sudah ada (lanjutkan, jangan timpa dari 0)
    prog = load_progress(yesterday_date)
    done_count = len(prog.get("completed_keywords", []))
    print(f"[Progress.json] Ditemukan di {date_folder}/progress.json: {done_count} keyword sudah selesai.")

    target_batch_indices = None
    if args.batches:
        try:
            target_batch_indices = [int(b.strip()) - 1 for b in args.batches.split(",") if b.strip()]
        except Exception as e:
            print(f"[Warning] Format --batches tidak valid: {e}")

    total_batches = len(BATCHES)

    for b_idx, kw_list in enumerate(BATCHES):
        b_num = b_idx + 1
        if target_batch_indices is not None and b_idx not in target_batch_indices:
            continue

        # Cek apakah seluruh keyword dalam batch sudah selesai
        if not args.force and all(is_keyword_completed(k, target_date=yesterday_date) for k in kw_list):
            print(f"[SKIP] Batch {b_num}/{total_batches} ({kw_list}) seluruhnya sudah selesai di {date_folder}.")
            continue

        print(f"\n" + "=" * 70)
        print(f"=== SESI BATCH {b_num}/{total_batches}: {kw_list} ===")
        print("=" * 70)

        captcha_triggered = False

        for kw_idx, kw in enumerate(kw_list):
            # 6. Checkpoint per keyword: lewati jika sudah ada
            if not args.force and is_keyword_completed(kw, target_date=yesterday_date):
                print(f"  [SKIP] Keyword '{kw}' sudah selesai di {date_folder}/progress.json.", flush=True)
                continue

            # 2. Jeda antar-keyword (10-15 detik)
            if kw_idx > 0 or b_idx > 0:
                if USE_SERPER_ONLY:
                    time.sleep(1.0)
                else:
                    sleep_between_keywords()

            try:
                res = process_keyword(kw, name_map, target_date=yesterday_date)
                # 6. Simpan checkpoint seketika setelah 1 keyword selesai
                save_keyword_progress(
                    kw,
                    res["articles"],
                    report_data={
                        "initial": res["initial"],
                        "date_valid": res["date_valid"],
                        "final_valid": res["final_valid"],
                        "kemenperin_yes": res["kemenperin_yes"],
                        "kemenperin_no": res["kemenperin_no"],
                    },
                    target_date=yesterday_date,
                )
            except GoogleCaptchaBlockedError as c_err:
                print(f"\n[CRITICAL CAPTCHA GATE] {c_err}", flush=True)
                print(f"  a. Menghentikan request Google News RSS seketika (NO RETRY).", flush=True)
                print(f"  b. Checkpoint progres tersimpan aman di {date_folder}/progress.json.", flush=True)

                exa_key = os.environ.get("EXA_API_KEY", "").strip()
                if exa_key:
                    print(f"  c. EXA_API_KEY terdeteksi! Mengalihkan sisa keyword ke Exa Search...", flush=True)
                    rem_kws = [k for k in ALL_46_KEYWORDS if not is_keyword_completed(k, target_date=yesterday_date)]
                    run_remaining_via_exa(rem_kws, name_map, target_date=yesterday_date)
                else:
                    print(f"  d. EXA_API_KEY tidak diset. Menghentikan proses total untuk dilaporkan ke user.", flush=True)
                captcha_triggered = True
                break

        if captcha_triggered:
            break

        # 8. Batasi 5-6 keyword per sesi eksekusi
        if b_idx < total_batches - 1 and (target_batch_indices is None or (b_idx + 1) in target_batch_indices):
            session_delay = args.batch_delay if args.batch_delay is not None else (1.0 if USE_SERPER_ONLY else random.uniform(25.0, 35.0))
            print(f"\n[Jeda Antar-Sesi] Menunggu jeda aman {session_delay:.1f} detik sebelum batch berikutnya...", flush=True)
            time.sleep(session_delay)

    # Proses 5 Keyword Besar jika tidak ada batasan batch atau eksplisit diminta
    run_five_big = (target_batch_indices is None) or ("big" in (args.batches or "").lower()) or ("9" in (args.batches or ""))
    if run_five_big and (args.force or not all(is_keyword_completed(k, target_date=yesterday_date) for k in FIVE_BIG_KEYWORDS)):
        print(f"\n" + "=" * 70)
        print(f"=== SESI 5 KEYWORD BESAR: {FIVE_BIG_KEYWORDS} ===")
        print("=" * 70)
        for kw_idx, kw in enumerate(FIVE_BIG_KEYWORDS):
            if not args.force and is_keyword_completed(kw, target_date=yesterday_date):
                print(f"  [SKIP] Keyword 5 besar '{kw}' sudah selesai di {date_folder}/progress.json.", flush=True)
                continue

            if not USE_SERPER_ONLY:
                sleep_between_keywords()

            try:
                res = process_keyword(kw, name_map, target_date=yesterday_date)
                save_keyword_progress(
                    kw,
                    res["articles"],
                    report_data={
                        "initial": res["initial"],
                        "date_valid": res["date_valid"],
                        "final_valid": res["final_valid"],
                        "kemenperin_yes": res["kemenperin_yes"],
                        "kemenperin_no": res["kemenperin_no"],
                    },
                    target_date=yesterday_date,
                )
            except GoogleCaptchaBlockedError as c_err:
                print(f"\n[CRITICAL CAPTCHA GATE] {c_err}", flush=True)
                exa_key = os.environ.get("EXA_API_KEY", "").strip()
                if exa_key:
                    print(f"  c. EXA_API_KEY terdeteksi! Mengalihkan sisa keyword ke Exa Search...", flush=True)
                    rem_kws = [k for k in ALL_46_KEYWORDS if not is_keyword_completed(k, target_date=yesterday_date)]
                    run_remaining_via_exa(rem_kws, name_map, target_date=yesterday_date)
                else:
                    print(f"  d. EXA_API_KEY tidak diset. Menghentikan proses total.", flush=True)
                break

    # Sesi Pencarian Nama Pejabat Kemenperin (13 Pejabat OR Query)
    run_officials = (target_batch_indices is None) or ("pejabat" in (args.batches or "").lower())
    if run_officials and (args.force or not is_keyword_completed("pejabat_kemenperin", target_date=yesterday_date)):
        print(f"\n" + "=" * 70)
        print("=== SESI PENCARIAN 13 NAMA PEJABAT KEMENPERIN (OR QUERY) ===")
        print("=" * 70)
        if not USE_SERPER_ONLY:
            sleep_between_keywords()

        try:
            res = process_keyword("pejabat_kemenperin", name_map, target_date=yesterday_date)
            save_keyword_progress(
                "pejabat_kemenperin",
                res["articles"],
                report_data={
                    "initial": res["initial"],
                    "date_valid": res["date_valid"],
                    "final_valid": res["final_valid"],
                    "kemenperin_yes": res["kemenperin_yes"],
                    "kemenperin_no": res["kemenperin_no"],
                },
                target_date=yesterday_date,
            )
        except GoogleCaptchaBlockedError as c_err:
            print(f"\n[CRITICAL CAPTCHA GATE] {c_err}", flush=True)
            exa_key = os.environ.get("EXA_API_KEY", "").strip()
            if exa_key:
                print(f"  c. Mengalihkan sisa keyword ke Exa Search...", flush=True)
                run_remaining_via_exa(["pejabat_kemenperin"], name_map, target_date=yesterday_date)

    # Sesi Pencarian Presisi Pejabat Agro Kemenperin (9 Pejabat Terkait Agro)
    run_presisi = (target_batch_indices is None) or ("presisi" in (args.batches or "").lower()) or ("pejabat" in (args.batches or "").lower())
    if run_presisi and (args.force or not is_keyword_completed("pejabat_presisi", target_date=yesterday_date)):
        print(f"\n" + "=" * 70)
        print("=== SESI PENCARIAN PRESISI 9 PEJABAT AGRO (NAMA + KOMODITAS AGRO OR QUERY) ===")
        print("=" * 70)
        if not USE_SERPER_ONLY:
            sleep_between_keywords()

        selected_pejabat = load_pejabat_precision_mapping(active_only=True)
        print(f"Pejabat presisi yang dijalankan ({len(selected_pejabat)} orang): {', '.join([p['nama'] for p in selected_pejabat])}")

        try:
            res_p = process_pejabat_presisi(
                name_map,
                target_date=yesterday_date,
                specific_pejabat=selected_pejabat,
                serper_only=USE_SERPER_ONLY,
            )
            save_keyword_progress(
                "pejabat_presisi",
                res_p["articles"],
                report_data={
                    "initial": res_p["initial"],
                    "date_valid": res_p["date_valid"],
                    "final_valid": res_p["final_valid"],
                    "kemenperin_yes": res_p["kemenperin_yes"],
                    "kemenperin_no": res_p["kemenperin_no"],
                },
                target_date=yesterday_date,
            )
        except GoogleCaptchaBlockedError as c_err:
            print(f"\n[CRITICAL CAPTCHA GATE] {c_err}", flush=True)

    # Sesi Pencarian Event & Pameran Industri Agro Tahunan
    run_events = (target_batch_indices is None) or ("event" in (args.batches or "").lower()) or ("pameran" in (args.batches or "").lower())
    if run_events:
        print("\n" + "=" * 70)
        print("=== SESI PENCARIAN EVENT & PAMERAN INDUSTRI AGRO TAHUNAN ===")
        print("=" * 70)
        for ev_kw in INDUSTRY_EVENT_KEYWORDS:
            if args.force or not is_keyword_completed(ev_kw, target_date=yesterday_date):
                print(f"\n[EVENT] Memproses keyword event: '{ev_kw}'...")
                if not USE_SERPER_ONLY:
                    sleep_between_keywords()
                try:
                    res_ev = process_keyword(ev_kw, name_map, target_date=yesterday_date)
                    save_keyword_progress(
                        ev_kw,
                        res_ev["articles"],
                        report_data={
                            "initial": res_ev["initial"],
                            "date_valid": res_ev["date_valid"],
                            "final_valid": res_ev["final_valid"],
                            "kemenperin_yes": res_ev["kemenperin_yes"],
                            "kemenperin_no": res_ev["kemenperin_no"],
                        },
                        target_date=yesterday_date,
                    )
                except GoogleCaptchaBlockedError as c_err:
                    print(f"\n[CRITICAL CAPTCHA GATE] {c_err}", flush=True)
                    break

    # Sesi Pencarian Institusi Khusus Kemenperin (Akademi Komunitas Bambu, dll. - Frasa Langsung)
    run_institusi = (target_batch_indices is None) or ("institusi" in (args.batches or "").lower()) or ("bambu" in (args.batches or "").lower())
    if run_institusi:
        print("\n" + "=" * 70)
        print("=== SESI PENCARIAN INSTITUSI KHUSUS KEMENPERIN (FRASA LANGSUNG) ===")
        print("=" * 70)
        for inst_kw in INSTITUTIONAL_KEYWORDS:
            if args.force or not is_keyword_completed(inst_kw, target_date=yesterday_date):
                print(f"\n[INSTITUSI] Memproses keyword institusi: '{inst_kw}'...")
                if not USE_SERPER_ONLY:
                    sleep_between_keywords()
                try:
                    res_inst = process_keyword(inst_kw, name_map, target_date=yesterday_date)
                    save_keyword_progress(
                        inst_kw,
                        res_inst["articles"],
                        report_data={
                            "initial": res_inst["initial"],
                            "date_valid": res_inst["date_valid"],
                            "final_valid": res_inst["final_valid"],
                            "kemenperin_yes": res_inst["kemenperin_yes"],
                            "kemenperin_no": res_inst["kemenperin_no"],
                        },
                        target_date=yesterday_date,
                    )
                except GoogleCaptchaBlockedError as c_err:
                    print(f"\n[CRITICAL CAPTCHA GATE] {c_err}", flush=True)
                    break

    # Direct Pull 2 Channel Resmi Kemenperin & Ditjen Agro
    if ENABLE_YOUTUBE:
        print("\n" + "=" * 70)
        print("=== DIRECT PULL 2 CHANNEL RESMI KEMENPERIN & DITJEN AGRO (2 UNIT KUOTA) ===")
        print("=" * 70)
        ch_videos = get_kemenperin_channel_videos(target_date=yesterday_date)
        print(f"Total video resmi diupload pada {yesterday_date}: {len(ch_videos)} video")
        if ch_videos:
            ch_valid, _ = filter_valid_articles(ch_videos, min_length=300, default_keyword="kemenperin_institusi")
            ch_flagged = []
            for v in ch_valid:
                title = v.get("title", "")
                text = v.get("text", "")
                if not is_agro_relevant_content(title, text):
                    continue
                sp1, sp2, unit = find_spokespersons(f"{title} {text}", name_map)
                tone = classify_tone(text, title)
                v_copy = dict(v)
                v_copy["tone"] = tone
                v_copy["spokesperson_1"] = sp1 or ""
                v_copy["spokesperson_2"] = sp2 or ""
                v_copy["unit_eselon"] = unit or "-"
                v_copy["terkait_kemenperin"] = "Ya"
                v_copy["kemenperin_signal_type"] = "Official Channel"
                v_copy["kemenperin_signal_detail"] = v.get("media_name", "Kemenperin")
                v_copy["keyword"] = "kemenperin_institusi"
                v_copy["sumber_data"] = "YouTube"
                ch_flagged.append(v_copy)

            if ch_flagged:
                save_keyword_progress(
                    "kemenperin_official_channel",
                    ch_flagged,
                    report_data={
                        "initial": len(ch_videos),
                        "date_valid": len(ch_videos),
                        "final_valid": len(ch_flagged),
                        "kemenperin_yes": len(ch_flagged),
                        "kemenperin_no": 0,
                        "source": "YouTube_Official_Channel",
                    },
                    target_date=yesterday_date,
                )
                print(f"[+] Berhasil menambahkan {len(ch_flagged)} video resmi ke checkpoint progres.")
    else:
        print("\n[-] YouTube dinonaktifkan sementara (ENABLE_YOUTUBE=False), skip Direct Pull Channel Resmi.")

    # Direct Crawl Siaran Pers kemenperin.go.id
    print("\n" + "=" * 70)
    print("=== DIRECT CRAWL SIARAN PERS KEMENPERIN.GO.ID ===")
    print("=" * 70)
    crawl_items = crawl_kemenperin_siaran_pers(target_date=yesterday_date, max_pages=3)
    print(f"Total siaran pers kemenperin.go.id pada {yesterday_date}: {len(crawl_items)} artikel")
    if crawl_items:
        crawl_valid, _ = filter_valid_articles(crawl_items, min_length=200, default_keyword="kemenperin_institusi")
        crawl_flagged = []
        for a in crawl_valid:
            title = a.get("title", "")
            text = a.get("text", "")
            if not is_agro_relevant_content(title, text):
                continue
            sp1, sp2, unit = find_spokespersons(f"{title} {text}", name_map)
            tone = classify_tone(text, title)
            a_copy = dict(a)
            a_copy["tone"] = tone
            a_copy["spokesperson_1"] = sp1 or ""
            a_copy["spokesperson_2"] = sp2 or ""
            a_copy["unit_eselon"] = unit or "IA"
            a_copy["terkait_kemenperin"] = "Ya"
            a_copy["kemenperin_signal_type"] = "Direct Crawl"
            a_copy["kemenperin_signal_detail"] = "kemenperin.go.id"
            a_copy["keyword"] = "kemenperin_institusi"
            a_copy["sumber_data"] = "Direct Crawl"
            crawl_flagged.append(a_copy)
        if crawl_flagged:
            save_keyword_progress(
                "direct_crawl_kemenperin",
                crawl_flagged,
                report_data={
                    "initial": len(crawl_items),
                    "date_valid": len(crawl_items),
                    "final_valid": len(crawl_flagged),
                    "kemenperin_yes": len(crawl_flagged),
                    "kemenperin_no": 0,
                    "source": "Direct_Crawl",
                },
                target_date=yesterday_date,
            )
            print(f"[+] Berhasil menambahkan {len(crawl_flagged)} siaran pers resmi ke checkpoint progres.")

    # Direct Pull File Manual dari folder pdf_input/ jika ada - DIBLOKIR / DINONAKTIFKAN
    # Dokumen PDF tidak lagi diambil sesuai instruksi user
    # manual_pdfs = process_pdf_input_folder("pdf_input")

    # Finalisasi dan Penggabungan Dataset ke Excel dalam folder tanggal
    print("\n" + "=" * 70)
    print(f"=== FINALISASI DAN EKSPOR DATASET LENGKAP ({date_str}) ===")
    print("=" * 70)

    final_prog = load_progress(yesterday_date)
    all_articles = final_prog.get("articles", [])
    print(f"Total artikel unik terkumpul di {date_folder}/progress.json: {len(all_articles)}")

    if all_articles:
        final_unique = dedup_across_keywords(all_articles, threshold=85)
        final_excel_path = os.path.join(date_folder, f"all_{date_str}.xlsx")

        saved_final = save_to_excel(final_unique, final_excel_path, merge_existing=True)
        print(f"[SUKSES] File Excel berhasil disimpan / di-merge ke: {saved_final}")
        terbaru_excel_path = os.path.join(date_folder, f"all_{date_str}_terbaru.xlsx")
        save_to_excel(final_unique, terbaru_excel_path, merge_existing=False)

        # Laporan Ringkasan Akhir
        try:
            df_final = pd.read_excel(saved_final)
            print("\n" + "=" * 70)
            print(f"=== RINGKASAN DATASET FINAL ({date_str}) ===")
            print("=" * 70)
            print(f"Total baris artikel: {len(df_final)}")
            
            print("\n[1] DISTRIBUSI SUMBER DATA:")
            if "Sumber Data" in df_final.columns:
                print(df_final["Sumber Data"].value_counts().to_string())
            else:
                print("  (Kolom 'Sumber Data' tidak ditemukan)")

            print("\n[2] DISTRIBUSI TONE GABUNGAN:")
            if "Tone" in df_final.columns:
                print(df_final["Tone"].value_counts().to_string())
            else:
                print("  (Kolom 'Tone' tidak ditemukan)")

            print("\n[3] PENGGUNAAN KUOTA YOUTUBE DATA API:")
            print(f"  Total kuota terpakai sesi ini: {get_youtube_quota_used()} unit (dari limit harian 10.000 unit)")
            print("=" * 70)
        except Exception as err:
            print(f"  [Warning] Gagal mencetak ringkasan dataset: {err}")
    else:
        print("[INFO] Tidak ada artikel terkumpul untuk diekspor.")


if __name__ == "__main__":
    main()

