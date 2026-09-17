"""
run_comparison_test.py
Skrip uji banding cakupan Google News RSS vs Exa Search untuk keyword "gula" dan "industri agro".
Menghasilkan laporan perbandingan lengkap dan file Excel yang dinamai sesuai tanggal evaluasi.
"""

import os
import sys
import json
import pandas as pd
from rapidfuzz import fuzz

from exa_search import search_exa
from fetch_news import is_valid_domain, is_near_duplicate_title
from relevance_filter import matches_word_boundary
from main import filter_valid_articles

EVALUATED_DATE = "2026-09-14"
# Window UTC yang mencakup 2026-09-14 00:00:00 WIB (UTC+7) hingga 23:59:59 WIB
START_DATE = "2026-09-13T17:00:00.000Z"
END_DATE = "2026-09-14T23:59:59.999Z"
TARGET_KEYWORDS = ["gula", "industri agro"]
OUTPUT_EXCEL = f"hasil_scrapping/uji_banding_rss_vs_exa_{EVALUATED_DATE}.xlsx"
OUTPUT_EXCEL_DATE_ONLY = f"hasil_scrapping/{EVALUATED_DATE}.xlsx"


def is_evaluated_date(pub_str: str, target_date_str: str = EVALUATED_DATE) -> bool:
    if not pub_str:
        return False
    if target_date_str in str(pub_str)[:10]:
        return True
    try:
        dt = pd.to_datetime(pub_str, errors="coerce")
        if pd.isna(dt):
            return False
        if dt.tzinfo is not None:
            dt = dt.tz_convert("Asia/Jakarta")
        elif str(pub_str).endswith("Z"):
            dt = pd.to_datetime(pub_str).tz_localize("UTC").tz_convert("Asia/Jakarta")
        return dt.strftime("%Y-%m-%d") == target_date_str
    except Exception:
        return target_date_str in str(pub_str)


def classify_media_type(url: str, media_name: str = "") -> str:
    from urllib.parse import urlparse
    parsed = urlparse(str(url))
    netloc = parsed.netloc.lower()
    
    if ".go.id" in netloc:
        return "Portal Pemerintah (.go.id)"
    
    foreign_tlds = [".mx", ".us", ".uk", ".ru", ".cn", ".in", ".br", ".de", ".fr", ".au"]
    if any(netloc.endswith(t) for t in foreign_tlds) or "nfaausa" in netloc or "lagula.com" in netloc:
        return "Situs Asing / Non-ID"
        
    national_medias = [
        "detik.com", "kompas.com", "cnnindonesia.com", "cnbcindonesia.com",
        "bisnis.com", "tempo.co", "kontan.co.id", "antaranews.com",
        "liputan6.com", "tribunnews.com", "republika.co.id", "jawapos.com",
        "merdeka.com", "suara.com", "katadata.co.id", "viva.co.id",
        "sindonews.com", "okezone.com", "inews.id", "industry.co.id", "rri.co.id"
    ]
    if any(m in netloc for m in national_medias):
        return "Media Nasional"
        
    return "Media Lokal / Daerah"


