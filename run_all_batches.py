"""
run_all_batches.py
Menjalankan seluruh 41 keyword komoditas tersisa dari keyword_data.txt secara batch (5 keyword per batch).
Menggabungkan hasilnya dengan 5 keyword besar (hasil filter terbaru) ke:
hasil_scrapping/hasil_scraping_semua_keyword.xlsx
"""

import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import load_spokesperson_map, get_date_range, is_published_yesterday
from fetch_news import search_keyword, dedup_by_link, dedup_by_title
from extract_content import extract_article_text, resolve_article_url
from main import filter_valid_articles, extract_one_article
from relevance_filter import get_kemenperin_signal
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel

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


def process_keyword(kw: str, name_map: dict) -> dict:
    raw = search_keyword(kw, delay=0.5)
    candidates = dedup_by_link(raw)
    initial_count = len(candidates)

    yesterday_items = [c for c in candidates if is_published_yesterday(c.get("published", ""))]
    date_dropped = initial_count - len(yesterday_items)

    extracted = []
    if yesterday_items:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(extract_one_article, item) for item in yesterday_items]
            for f in as_completed(futures):
                extracted.append(f.result())

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
    yesterday_date, _ = get_date_range()
    print(f"================================================================================")
    print(f"=== MEMULAI BATCH SCRAPING 41 KEYWORD SISA (OPSI B & FILTER KERTAS BARU) ===")
    print(f"================================================================================")
    print(f"Tanggal evaluasi: {yesterday_date}")
    name_map = load_spokesperson_map("keyword_nama.xlsx")
    print(f"Daftar Pejabat Acuan: {len(name_map)} nama")

    # Load checkpoint jika ada
    checkpoint = {"batches_done": [], "batch_reports": [], "all_articles": []}
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
                print(f"[Checkpoint] Ditemukan: {len(checkpoint.get('batches_done', []))} batch sudah selesai sebelumnya.")
        except Exception:
            pass

    total_batches = len(BATCHES)

    for b_idx, kw_list in enumerate(BATCHES):
        b_num = b_idx + 1
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

        for kw in kw_list:
            print(f"  [>] Memproses keyword: '{kw}'...", flush=True)
            res = process_keyword(kw, name_map)
            batch_initial += res["initial"]
            batch_date_valid += res["date_valid"]
            batch_final_valid += res["final_valid"]
            batch_kemenperin_yes += res["kemenperin_yes"]
            checkpoint["all_articles"].extend(res["articles"])

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

    # Memproses ulang / mengambil 5 keyword besar dengan filter kertas terbaru
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

    # Gabungkan seluruh artikel dari 41 keyword + 5 keyword besar
    all_combined_articles = checkpoint["all_articles"] + five_big_articles
    total_raw_combined = len(all_combined_articles)
    print(f"\nTotal artikel sebelum dedup lintas keyword: {total_raw_combined}")

    # 1. Dedup URL
    seen_urls = set()
    cross_deduped = []
    for art in all_combined_articles:
        url_to_check = art.get("resolved_url") or art.get("link", "")
        clean_url = url_to_check.split("?")[0].rstrip("/")
        if clean_url not in seen_urls:
            seen_urls.add(clean_url)
            cross_deduped.append(art)

    # 2. Dedup judul (rapidfuzz >= 85)
    final_unique = dedup_by_title(cross_deduped, threshold=85)
    print(f"Total artikel setelah dedup URL & judul   : {len(final_unique)} (Dieliminasi duplikat: {total_raw_combined - len(final_unique)})")

    # NLP: Tone sentimen IndoBERT & Spokesperson mapping
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
        })

    final_excel_path = os.path.join(OUTPUT_DIR, "hasil_scraping_semua_keyword.xlsx")
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
