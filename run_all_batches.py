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
from main import filter_valid_articles, extract_one_article
from relevance_filter import get_kemenperin_signal
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel
from serper_search import search_serper_news

USE_SERPER_ONLY: bool = os.environ.get("USE_SERPER_ONLY", "false").lower() in ("true", "1", "yes")

OUTPUT_DIR = "hasil_scrapping"
os.makedirs(OUTPUT_DIR, exist_ok=True)
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "batch_progress_checkpoint.json")

# 41 Keyword sisa yang belum dijalankan (di luar 5 keyword besar)
BATCHES = [
    ["mamin", "kelapa", "gula", "tepung", "terigu"],
    ["tapioka", "sagu", "rumput laut", "alga", "spirulina"],
    ["olahan daging", "mi instan", "ikan kaleng", "makanan kemasan", "biskuit"],
    ["pulp", "mebel", "furniture", "atsiri", "karet"],
    ["kayu lapis", "hasil tembakau", "kakao", "cokelat", "minuman beralkohol"],
    ["minuman berpemanis", "nikotin", "tar", "teh", "susu"],
    ["amdk", "air minum dalam kemasan", "galon guna ulang", "kopi", "cpo"],
    ["minyak sawit", "pome", "fame", "biodiesel", "bioethanol", "pakan ternak"],
]

FIVE_BIG_KEYWORDS = ["industri agro", "makanan dan minuman", "sawit", "kertas", "rokok"]
ALL_46_KEYWORDS = [kw for b in BATCHES for kw in b] + FIVE_BIG_KEYWORDS


def process_keyword(kw: str, name_map: dict, serper_only: bool = False) -> dict:
    """Memproses satu keyword dengan RSS + integrasi Exa untuk keyword satu kata."""
    use_serper = serper_only or USE_SERPER_ONLY
    if use_serper:
        raw = search_serper_news(kw)
    else:
        raw = search_keyword(kw)

    # Integrasi Exa Search permanen: HANYA untuk keyword satu kata
    if is_single_word_keyword(kw):
        print(f"      [Exa.ai] Fetching berita pelengkap untuk keyword 1 kata '{kw}'...", flush=True)
        exa_items = search_exa_news(kw)
        if exa_items:
            print(f"      -> {len(exa_items)} kandidat pelengkap ditemukan oleh Exa Search.", flush=True)
            raw = raw + exa_items
        else:
            print(f"      -> Tidak ada entri tambahan dari Exa (atau EXA_API_KEY tidak diset).", flush=True)

    candidates = dedup_by_link(raw)
    initial_count = len(candidates)

    yesterday_items = [c for c in candidates if is_published_yesterday(c.get("published", ""))]
    date_dropped = initial_count - len(yesterday_items)

    extracted = []
    if yesterday_items:
        workers = 4 if use_serper else 2
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(extract_one_article, item) for item in yesterday_items]
            for f in as_completed(futures):
                try:
                    extracted.append(f.result(timeout=35))
                except GoogleCaptchaBlockedError:
                    raise
                except Exception:
                    pass

    content_valid, discarded = filter_valid_articles(extracted, min_length=300, default_keyword=kw)

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
    parser.add_argument("--skip-access-check", action="store_true", help="Lewati tes awal akses Google News")
    args = parser.parse_args()

    if args.api_key:
        os.environ["SERPER_API_KEY"] = args.api_key.strip()

    global USE_SERPER_ONLY
    if args.serper_only:
        USE_SERPER_ONLY = True
        os.environ["USE_SERPER_ONLY"] = "true"

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
        if all(is_keyword_completed(k, target_date=yesterday_date) for k in kw_list):
            print(f"[SKIP] Batch {b_num}/{total_batches} ({kw_list}) seluruhnya sudah selesai di {date_folder}.")
            continue

        print(f"\n" + "=" * 70)
        print(f"=== SESI BATCH {b_num}/{total_batches}: {kw_list} ===")
        print("=" * 70)

        captcha_triggered = False

        for kw_idx, kw in enumerate(kw_list):
            # 6. Checkpoint per keyword: lewati jika sudah ada
            if is_keyword_completed(kw, target_date=yesterday_date):
                print(f"  [SKIP] Keyword '{kw}' sudah selesai di {date_folder}/progress.json.", flush=True)
                continue

            # 2. Jeda antar-keyword (10-15 detik)
            if kw_idx > 0 or b_idx > 0:
                if USE_SERPER_ONLY:
                    time.sleep(1.0)
                else:
                    sleep_between_keywords()

            print(f"  [>] Memproses keyword: '{kw}'...", flush=True)
            try:
                res = process_keyword(kw, name_map)
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
                print(
                    f"      -> Awal={res['initial']} | Tgl Kemarin={res['date_valid']} | "
                    f"FINAL VALID={res['final_valid']} (Kemenperin: Ya={res['kemenperin_yes']} / Tidak={res['kemenperin_no']})",
                    flush=True,
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

        # 8. Batasi 5-6 keyword per sesi eksekusi: jeda 2-3 menit antar-batch
        if b_idx < total_batches - 1 and (target_batch_indices is None or (b_idx + 1) in target_batch_indices):
            session_delay = random.uniform(120.0, 180.0)
            print(f"\n[Jeda Antar-Sesi] Menunggu jeda aman {session_delay:.1f} detik (2-3 menit) sebelum batch berikutnya...", flush=True)
            time.sleep(session_delay)

    # Proses 5 Keyword Besar jika tidak ada batasan batch atau eksplisit diminta
    run_five_big = (target_batch_indices is None) or ("big" in (args.batches or "").lower()) or ("9" in (args.batches or ""))
    if run_five_big and not all(is_keyword_completed(k, target_date=yesterday_date) for k in FIVE_BIG_KEYWORDS):
        print(f"\n" + "=" * 70)
        print(f"=== SESI 5 KEYWORD BESAR: {FIVE_BIG_KEYWORDS} ===")
        print("=" * 70)
        for kw_idx, kw in enumerate(FIVE_BIG_KEYWORDS):
            if is_keyword_completed(kw, target_date=yesterday_date):
                print(f"  [SKIP] Keyword 5 besar '{kw}' sudah selesai di {date_folder}/progress.json.", flush=True)
                continue

            if not USE_SERPER_ONLY:
                sleep_between_keywords()

            print(f"  [>] Memproses keyword 5 besar: '{kw}'...", flush=True)
            try:
                res = process_keyword(kw, name_map)
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
                print(
                    f"      -> Awal={res['initial']} | Tgl Kemarin={res['date_valid']} | "
                    f"FINAL VALID={res['final_valid']} (Kemenperin: Ya={res['kemenperin_yes']} / Tidak={res['kemenperin_no']})",
                    flush=True,
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
    else:
        print("[INFO] Tidak ada artikel terkumpul untuk diekspor.")


if __name__ == "__main__":
    main()

