"""
run_uji_banding_2026_08_06.py
Menjalankan pipeline scraping khusus tanggal 6 AGUSTUS 2026:
1. 46 Keyword Komoditas Ditjen Industri Agro (Google News RSS + Exa untuk keyword 1 kata)
2. Pencarian Institusi Khusus Kemenperin via Google News RSS
3. Direct Crawl kemenperin.go.id untuk siaran pers resmi
4. Simpan hasil ke hasil_scrapping/uji_banding_2026-08-06.xlsx
5. Uji banding apple-to-apple dengan file referensi Kompilasi Data Monitoring Media Massa Periode 06 - 13 Agustus 2026.xlsx
"""

import os
import sys
import json
import time
from datetime import date, datetime
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidfuzz import fuzz

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import (
    get_date_range_custom,
    is_published_yesterday,
    is_single_word_keyword,
    load_spokesperson_map,
)
from fetch_news import (
    search_keyword,
    dedup_by_link,
    dedup_by_title,
    dedup_across_keywords,
    GoogleCaptchaBlockedError,
)
from exa_search import search_exa_news
from extract_content import extract_article_text, resolve_article_url
from main import extract_one_article, filter_valid_articles
from relevance_filter import get_kemenperin_signal
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from direct_crawl_kemenperin import crawl_kemenperin_siaran_pers
from export_excel import save_to_excel

TARGET_DATE = date(2026, 8, 6)
OUTPUT_EXCEL = os.path.join("hasil_scrapping", "uji_banding_2026-08-06.xlsx")
REFERENCE_EXCEL = r"C:\1.Pupud\MAGANG AGRO\Data\excel\Kompilasi Data Monitoring Media Massa Periode 06 - 13 Agustus 2026.xlsx"

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


def process_single_keyword(kw: str, name_map: dict, target_date: date) -> list[dict]:
    """Mengambil, mengekstrak, memvalidasi, dan mentag artikel untuk satu keyword."""
    # 1. Fetch RSS dengan query target tanggal
    try:
        raw = search_keyword(kw, target_date=target_date)
    except Exception as e:
        print(f"      [Error RSS] {e}", flush=True)
        raw = []

    # 2. Tambahan Exa untuk keyword 1 kata
    if is_single_word_keyword(kw):
        try:
            exa_items = search_exa_news(kw, target_date=target_date)
            if exa_items:
                raw.extend(exa_items)
        except Exception as e:
            print(f"      [Error Exa] {e}", flush=True)

    candidates = dedup_by_link(raw)
    date_items = [c for c in candidates if is_published_yesterday(c.get("published", ""), target_date=target_date)]

    # Pre-filter judul promosi/kuliner sebelum download HTML penuh
    filtered_date_items = []
    for c in date_items:
        t = c.get("title", "")
        tl = t.lower()
        if any(tl.startswith(p) for p in ["jual ", "beli ", "promo ", "diskon ", "harga menu "]):
            continue
        if any(n in tl for n in ["seblak ", "grab food", "online 24 jam", "resep roemah"]):
            continue
        filtered_date_items.append(c)

    if not filtered_date_items:
        return []

    # 3. Ekstraksi konten artikel
    extracted = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(extract_one_article, item) for item in filtered_date_items]
        for f in as_completed(futures):
            try:
                extracted.append(f.result(timeout=20))
            except Exception:
                pass

    # 4. Filter Relevansi
    content_valid, _ = filter_valid_articles(extracted, min_length=300, default_keyword=kw)

    # 5. Tagging Kemenperin, Tone, Spokesperson
    tagged = []
    for art in content_valid:
        title = art.get("title", "")
        text = art.get("text", "")
        is_rel, sig_type, sig_det = get_kemenperin_signal(title, text, name_map)
        sp1, sp2, unit = find_spokespersons(text, name_map)
        tone = classify_tone(text)

        item_copy = dict(art)
        item_copy["keyword"] = kw
        item_copy["terkait_kemenperin"] = "Ya" if is_rel else "Tidak"
        item_copy["kemenperin_signal_type"] = sig_type
        item_copy["kemenperin_signal_detail"] = sig_det
        item_copy["spokesperson_1"] = sp1
        item_copy["spokesperson_2"] = sp2
        item_copy["unit_eselon"] = unit
        item_copy["tone"] = tone
        tagged.append(item_copy)

    return tagged


