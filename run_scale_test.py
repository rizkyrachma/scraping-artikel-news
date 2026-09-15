"""
run_scale_test.py
Uji skala 5 keyword besar dari keyword_data.txt dengan SKEMA OPSI B (Flagging Kemenperin):
1. industri agro
2. makanan dan minuman
3. sawit
4. kertas
5. rokok

Alur:
1. Fetch RSS & dedup URL awal
2. Filter tanggal publikasi HANYA KEMARIN (H-1) langsung dari metadata RSS
3. Ekstraksi konten teks (dengan timeout 20s & retry untuk .go.id)
4. Filter validitas konten industri (panjang >= 300, frekuensi keyword, anti-resep, anti-promo, industri vs personal)
5. Flagging Kemenperin: "Ya" vs "Tidak" (TIDAK MEMBUANG ARTIKEL NON-KEMENPERIN)
6. Deduplikasi lintas keyword, Entity Mapping & IndoBERT Sentiment
7. Ekspor ke Excel hasil_scrapping/hasil_scraping_5_keyword_opsi_b.xlsx dengan 9 kolom
"""

import os
import json
from config import load_spokesperson_map, get_date_range, is_published_yesterday
from fetch_news import search_keyword, dedup_by_link, dedup_by_title
from extract_content import extract_article_text, resolve_article_url
from concurrent.futures import ThreadPoolExecutor, as_completed
from main import filter_valid_articles
from relevance_filter import get_kemenperin_signal
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel

KEYWORDS = [
    "industri agro",
    "makanan dan minuman",
    "sawit",
    "kertas",
    "rokok",
]

OUTPUT_DIR = "hasil_scrapping"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def extract_one(item: dict) -> dict:
    link = item.get("link", "")
    try:
        res = resolve_article_url(link)
    except Exception:
        res = link
    try:
        txt = extract_article_text(res, max_length=8000)
    except Exception:
        txt = ""
    item_copy = dict(item)
    item_copy["text"] = txt
    item_copy["resolved_url"] = res
    if res and "news.google.com" not in res:
        item_copy["link"] = res
    return item_copy


def test_keyword(kw: str, name_map: dict) -> dict:
    print(f"\n========================================================", flush=True)
    print(f"[*] MEMPROSES KEYWORD: '{kw}'", flush=True)
    print(f"========================================================", flush=True)

    # 1. Fetch & dedup URL awal
    raw = search_keyword(kw, delay=0.5)
    candidates = dedup_by_link(raw)
    initial_count = len(candidates)
    print(f"  1. Kandidat awal (setelah dedup URL): {initial_count}", flush=True)

    # 2. Filter tanggal langsung dari metadata RSS (HANYA KEMARIN)
    yesterday_items = [c for c in candidates if is_published_yesterday(c.get("published", ""))]
    date_dropped_count = initial_count - len(yesterday_items)
    print(f"  2. Lolos filter tanggal kemarin: {len(yesterday_items)} (Gugur arsip lama: {date_dropped_count})", flush=True)

    # 3. Ekstraksi konten teks HANYA untuk artikel tanggal kemarin
    print(f"  3. Mengekstrak {len(yesterday_items)} artikel tanggal kemarin...", flush=True)
    extracted = []
    if yesterday_items:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(extract_one, c) for c in yesterday_items]
            for f in as_completed(futures):
                extracted.append(f.result())

    # 4. Filter validitas konten (panjang, primary topic, resep, promo, industri vs kesehatan, dedup judul)
    content_valid, discarded = filter_valid_articles(extracted, min_length=300, default_keyword=kw)
    content_valid_count = len(content_valid)
    print(f"  4. Lolos filter konten relevan & industri: {content_valid_count} (Dibuang konten: {len(discarded)})", flush=True)

    # 5. OPSI B: Flagging Institusi Kemenperin (Eksplisit/Implisit) - TIDAK DIBUANG
    kemenperin_yes = 0
    flagged_articles = []
    for art in content_valid:
        is_rel, sig_type, sig_det = get_kemenperin_signal(art["title"], art["text"], name_map)
        item_copy = dict(art)
        item_copy["keyword"] = kw
        item_copy["terkait_kemenperin"] = "Ya" if is_rel else "Tidak"
        item_copy["kemenperin_signal_type"] = sig_type
        item_copy["kemenperin_signal_detail"] = sig_det
        flagged_articles.append(item_copy)
        if is_rel:
            kemenperin_yes += 1

    kemenperin_no = content_valid_count - kemenperin_yes
    print(
        f"  5. OPSI B: Semua {content_valid_count} artikel disimpan! | "
        f"Terkait Kemenperin: Ya={kemenperin_yes} / Tidak={kemenperin_no}",
        flush=True,
    )
    if kemenperin_yes > 0:
        for idx, art in enumerate([a for a in flagged_articles if a["terkait_kemenperin"] == "Ya"], 1):
            print(f"     [+] Kemenperin #{idx}: {art['title']} ({art['kemenperin_signal_type']}: {art['kemenperin_signal_detail']})", flush=True)

    return {
        "keyword": kw,
        "initial": initial_count,
        "date_valid": len(yesterday_items),
        "date_dropped": date_dropped_count,
        "final_valid": content_valid_count,
        "kemenperin_yes": kemenperin_yes,
        "kemenperin_no": kemenperin_no,
        "articles": flagged_articles,
    }


