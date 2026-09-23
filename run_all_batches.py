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
)
from fetch_news import (
    search_keyword,
    dedup_by_link,
    dedup_by_title,
    dedup_across_keywords,
    check_google_news_access,
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
from relevance_filter import get_kemenperin_signal
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel
from serper_search import search_serper_news
from youtube_search import search_youtube_videos, get_kemenperin_channel_videos, get_youtube_quota_used
from pdf_search import search_pdf_documents
from pdf_ocr import process_pdf_input_folder

USE_SERPER_ONLY: bool = os.environ.get("USE_SERPER_ONLY", "false").lower() in ("true", "1", "yes")

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


def process_keyword(kw: str, name_map: dict, serper_only: bool = False, target_date: date | None = None) -> dict:
    """Memproses satu keyword dengan 6 sub-tahap granular, live extraction progress, dan timeout warning."""
    t_start = time.time()
    use_serper = serper_only or USE_SERPER_ONLY

    if target_date is None:
        target_date, _ = get_date_range()

    log_granular(f"  [>] Memproses keyword: '{kw}'...")

    # [1/6] Fetch RSS (media + gov)
    if use_serper:
        raw = search_serper_news(kw)
    else:
        raw = search_keyword(kw)
    log_granular(f"     [1/6] Fetch RSS (media + gov)...          -> selesai, {len(raw)} kandidat")

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
    yt_items = search_youtube_videos(kw, target_date=target_date)
    if yt_items:
        log_granular(f"     [+] Fetch YouTube (search 1x)...          -> selesai, {len(yt_items)} video")
        raw = raw + yt_items
    else:
        log_granular(f"     [-] Fetch YouTube (search 1x)...          -> 0 video (atau API key kosong)")

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
        workers = 8
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(extract_single_article_with_timer, item) for item in yesterday_items]
            completed = 0
            for f in as_completed(futures):
                completed += 1
                try:
                    res, disp_url = f.result(timeout=35)
                    extracted.append(res)
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
        is_rel, sig_type, sig_det = get_kemenperin_signal(art["title"], art["text"], name_map)
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
    parser.add_argument("--date", "--target-date", dest="target_date", type=str, default=None, help="Tanggal target evaluasi YYYY-MM-DD")
    parser.add_argument("--skip-access-check", action="store_true", help="Lewati tes awal akses Google News")
    parser.add_argument("--force", action="store_true", help="Paksa jalankan ulang keyword meskipun sudah ada di progress.json")
    args = parser.parse_args()

    if args.api_key:
        os.environ["SERPER_API_KEY"] = args.api_key.strip()

    global USE_SERPER_ONLY
    if args.serper_only:
        USE_SERPER_ONLY = True
        os.environ["USE_SERPER_ONLY"] = "true"

    if args.target_date:
        from datetime import datetime
        yesterday_date = datetime.strptime(args.target_date.strip(), "%Y-%m-%d").date()
    else:
        yesterday_date, _ = get_date_range()

    date_str = yesterday_date.strftime("%Y-%m-%d")
    date_folder = get_date_folder(yesterday_date)

    print(f"================================================================================")
    print(f"=== BATCH SCRAPING 46 KEYWORD (MODE: {'SERPER.DEV ONLY' if USE_SERPER_ONLY else 'GOOGLE NEWS RSS + EXA'}) ===")
    print(f"================================================================================")
    print(f"Tanggal evaluasi : {yesterday_date}")
    print(f"Folder Output    : {date_folder}")
    name_map = load_spokesperson_map("keyword_nama.xlsx")
    print(f"Daftar Pejabat   : {len(name_map)} nama")

    start_heartbeat()

    # 5. TES KONEKSI RINGAN SEBELUM MULAI BATCH (1x request, bukan cron)
    if USE_SERPER_ONLY:
        print(f"\n[MODE SERPER ONLY AKTIF] Melewati pengecekan akses Google News RSS.")
    elif not args.skip_access_check:
        print(f"\n[TEST AKSES RINGAN] Mengirim 1 request uji ke Google News RSS...")
        is_access_ok, access_msg = check_google_news_access()
        if not is_access_ok:
            print(f"[BATAL] IP terblokir / bermasalah: {access_msg}")
            print(f"        Proses dihentikan agar tidak memperparah CAPTCHA gate.")
            print(f"        Harap tunggu instruksi manual sebelum mencoba kembali.\n")
            return
        print(f"[TEST AKSES BERHASIL] {access_msg}\n")

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

    # Direct Pull 2 Channel Resmi Kemenperin & Ditjen Agro
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