def run_pipeline_for_date():
    os.environ["OVERRIDE_DATE"] = TARGET_DATE.strftime("%Y-%m-%d")
    start_d, end_d = get_date_range_custom(TARGET_DATE)
    print("=" * 80)
    print(f"=== PIPELINE SCRAPING KHUSUS TANGGAL: {TARGET_DATE} ===")
    print(f"Target Date Custom: {start_d} s.d. {end_d}")
    print("=" * 80)

    name_map = load_spokesperson_map("keyword_nama.xlsx")
    print(f"Pejabat terdaftar: {len(name_map)} orang\n")

    all_articles = []

    # -------------------------------------------------------------
    # BAGIAN 1: 46 KEYWORD KOMODITAS AGRO
    # -------------------------------------------------------------
    print("--- [1/3] Menjalankan 46 Keyword Komoditas Ditjen Industri Agro ---")
    for idx, kw in enumerate(ALL_46_KEYWORDS, start=1):
        print(f"[{idx:02d}/46] Memproses: '{kw}'...", end="", flush=True)
        t0 = time.time()
        res = process_single_keyword(kw, name_map, TARGET_DATE)
        elapsed = time.time() - t0
        print(f" -> {len(res)} artikel lolos (durasi {elapsed:.1f}s)", flush=True)
        all_articles.extend(res)
        time.sleep(0.2)  # jeda sopan antar-keyword

    # -------------------------------------------------------------
    # BAGIAN 2: PENCARIAN INSTITUSI KHUSUS
    # -------------------------------------------------------------
    print("\n--- [2/3] Menjalankan Pencarian Institusi Khusus Kemenperin ---")
    query_institusi = 'Kemenperin OR "Kementerian Perindustrian" OR "Agus Gumiwang" OR "Putu Juli Ardika"'
    print(f"Query: {query_institusi}")
    try:
        raw_inst = search_keyword(query_institusi, target_date=TARGET_DATE)
        raw_inst_dedup = dedup_by_link(raw_inst)
        inst_date = [c for c in raw_inst_dedup if is_published_yesterday(c.get("published", ""), target_date=TARGET_DATE)]
        print(f"Ditemukan {len(inst_date)} artikel institusi tanggal {TARGET_DATE}. Mengekstrak konten...")

        extracted_inst = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(extract_one_article, item) for item in inst_date]
            for f in as_completed(futures):
                try:
                    extracted_inst.append(f.result(timeout=35))
                except Exception:
                    pass

        valid_inst, _ = filter_valid_articles(extracted_inst, min_length=300, default_keyword="kemenperin_institusi")
        for art in valid_inst:
            title = art.get("title", "")
            text = art.get("text", "")
            is_rel, sig_type, sig_det = get_kemenperin_signal(title, text, name_map)
            sp1, sp2, unit = find_spokespersons(text, name_map)
            tone = classify_tone(text)

            item_copy = dict(art)
            item_copy["keyword"] = "kemenperin_institusi"
            # Dari pencarian institusi khusus, otomatis Terkait Kemenperin = Ya
            item_copy["terkait_kemenperin"] = "Ya"
            item_copy["kemenperin_signal_type"] = sig_type or "EKSPLISIT"
            item_copy["kemenperin_signal_detail"] = sig_det or "kemenperin_institusi"
            item_copy["spokesperson_1"] = sp1
            item_copy["spokesperson_2"] = sp2
            item_copy["unit_eselon"] = unit
            item_copy["tone"] = tone
            all_articles.append(item_copy)
        print(f"Hasil Institusi Khusus: {len(valid_inst)} artikel lolos.")
    except Exception as e:
        print(f"Gagal pada pencarian institusi khusus: {e}")

    # -------------------------------------------------------------
    # BAGIAN 3: DIRECT CRAWL kemenperin.go.id
    # -------------------------------------------------------------
    print("\n--- [3/3] Menjalankan Direct Crawl kemenperin.go.id ---")
    try:
        crawl_results = crawl_kemenperin_siaran_pers(target_date=TARGET_DATE, max_pages=3)
        print(f"Direct crawl menemukan {len(crawl_results)} rilis resmi.")
        for r in crawl_results:
            text = r.get("text", "")
            sp1, sp2, unit = find_spokespersons(text, name_map)
            tone = classify_tone(text)
            r["spokesperson_1"] = sp1
            r["spokesperson_2"] = sp2
            r["unit_eselon"] = unit
            r["tone"] = tone
            all_articles.append(r)
    except Exception as e:
        print(f"Gagal direct crawl kemenperin: {e}")

    # -------------------------------------------------------------
    # DEDUPLIKASI LINTAS-KEYWORD & EKSPOR
    # -------------------------------------------------------------
    print("\n" + "=" * 80)
    print("=== DEDUPLIKASI & EKSPOR HASIL SCRAPING ===")
    print("=" * 80)
    print(f"Total artikel sebelum deduplikasi: {len(all_articles)}")
    final_unique = dedup_across_keywords(all_articles, threshold=85)
    print(f"Total artikel unik final: {len(final_unique)}")

    saved_path = save_to_excel(final_unique, OUTPUT_EXCEL, merge_existing=False)
    print(f"File hasil scraping disimpan ke: {saved_path}")

    # -------------------------------------------------------------
    # ANALISIS PERBANDINGAN DENGAN FILE REFERENSI
    # -------------------------------------------------------------
    compare_with_reference(final_unique)