def main():
    yesterday_date, _ = get_date_range()
    print(f"=== UJI SKALA 5 KEYWORD BESAR (OPSI B: FLAGGING KEMENPERIN) ===")
    print(f"Tanggal 'kemarin' yang dievaluasi : {yesterday_date}")
    name_map = load_spokesperson_map("keyword_nama.xlsx")
    print(f"Daftar Pejabat Acuan ({len(name_map)} nama): {list(name_map.keys())}")

    results = []
    all_articles = []
    for kw in KEYWORDS:
        res = test_keyword(kw, name_map)
        results.append(res)
        all_articles.extend(res["articles"])

    print("\n" + "=" * 90)
    print("=== REKAPITULASI HASIL UJI SKALA 5 KEYWORD BESAR (OPSI B) ===")
    print("=" * 90)
    print(f"{'Keyword':<22} | {'Awal':<6} | {'Tgl Kemarin':<12} | {'Final Valid':<12} | {'Kemenperin Ya':<14} | {'Kemenperin Tidak':<16}")
    print("-" * 90)
    for r in results:
        print(
            f"{r['keyword']:<22} | {r['initial']:<6} | {r['date_valid']:<12} | {r['final_valid']:<12} | "
            f"{r['kemenperin_yes']:<14} | {r['kemenperin_no']:<16}"
        )
    print("=" * 90)

    # Deduplikasi lintas keyword
    total_before = len(all_articles)
    seen_urls = set()
    cross_deduped = []
    for art in all_articles:
        url_to_check = art.get("resolved_url") or art.get("link", "")
        clean_url = url_to_check.split("?")[0].rstrip("/")
        if clean_url not in seen_urls:
            seen_urls.add(clean_url)
            cross_deduped.append(art)

    final_unique = dedup_by_title(cross_deduped, threshold=85)
    print(f"\nTotal artikel sebelum dedup lintas keyword : {total_before}")
    print(f"Total artikel setelah dedup URL & judul   : {len(final_unique)} (Dieliminasi duplikat: {total_before - len(final_unique)})")

    # NLP: Tone & Spokesperson Mapping
    print("\nMenjalankan Entity Mapping dan Sentiment Analysis...")
    records = []
    sp_count = 0
    tone_dist = {"Positif": 0, "Netral": 0, "Negatif": 0}
    kemenperin_total_yes = 0

    for art in final_unique:
        text = art.get("text", "")
        sp1, sp2, unit = find_spokespersons(text, name_map)
        tone = classify_tone(text)
        terkait = art.get("terkait_kemenperin", "Tidak")
        if terkait == "Ya":
            kemenperin_total_yes += 1
        if sp1 or sp2:
            sp_count += 1
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

    excel_path = os.path.join(OUTPUT_DIR, "hasil_scraping_5_keyword_opsi_b.xlsx")
    saved_file = save_to_excel(records, excel_path)
    print(f"\n[SUKSES] File Excel Opsi B berhasil disimpan: {saved_file}")
    print(f"Ringkasan Final Excel:")
    print(f"  - Total Baris Berita   : {len(records)}")
    print(f"  - Terkait Kemenperin Ya: {kemenperin_total_yes}")
    print(f"  - Terkait Kemenperin Tdk: {len(records) - kemenperin_total_yes}")
    print(f"  - Spokesperson Terisi  : {sp_count}")
    print(f"  - Tone Sentimen        : Positif={tone_dist.get('Positif', 0)}, Netral={tone_dist.get('Netral', 0)}, Negatif={tone_dist.get('Negatif', 0)}")

    # Simpan JSON report
    json_path = os.path.join(OUTPUT_DIR, "hasil_uji_5_keyword_opsi_b.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "evaluated_date": str(yesterday_date),
            "summary_per_keyword": [
                {
                    "keyword": r["keyword"],
                    "initial_candidates": r["initial"],
                    "yesterday_date_valid": r["date_valid"],
                    "final_valid_articles": r["final_valid"],
                    "kemenperin_yes": r["kemenperin_yes"],
                    "kemenperin_no": r["kemenperin_no"],
                }
                for r in results
            ],
            "total_records_in_excel": len(records),
            "kemenperin_yes_in_excel": kemenperin_total_yes,
            "kemenperin_no_in_excel": len(records) - kemenperin_total_yes,
            "tone_distribution": tone_dist,
            "excel_path": saved_file,
        }, f, ensure_ascii=False, indent=2)
    print(f"Laporan JSON tersimpan ke: {json_path}")


if __name__ == "__main__":
    main()
