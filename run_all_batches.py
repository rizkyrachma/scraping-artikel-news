"""
run_all_batches.py
Menjalankan seluruh 41 keyword komoditas tersisa dari keyword_data.txt secara batch (5 keyword per batch).
Menggabungkan hasilnya dengan 5 keyword besar (hasil filter terbaru) ke:
hasil_scrapping/hasil_scraping_semua_keyword.xlsx
"""

import os
import json
import time
import argparse
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import load_spokesperson_map, get_date_range, is_published_yesterday
from fetch_news import search_keyword, dedup_by_link, dedup_by_title
from extract_content import (
    extract_article_text,
    resolve_article_url,
    check_google_news_access,
    GoogleCaptchaBlockedError,
)
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


def process_keyword(kw: str, name_map: dict, serper_only: bool = False) -> dict:
    use_serper = serper_only or USE_SERPER_ONLY
    if use_serper:
        raw = search_serper_news(kw)
    else:
        raw = search_keyword(kw, delay=2.0)
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


def main():
    parser = argparse.ArgumentParser(description="Batch Scraping Runner")
    parser.add_argument("--serper-only", action="store_true", help="Pakai Serper.dev SAJA (bypass Google News RSS)")
    parser.add_argument("--api-key", type=str, default=None, help="Serper.dev API Key")
    parser.add_argument("--batches", type=str, default=None, help="Nomor batch yang ingin dijalankan (contoh: 7,8)")
    args = parser.parse_args()

    if args.api_key:
        os.environ["SERPER_API_KEY"] = args.api_key.strip()

    global USE_SERPER_ONLY
    if args.serper_only:
        USE_SERPER_ONLY = True
        os.environ["USE_SERPER_ONLY"] = "true"

    yesterday_date, _ = get_date_range()
    print(f"================================================================================")
    print(f"=== MEMULAI BATCH SCRAPING KEYWORD (MODE: {'SERPER.DEV ONLY' if USE_SERPER_ONLY else 'GOOGLE NEWS RSS'}) ===")
    print(f"================================================================================")
    print(f"Tanggal evaluasi: {yesterday_date}")
    name_map = load_spokesperson_map("keyword_nama.xlsx")
    print(f"Daftar Pejabat Acuan: {len(name_map)} nama")

    # 1. PENGECEKAN STATUS SEBELUM MULAI BATCH
    if USE_SERPER_ONLY:
        print(f"\n[MODE SERPER ONLY AKTIF] Melewati pengecekan akses Google News RSS.")
        print(f"                         Seluruh query dialihkan ke Serper.dev.")
        serper_key = os.environ.get("SERPER_API_KEY", "").strip()
        if not serper_key:
            print(f"[STOP] SERPER_API_KEY tidak ditemukan di environment variable.")
            print(f"       Harap set environment variable SERPER_API_KEY terlebih dahulu sebelum menjalankan.")
            return
        print(f"[SERPER READY] API Key ditemukan di environment.\n")
    else:
        print(f"\n[TEST AKSES] Mengirim 1 request uji ringan ke Google News...")
        is_access_ok, access_msg = check_google_news_access()
        if not is_access_ok:
            print(f"[BATAL] IP masih terblokir: {access_msg}")
            print(f"        Proses dihentikan agar tidak memperparah CAPTCHA gate.")
            print(f"        Silakan tunggu dan coba lagi nanti.\n")
            return
        print(f"[TEST AKSES SUKSES] {access_msg}\n")

    # Load checkpoint jika ada
    checkpoint = {"batches_done": [], "batch_reports": [], "all_articles": []}
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
                print(f"[Checkpoint] Ditemukan: {len(checkpoint.get('batches_done', []))} batch sudah selesai sebelumnya.")
        except Exception:
            pass

    target_batch_indices = None
    if args.batches:
        try:
            target_batch_indices = [int(b.strip()) - 1 for b in args.batches.split(",") if b.strip()]
        except Exception as e:
            print(f"[Warning] Format --batches tidak valid: {e}")

    total_batches = len(BATCHES)
    current_session_articles = []

    for b_idx, kw_list in enumerate(BATCHES):
        b_num = b_idx + 1
        if target_batch_indices is not None and b_idx not in target_batch_indices:
            continue

        if b_idx in checkpoint.get("batches_done", []):
            print(f"[SKIP] Batch {b_num}/{total_batches} ({kw_list}) sudah selesai di checkpoint.")
            continue

        print(f"\n" + "=" * 70)
        print(f"=== BATCH {b_num}/{total_batches}: {kw_list} ===")
        print("=" * 70)

        batch_initial = 0
        batch_date_valid = 0
        batch_final_valid = 0
        batch_kemenperin_yes = 0
        batch_kw_stats = []

        for kw_idx, kw in enumerate(kw_list):
            if kw_idx > 0:
                if USE_SERPER_ONLY:
                    time.sleep(1.0)
                else:
                    # Jeda antar-keyword 10-15 detik untuk Google RSS
                    print(f"  [Pacing] Menunggu 12 detik sebelum keyword berikutnya...", flush=True)
                    time.sleep(12)

            print(f"  [>] Memproses keyword: '{kw}'...", flush=True)
            try:
                res = process_keyword(kw, name_map)
            except GoogleCaptchaBlockedError as c_err:
                print(f"\n[STOP DARURAT] {c_err}")
                print(f"               Menyimpan checkpoint terkini dan menghentikan pipeline.")
                with open(CHECKPOINT_FILE, "w", encoding="utf-8") as cf:
                    json.dump(checkpoint, cf, indent=2, ensure_ascii=False)
                return

            batch_initial += res["initial"]
            batch_date_valid += res["date_valid"]
            batch_final_valid += res["final_valid"]
            batch_kemenperin_yes += res["kemenperin_yes"]
            checkpoint["all_articles"].extend(res["articles"])
            current_session_articles.extend(res["articles"])

            batch_kw_stats.append({
                "keyword": kw,
                "initial": res["initial"],
                "date_valid": res["date_valid"],
                "final_valid": res["final_valid"],
                "kemenperin_yes": res["kemenperin_yes"],
                "kemenperin_no": res["kemenperin_no"],
            })
            print(
                f"      -> Awal={res['initial']} | Tgl Kemarin={res['date_valid']} | "
                f"FINAL VALID={res['final_valid']} (Kemenperin: Ya={res['kemenperin_yes']} / Tidak={res['kemenperin_no']})",
                flush=True,
            )

        checkpoint["batches_done"].append(b_idx)
        checkpoint["batch_reports"].append({
            "batch_num": b_num,
            "keywords": kw_list,
            "total_initial": batch_initial,
            "total_date_valid": batch_date_valid,
            "total_final_valid": batch_final_valid,
            "total_kemenperin_yes": batch_kemenperin_yes,
            "details": batch_kw_stats,
        })

        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)

        print("-" * 50)
        print(f"[LAPORAN BATCH {b_num}/{total_batches} SELESAI]")
        print(f"Total kandidat awal      : {batch_initial}")
        print(f"Lolos tanggal kemarin    : {batch_date_valid}")
        print(f"Total final artikel valid: {batch_final_valid}")
        print(f"Terkait Kemenperin: Ya   : {batch_kemenperin_yes} | Tidak: {batch_final_valid - batch_kemenperin_yes}")
        print("-" * 50)

    # Finalisasi dan penggabungan dataset
    clean_excel_path = os.path.join(OUTPUT_DIR, "hasil_scraping_semua_keyword_clean.xlsx")
    final_excel_path = os.path.join(OUTPUT_DIR, "hasil_scraping_semua_keyword.xlsx")

    if USE_SERPER_ONLY and os.path.exists(clean_excel_path):
        print("\n" + "=" * 70)
        print("=== MENGGABUNGKAN HASIL SERPER KE DATASET BERSIH YANG ADA ===")
        print("=" * 70)
        existing_df = pd.read_excel(clean_excel_path)
        existing_records = existing_df.to_dict(orient="records")
        print(f"Dataset awal dimuat: {len(existing_records)} baris berita bersih.")

        # Ambil artikel Batch 7 & 8 yang baru dijalankan
        batch_7_8_keywords = set([kw.lower() for kw in (BATCHES[6] + BATCHES[7])])
        articles_to_process = current_session_articles if current_session_articles else [
            a for a in checkpoint.get("all_articles", []) if a.get("keyword", "").lower() in batch_7_8_keywords
        ]
        print(f"Artikel baru dari Batch 7-8 untuk diproses: {len(articles_to_process)}")

        # Ekstrak NLP untuk artikel baru
        import dateparser
        new_records = []
        for art in articles_to_process:
            text = art.get("text", "")
            sp1, sp2, unit = find_spokespersons(text, name_map)
            tone = classify_tone(text)
            terkait = art.get("terkait_kemenperin", "Tidak")
            raw_pub = art.get("published", "")
            dt_pub = raw_pub
            try:
                parsed_dt = dateparser.parse(str(raw_pub))
                if parsed_dt:
                    dt_pub = parsed_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

            new_records.append({
                "Tanggal": dt_pub,
                "Title": art["title"],
                "Link Website": art.get("link", ""),
                "Media Name": art.get("media_name") or "",
                "Tone": tone,
                "Spokesperson 1": sp1,
                "Spokesperson 2": sp2,
                "Unit Eselon": unit,
                "Terkait Kemenperin": terkait,
                "Keywords": art.get("keyword", ""),
            })

        # Gabungkan dan dedup URL + judul
        combined_raw = existing_records + new_records
        seen_urls = set()
        dedup_records = []
        for rec in combined_raw:
            url_clean = str(rec.get("Link Website", "")).split("?")[0].rstrip("/")
            if url_clean and url_clean not in seen_urls:
                seen_urls.add(url_clean)
                dedup_records.append(rec)

        final_records = dedup_by_title(dedup_records, threshold=85)
        print(f"Hasil gabungan setelah dedup URL & judul: {len(final_records)} baris berita.")

        saved_clean = save_to_excel(final_records, clean_excel_path)
        save_to_excel(final_records, final_excel_path)
        print(f"\n[SUKSES] File dataset bersih berhasil di-update: {saved_clean}")
        return

    # Jika berjalan dengan Google RSS mode reguler:
    print("\n" + "=" * 70)
    print("=== MENGGABUNGKAN 5 KEYWORD BESAR DENGAN FILTER KERTAS TERBARU ===")
    print("=" * 70)
    five_big_articles = []
    five_big_stats = []
    for kw in FIVE_BIG_KEYWORDS:
        print(f"  [>] Menyiapkan data 5 besar: '{kw}'...", flush=True)
        res = process_keyword(kw, name_map)
        five_big_articles.extend(res["articles"])
        five_big_stats.append(res)
        print(
            f"      -> Awal={res['initial']} | Tgl Kemarin={res['date_valid']} | "
            f"FINAL VALID={res['final_valid']} (Kemenperin: Ya={res['kemenperin_yes']} / Tidak={res['kemenperin_no']})",
            flush=True,
        )

    all_combined_articles = checkpoint["all_articles"] + five_big_articles
    total_raw_combined = len(all_combined_articles)
    print(f"\nTotal artikel sebelum dedup lintas keyword: {total_raw_combined}")

    seen_urls = set()
    cross_deduped = []
    for art in all_combined_articles:
        url_to_check = art.get("resolved_url") or art.get("link", "")
        clean_url = url_to_check.split("?")[0].rstrip("/")
        if clean_url not in seen_urls:
            seen_urls.add(clean_url)
            cross_deduped.append(art)

    final_unique = dedup_by_title(cross_deduped, threshold=85)
    print(f"Total artikel setelah dedup URL & judul   : {len(final_unique)} (Dieliminasi duplikat: {total_raw_combined - len(final_unique)})")

    print("\nMenjalankan Entity Mapping dan Sentiment Analysis pada seluruh artikel...")
    records = []
    sp_count = 0
    kemenperin_total_yes = 0
    tone_dist = {"Positif": 0, "Netral": 0, "Negatif": 0}

    for art in final_unique:
        text = art.get("text", "")
        sp1, sp2, unit = find_spokespersons(text, name_map)
        tone = classify_tone(text)
        terkait = art.get("terkait_kemenperin", "Tidak")

        if sp1 or sp2:
            sp_count += 1
        if terkait == "Ya":
            kemenperin_total_yes += 1
        tone_dist[tone] = tone_dist.get(tone, 0) + 1

        records.append({
            "Tanggal": art.get("published", ""),
            "Title": art["title"],
            "Link Website": art.get("link", ""),
            "Media Name": art.get("media_name") or "",
            "Tone": tone,
            "Spokesperson 1": sp1,
            "Spokesperson 2": sp2,
            "Unit Eselon": unit,
            "Terkait Kemenperin": terkait,
            "Keywords": art.get("keyword", ""),
        })

    saved_file = save_to_excel(records, final_excel_path)
    print(f"\n[SUKSES] Seluruh scraping selesai!")
    print(f"File Excel Final berhasil disimpan ke: {saved_file}")
    print(f"Ringkasan Akhir:")
    print(f"  - Total Baris Berita   : {len(records)}")
    print(f"  - Terkait Kemenperin Ya: {kemenperin_total_yes}")
    print(f"  - Terkait Kemenperin Tdk: {len(records) - kemenperin_total_yes}")
    print(f"  - Spokesperson Terisi  : {sp_count}")
    print(f"  - Tone Sentimen        : Positif={tone_dist.get('Positif', 0)}, Netral={tone_dist.get('Netral', 0)}, Negatif={tone_dist.get('Negatif', 0)}")

    summary_json_path = os.path.join(OUTPUT_DIR, "hasil_scraping_semua_keyword_summary.json")
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "evaluated_date": str(yesterday_date),
            "total_articles": len(records),
            "kemenperin_yes": kemenperin_total_yes,
            "kemenperin_no": len(records) - kemenperin_total_yes,
            "spokesperson_filled": sp_count,
            "tone_distribution": tone_dist,
            "batch_reports": checkpoint.get("batch_reports", []),
            "five_big_stats": [
                {
                    "keyword": s["keyword"],
                    "initial": s["initial"],
                    "date_valid": s["date_valid"],
                    "final_valid": s["final_valid"],
                    "kemenperin_yes": s["kemenperin_yes"],
                    "kemenperin_no": s["kemenperin_no"],
                }
                for s in five_big_stats
            ],
            "excel_path": saved_file,
        }, f, ensure_ascii=False, indent=2)
    print(f"Laporan ringkasan tersimpan ke: {summary_json_path}")


if __name__ == "__main__":
    main()