def run_test(api_key: str | None = None):
    key = api_key or os.environ.get("EXA_API_KEY", "").strip()
    if not key:
        print("[ERROR] EXA_API_KEY belum tersedia.")
        return None

    # 1. Muat data baseline RSS dari hasil_scraping_semua_keyword_clean.xlsx
    clean_excel_path = "hasil_scrapping/hasil_scraping_semua_keyword_clean.xlsx"
    df_clean = pd.read_excel(clean_excel_path)
    
    rss_data = {}
    for kw in TARGET_KEYWORDS:
        subset = df_clean[df_clean["Keywords"].str.contains(kw, case=False, na=False)].copy()
        rss_data[kw] = subset.to_dict(orient="records")
        print(f"[Baseline RSS] '{kw}': {len(rss_data[kw])} artikel valid bertanggal {EVALUATED_DATE}")

    # 2. Jalankan Exa Search untuk masing-masing keyword
    exa_data = {}
    for kw in TARGET_KEYWORDS:
        print(f"\n[Exa Search] Menjalankan pencarian literal untuk: '{kw}'...")
        try:
            raw_results = search_exa(
                query=kw,
                api_key=key,
                start_published_date=START_DATE,
                end_published_date=END_DATE,
                search_type="keyword",
                num_results=25,
            )
            print(f"      -> Exa mentah mengembalikan: {len(raw_results)} entri")
        except Exception as e:
            print(f"      -> [Error Exa] {e}")
            raw_results = []

        # Filter ketat: tanggal tepat, domain valid, keyword literal di judul/teks, dan filter konten pipeline
        processed_candidates = []
        for item in raw_results:
            title = item.get("title", "")
            link = item.get("link", "")
            text = item.get("text", "")
            pub = item.get("published", "")

            # Cek tanggal tepat kemarin (2026-09-14 WIB)
            if not is_evaluated_date(pub, EVALUATED_DATE):
                continue

            # Cek valid domain
            if not is_valid_domain(link):
                continue

            # Cek keyword literal ada di judul atau isi teks
            if not (matches_word_boundary(kw, title) or matches_word_boundary(kw, text)):
                continue

            processed_candidates.append({
                "title": title,
                "link": link,
                "text": text,
                "published": pub,
                "media_name": item.get("media_name", ""),
                "keyword": kw,
            })

        valid_exa, discarded_exa = filter_valid_articles(processed_candidates, min_length=300, default_keyword=kw)
        exa_data[kw] = valid_exa
        print(f"      -> Lolos filter ketat & relevansi: {len(valid_exa)} artikel (Dibuang: {len(discarded_exa)})")

    # 3. Analisis Perbandingan Cakupan
    comparison_summary = []
    detail_records = []

    for kw in TARGET_KEYWORDS:
        rss_articles = rss_data.get(kw, [])
        exa_articles = exa_data.get(kw, [])

        # Cari overlap berdasarkan URL atau kemiripan judul >= 85
        overlap = []
        only_rss = []
        only_exa = []

        matched_exa_indices = set()
        for r_art in rss_articles:
            r_title = str(r_art.get("Title", ""))
            r_url = str(r_art.get("Link Website", "")).split("?")[0].rstrip("/")

            match_found = False
            for e_idx, e_art in enumerate(exa_articles):
                e_title = str(e_art.get("title", ""))
                e_url = str(e_art.get("link", "")).split("?")[0].rstrip("/")

                if (r_url and r_url == e_url) or is_near_duplicate_title(r_title, e_title, threshold=85):
                    overlap.append({
                        "Keyword": kw,
                        "Kategori": "Overlap (Keduanya)",
                        "Tipe Sumber": classify_media_type(r_url, r_art.get("Media Name", "")),
                        "Title": r_title,
                        "Media RSS": r_art.get("Media Name", ""),
                        "Media Exa": e_art.get("media_name", ""),
                        "Link": r_url,
                        "Tanggal": r_art.get("Tanggal", ""),
                    })
                    matched_exa_indices.add(e_idx)
                    match_found = True
                    break

            if not match_found:
                only_rss.append({
                    "Keyword": kw,
                    "Kategori": "Hanya RSS",
                    "Tipe Sumber": classify_media_type(r_url, r_art.get("Media Name", "")),
                    "Title": r_title,
                    "Media RSS": r_art.get("Media Name", ""),
                    "Media Exa": "-",
                    "Link": r_url,
                    "Tanggal": r_art.get("Tanggal", ""),
                })

        for e_idx, e_art in enumerate(exa_articles):
            if e_idx not in matched_exa_indices:
                e_link = e_art.get("link", "")
                only_exa.append({
                    "Keyword": kw,
                    "Kategori": "Hanya Exa",
                    "Tipe Sumber": classify_media_type(e_link, e_art.get("media_name", "")),
                    "Title": e_art.get("title", ""),
                    "Media RSS": "-",
                    "Media Exa": e_art.get("media_name", ""),
                    "Link": e_link,
                    "Tanggal": e_art.get("published", ""),
                })

        comparison_summary.append({
            "Keyword": kw,
            "Total RSS": len(rss_articles),
            "Total Exa": len(exa_articles),
            "Overlap (Keduanya)": len(overlap),
            "Hanya RSS": len(only_rss),
            "Hanya Exa": len(only_exa),
        })

        detail_records.extend(overlap + only_rss + only_exa)

    # 4. Simpan ke File Excel dengan Nama Tanggal Evaluasi
    for target_path in [OUTPUT_EXCEL, OUTPUT_EXCEL_DATE_ONLY]:
        with pd.ExcelWriter(target_path, engine="openpyxl") as writer:
            pd.DataFrame(comparison_summary).to_excel(writer, sheet_name="Ringkasan_Perbandingan", index=False)
            pd.DataFrame(detail_records).to_excel(writer, sheet_name="Detail_Semua_Artikel", index=False)
        print(f"[SUKSES] Hasil uji banding berhasil disimpan ke: {target_path}")

    return {
        "summary": comparison_summary,
        "details": detail_records,
        "excel_path": OUTPUT_EXCEL,
        "excel_date_path": OUTPUT_EXCEL_DATE_ONLY,
    }


if __name__ == "__main__":
    api_key_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_test(api_key_arg)
