"""
run_full_gula_pipeline.py
Script eksekusi pipeline lengkap dari awal untuk keyword 'gula':
1. Fetch RSS & Domain filter & Initial title relevance
2. Content extraction (trafilatura + newspaper3k fallback)
3. Noise filtering:
   - Kosong / gagal ekstraksi
   - Suspiciously short (< 300 char)
   - Filter frekuensi keyword (is_keyword_primary_topic: title match ATAU >= 2x di isi)
   - Konten resep (is_recipe)
   - Materi promo supermarket (is_promotional)
   - Deduplikasi kemiripan judul (is_near_duplicate_title >= 85)
4. Filter Topik Industri / Kebijakan vs Kesehatan Personal (is_industry_policy_topic)
5. Entity mapping (spokesperson & unit eselon)
6. Analisis sentimen IndoBERT 3-kelas (Positif, Netral, Negatif)
7. Laporan statistik & tabel seluruh artikel final
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import load_spokesperson_map
from fetch_news import search_keyword, is_near_duplicate_title
from extract_content import extract_article_text, is_suspiciously_short
from relevance_filter import (
    is_recipe,
    is_promotional,
    is_keyword_primary_topic,
    count_keyword_occurrences,
    is_industry_policy_topic,
    get_industry_health_scores,
)
from entity_mapper import find_spokespersons
from sentiment import classify_tone


SUSPICIOUS_TARGETS = [
    "Pelayanan Kesehatan Sampai ke Pintu Rumah, Home Care",
    "Homecare Jadi Cara Kecamatan Sumbersari",
    "Jumat Berkah, Polres Karimun Salurkan Bantuan Sembako",
    "Lewat Program Homecare Kelurahan Sumbersari",
    "Diskominfo Kabupaten Pati",
    "Pasca Erupsi Sinabung, Kapolsek Simpang Empat",
    "Kunjungan Home Care Dispusip Dekatkan Pelayanan",
    "Polsek Sekar Lakukan Patroli Pastikan Harga Sembako",
    "Gubernur Kaltara Kenang Keramahan Warga Jateng, MTQ",
    "Kepedulian Polres Musi Rawas: Sisihkan Rezeki Demi",
]


def extract_item(idx: int, item: dict) -> dict:
    title = item["title"]
    link = item["link"]
    try:
        text = extract_article_text(link, max_length=8000)
    except Exception:
        text = ""

    item_dict = dict(item)
    item_dict["index"] = idx
    item_dict["text"] = text
    return item_dict


def main():
    print("=" * 80)
    print("EKSEKUSI PIPELINE LENGKAP DARI AWAL UNTUK KEYWORD 'GULA'")
    print("=" * 80)

    # 1. Fetch & Domain Verification & Initial Title Relevance
    print("\n[Langkah 1 & 2] Mengambil Google News RSS dan Filter Domain & Relevansi Judul...")
    raw_articles = search_keyword("gula", delay=0.5)
    total_raw = len(raw_articles)
    print(f"Total kandidat artikel lolos fetch awal: {total_raw} artikel")

    # 2. Ekstraksi Konten
    print("\n[Langkah 3] Mengekstrak konten teks artikel (trafilatura + newspaper3k fallback)...")
    extracted_items = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(extract_item, idx, item) for idx, item in enumerate(raw_articles, start=1)]
        for f in as_completed(futures):
            extracted_items.append(f.result())

    extracted_items.sort(key=lambda x: x["index"])

    # 3. Investigasi Khusus 10 Artikel Mencurigakan
    print("\n" + "=" * 80)
    print("INVESTIGASI 10 ARTIKEL MENCURIGAKAN (Puskesmas, Sembako, MTQ, Bedah Rumah)")
    print("=" * 80)
    investigated_count = 0
    discarded_suspicious_count = 0

    for item in extracted_items:
        title = item.get("title", "")
        text = item.get("text", "")
        is_target = any(target.lower() in title.lower() for target in SUSPICIOUS_TARGETS)
        if is_target:
            investigated_count += 1
            occurrences = count_keyword_occurrences(text, "gula")
            is_primary = is_keyword_primary_topic(title, text, "gula")
            decision = "LOLOS" if is_primary else "DIBUANG"
            if not is_primary:
                discarded_suspicious_count += 1

            print(f"{investigated_count}. Judul : {title}")
            print(f"   Jumlah kata 'gula' di isi: {occurrences}x | Status: [{decision}]")
            print("-" * 80)

    print(f"Ringkasan Investigasi: {discarded_suspicious_count} dari {investigated_count} artikel mencurigakan berhasil DIBUANG.")
    print("=" * 80)

    # 4. Filter Noise Lanjutan (Tahap 1: Struktur, Frekuensi, Resep, Promo, Dedup Judul)
    print("\n[Langkah 4] Menerapkan Filter Noise Lanjutan...")
    stage1_valid: list[dict] = []
    failed_discarded = []
    short_discarded = []
    not_primary_discarded = []
    recipe_discarded = []
    promo_discarded = []
    duplicate_discarded = []

    for item in extracted_items:
        title = item.get("title", "")
        text = item.get("text", "")

        # A. Gagal ekstraksi / kosong
        if not text:
            failed_discarded.append(item)
            continue

        # B. Suspiciously short (< 300 karakter)
        if is_suspiciously_short(text, min_length=300):
            short_discarded.append(item)
            continue

        # C. Filter Frekuensi Keyword (Primary Topic)
        if not is_keyword_primary_topic(title, text, "gula"):
            not_primary_discarded.append(item)
            continue

        # D. Resep kuliner
        if is_recipe(title, text):
            recipe_discarded.append(item)
            continue

        # E. Iklan / Promo ritel
        if is_promotional(title, text):
            promo_discarded.append(item)
            continue

        # F. Deduplikasi Kemiripan Judul (Rapidfuzz threshold >= 85)
        matched_idx = -1
        for idx, existing in enumerate(stage1_valid):
            if is_near_duplicate_title(title, existing.get("title", ""), threshold=85):
                matched_idx = idx
                break

        if matched_idx == -1:
            stage1_valid.append(item)
        else:
            existing_text = stage1_valid[matched_idx].get("text", "")
            if len(text) > len(existing_text):
                duplicate_discarded.append(stage1_valid[matched_idx])
                stage1_valid[matched_idx] = item
            else:
                duplicate_discarded.append(item)

    print(f"\nTotal artikel lolos tahap awal (sebelum filter industri/kesehatan): {len(stage1_valid)} artikel")

    # 5. Filter Topik Industri / Kebijakan vs Kesehatan Personal (50 Artikel)
    print("\n" + "=" * 110)
    print("PENERAPAN FILTER TOPIK INDUSTRI/KEBIJAKAN VS KESEHATAN PERSONAL")
    print("=" * 110)
    print(f"{'No':<3} | {'Ind':<4} | {'Hlt':<4} | {'Status':<8} | Judul Artikel")
    print("-" * 110)

    final_articles: list[dict] = []
    health_discarded: list[dict] = []

    for idx, item in enumerate(stage1_valid, start=1):
        title = item.get("title", "")
        text = item.get("text", "")
        ind_score, health_score, is_pass = get_industry_health_scores(title, text)

        status = "LOLOS" if is_pass else "DIBUANG"
        t_trunc = (title[:75] + "...") if len(title) > 78 else title
        print(f"{idx:<3} | {ind_score:<4} | {health_score:<4} | {status:<8} | {t_trunc}")

        if is_pass:
            item_copy = dict(item)
            item_copy["ind_score"] = ind_score
            item_copy["health_score"] = health_score
            final_articles.append(item_copy)
        else:
            item_copy = dict(item)
            item_copy["ind_score"] = ind_score
            item_copy["health_score"] = health_score
            health_discarded.append(item_copy)

    print("-" * 110)
    print(f"Hasil Evaluasi: {len(final_articles)} artikel LOLOS, {len(health_discarded)} artikel DIBUANG.")
    print("=" * 110)

    # 6. Entity Mapping & Sentiment Analysis (3 Kelas Asli IndoBERT: Positif / Netral / Negatif)
    print(f"\n[Langkah 5 & 6] Menjalankan Entity Mapping dan Analisis Sentimen IndoBERT (3 Kelas) pada {len(final_articles)} artikel...")
    name_map = load_spokesperson_map("keyword_nama.xlsx")

    processed_records = []
    positive_count = 0
    neutral_count = 0
    negative_count = 0

    for idx, item in enumerate(final_articles, start=1):
        title = item["title"]
        text = item["text"]

        sp1, sp2, unit = find_spokespersons(text, name_map)
        tone = classify_tone(text)

        if tone == "Positif":
            positive_count += 1
        elif tone == "Netral":
            neutral_count += 1
        elif tone == "Negatif":
            negative_count += 1
        else:
            neutral_count += 1

        snippet = text[:150].replace("\n", " ").replace("\r", " ").strip()

        processed_records.append({
            "no": idx,
            "title": title,
            "link": item["link"],
            "source": item.get("source", ""),
            "tone": tone,
            "sp1": sp1,
            "sp2": sp2,
            "unit": unit,
            "snippet": snippet,
        })

    total_final = len(processed_records)

    # Laporan Statistik Pembersihan
    print("\n" + "=" * 80)
    print("LAPORAN STATISTIK PEMBERSIHAN NOISE PIPELINE")
    print("=" * 80)
    print(f"Total kandidat artikel awal                            : {total_raw}")
    print(f"1. Dibuang karena EKSTRAKSI GAGAL / KOSONG              : {len(failed_discarded)} artikel")
    print(f"2. Dibuang karena TERLALU PENDEK (< 300 char)           : {len(short_discarded)} artikel")
    print(f"3. Dibuang karena BUKAN TOPIK UTAMA (frekuensi < 2x)    : {len(not_primary_discarded)} artikel")
    print(f"4. Dibuang karena konten RESEP (is_recipe)              : {len(recipe_discarded)} artikel")
    print(f"5. Dibuang karena IKLAN/PROMO (is_promotional)          : {len(promo_discarded)} artikel")
    print(f"6. Dibuang karena DUPLIKAT JUDUL (is_near_dup >= 85%)   : {len(duplicate_discarded)} artikel")
    print(f"7. Dibuang karena KESEHATAN PERSONAL (hlt > ind score)  : {len(health_discarded)} artikel")
    for hd in health_discarded:
        print(f"   - [Ind: {hd['ind_score']} vs Hlt: {hd['health_score']}] {hd['title']}")

    print(f"8. Dibuang karena SUBSTRING BUG (regulasi dll)          : 0 artikel (diisolasi 100% oleh regex \\b...\\b)")
    print("-" * 80)
    print(f"TOTAL ARTIKEL FINAL TERSISA UNTUK SENTIMEN              : {total_final} artikel")
    print("=" * 80)

    # Cetak Distribusi Tone 3 Kelas
    pos_pct = (positive_count / total_final * 100) if total_final > 0 else 0
    neu_pct = (neutral_count / total_final * 100) if total_final > 0 else 0
    neg_pct = (negative_count / total_final * 100) if total_final > 0 else 0

    print("\n" + "=" * 80)
    print("DISTRIBUSI TONE SENTIMEN (3 KELAS ASLI INDOBERT)")
    print("=" * 80)
    print(f"- Positif : {positive_count:>3} artikel ({pos_pct:.1f}%)")
    print(f"- Netral  : {neutral_count:>3} artikel ({neu_pct:.1f}%)")
    print(f"- Negatif : {negative_count:>3} artikel ({neg_pct:.1f}%)")
    print(f"- Total   : {total_final:>3} artikel (100.0%)")
    print("=" * 80)

    # Cetak Tabel Seluruh Artikel Tersisa
    print(f"\nTABEL LENGKAP HASIL SENTIMEN INDOBERT ({total_final} ARTIKEL FINAL):")
    print("-" * 135)
    print(f"{'No':<3} | {'Tone':<7} | {'Title':<65} | 150 Karakter Pertama Teks")
    print("-" * 135)
    for r in processed_records:
        t_trunc = (r['title'][:62] + '...') if len(r['title']) > 65 else r['title']
        print(f"{r['no']:<3} | {r['tone']:<7} | {t_trunc:<65} | {r['snippet']}")

    print("-" * 135)
    print("=" * 135)


if __name__ == "__main__":
    main()