def compare_with_reference(scraped_articles: list[dict]):
    print("\n" + "=" * 80)
    print("=== PERBANDINGAN APPLE-TO-APPLE DENGAN FILE REFERENSI ===")
    print("=" * 80)

    if not os.path.exists(REFERENCE_EXCEL):
        print(f"File referensi tidak ditemukan di: {REFERENCE_EXCEL}")
        return

    ref_df = pd.read_excel(REFERENCE_EXCEL, sheet_name="Sheet1")
    ref_df["parsed_date"] = pd.to_datetime(ref_df["Date"]).dt.date
    ref_target = ref_df[ref_df["parsed_date"] == TARGET_DATE].copy()

    total_ref = len(ref_target)
    agro_ref = len(ref_target[ref_target["Category"].str.contains("Agro", case=False, na=False)])
    kemenperin_ref = len(
        ref_target[
            (ref_target["Category"] == "01. Kementerian Perindustrian")
            & (ref_target["Category Group"] == "Kemenperin")
        ]
    )

    print(f"1. STATISTIK FILE REFERENSI (Tanggal {TARGET_DATE}):")
    print(f"   - Total baris referensi                : {total_ref} artikel")
    print(f"   - Kategori '03. Industri Agro'         : {agro_ref} artikel")
    print(f"   - Kategori '01. Kemenperin' (Kemenperin): {kemenperin_ref} artikel")
    print(f"   - Media Type referensi                 : {dict(ref_target['Media Type'].value_counts())}")

    total_scraped = len(scraped_articles)
    kemenperin_yes = sum(1 for a in scraped_articles if a.get("terkait_kemenperin") == "Ya")
    kemenperin_no = total_scraped - kemenperin_yes

    print(f"\n2. STATISTIK HASIL SCRAPING KITA (Tanggal {TARGET_DATE}):")
    print(f"   - Total artikel ditemukan              : {total_scraped} artikel")
    print(f"   - Terkait Kemenperin: Ya               : {kemenperin_yes} artikel")
    print(f"   - Terkait Kemenperin: Tidak            : {kemenperin_no} artikel")

    # Pencocokan judul artikel referensi dengan hasil scraping
    matched_ref_indices = set()
    match_details = []

    for r_idx, r_row in ref_target.iterrows():
        r_title = str(r_row["Title"]).strip()
        r_url = str(r_row.get("Source", "")).strip()

        best_score = 0
        best_match = None
        for s in scraped_articles:
            s_title = s.get("title", "")
            s_url = s.get("link", "")
            # Cek kecocokan URL exact jika ada
            if r_url and s_url and (r_url in s_url or s_url in r_url):
                best_score = 100
                best_match = s
                break
            score = fuzz.token_set_ratio(r_title.lower(), s_title.lower())
            if score > best_score:
                best_score = score
                best_match = s

        if best_score >= 80:
            matched_ref_indices.add(r_idx)
            match_details.append({
                "ref_title": r_title,
                "scraped_title": best_match.get("title"),
                "score": best_score,
                "category": r_row.get("Category"),
                "media": r_row.get("Media Name"),
            })

    print(f"\n3. HASIL PENCOCOKAN DENGAN REFERENSI:")
    print(f"   - Artikel referensi yang COCOK ditemukan kita : {len(matched_ref_indices)} dari {total_ref} ({len(matched_ref_indices)/total_ref*100:.1f}%)")
    print(f"   - Artikel referensi yang TIDAK KETEMU          : {total_ref - len(matched_ref_indices)} artikel")

    # Analisis artikel yang tidak ketemu
    unmatched_ref = ref_target.loc[~ref_target.index.isin(matched_ref_indices)].copy()

    # Kategori artikel yang tidak ketemu
    print(f"\n4. DISTRIBUSI KATEGORI ARTIKEL REFERENSI YANG TIDAK KETEMU:")
    print(unmatched_ref["Category"].value_counts().to_string())

    print(f"\n5. ANALISIS AKAR PENYEBAB ARTIKEL REFERENSI TIDAK KETEMU:")
    reasons = {
        "Bukan Sektor Agro (Otomotif/GIIAS/Motor Listrik/ILMATE)": 0,
        "Bukan Sektor Agro (Tekstil/TPT/Alas Kaki/IKFT)": 0,
        "Bukan Sektor Agro (Pertambangan/IUPK/Hilirisasi Mineral)": 0,
        "Bukan Sektor Agro (Ekonomi Makro/Purbaya/Luhut/BPS/Non-Agro)": 0,
        "Media TV (Bukan Media Online)": 0,
        "Topik Agro / Kemenperin tapi tidak terindeks RSS Google": 0,
    }

    sample_unmatched_agro = []
    sample_unmatched_other = []

    for _, row in unmatched_ref.iterrows():
        title = str(row["Title"])
        cat = str(row["Category"])
        m_type = str(row.get("Media Type", "")).lower()

        if "tv" in m_type:
            reasons["Media TV (Bukan Media Online)"] += 1
            continue

        tl = title.lower()
        if any(w in tl for w in ["motor", "mobil", "giias", "toyota", "daihatsu", "hyundai", "otomotif", "ilmate"]):
            reasons["Bukan Sektor Agro (Otomotif/GIIAS/Motor Listrik/ILMATE)"] += 1
            sample_unmatched_other.append((row["Media Name"], title, "Otomotif / ILMATE"))
        elif any(w in tl for w in ["tekstil", "tpt", "kain", "pakaian", "sepatu", "zeintin", "kulit"]):
            reasons["Bukan Sektor Agro (Tekstil/TPT/Alas Kaki/IKFT)"] += 1
            sample_unmatched_other.append((row["Media Name"], title, "Tekstil / IKFT"))
        elif any(w in tl for w in ["iupk", "tambang", "nikel", "mineral", "bauxit", "ancora"]):
            reasons["Bukan Sektor Agro (Pertambangan/IUPK/Hilirisasi Mineral)"] += 1
            sample_unmatched_other.append((row["Media Name"], title, "Mineral / Tambang"))
        elif any(w in tl for w in ["purbaya", "pengangguran", "g20", "bps", "cilacap", "pelabuhan", "thailand", "harley"]):
            reasons["Bukan Sektor Agro (Ekonomi Makro/Purbaya/Luhut/BPS/Non-Agro)"] += 1
            sample_unmatched_other.append((row["Media Name"], title, "Makro / Non-Agro"))
        else:
            reasons["Topik Agro / Kemenperin tapi tidak terindeks RSS Google"] += 1
            sample_unmatched_agro.append((row["Media Name"], title, cat))

    for reason, count in reasons.items():
        print(f"   - {reason}: {count} artikel")

    if sample_unmatched_agro:
        print(f"\n   [DAFTAR ARTIKEL BERPOTENSI RELEVAN YANG TIDAK TERINDEKS RSS / DI LUAR KEYWORD]:")
        for med, tit, cat in sample_unmatched_agro[:15]:
            print(f"     * [{cat}] {med}: {tit}")

    print("\n" + "=" * 80)
    print("=== SELESAI PENGUJIAN UJI BANDING 6 AGUSTUS 2026 ===")
    print("=" * 80)


if __name__ == "__main__":
    run_pipeline_for_date()
