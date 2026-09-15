"""
run_pipeline_test.py
Script untuk:
1. Menjalankan ekstraksi ulang keyword 'gula' dengan max_length cap (8000) dan deteksi suspiciously short (<300).
2. Menguji entity_mapper.py pada 5 artikel sampel relevan.
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import load_spokesperson_map
from fetch_news import search_keyword
from extract_content import extract_article_text, is_suspiciously_short, resolve_article_url
from entity_mapper import find_spokespersons


TARGET_5_SAMPLES = [
    "serunya naik lori di madukismo bantul",
    "cisdi: 9 dari 10 produk pangan kemasan",
    "program bongkar ratoon pg ngadiredjo kediri",
    "harga gula pasir lokal di pasar modern jawa barat",
    "gubernur khofifah tinjau pg ngadirejo kediri",
]


def match_target_sample(title: str) -> str | None:
    t = title.lower()
    for target in TARGET_5_SAMPLES:
        if target in t:
            return target
    return None


def fetch_and_extract_one(idx: int, item: dict) -> dict:
    title = item["title"]
    link = item["link"]
    resolved_link = resolve_article_url(link)

    # Ekstraksi dengan max_length cap = 8000
    try:
        text = extract_article_text(link, max_length=8000)
    except Exception:
        text = ""

    char_len = len(text)
    is_success = char_len > 0
    # Cek apakah artikel kena cap (panjang pas 8000)
    is_capped = (char_len >= 8000)
    # Cek apakah suspiciously short (< 300)
    is_short = is_suspiciously_short(text, min_length=300) if is_success else False

    return {
        "index": idx,
        "title": title,
        "link": link,
        "resolved_link": resolved_link,
        "text": text,
        "char_len": char_len,
        "is_success": is_success,
        "is_capped": is_capped,
        "is_short": is_short,
        "sample_key": match_target_sample(title),
    }


def main():
    print("=" * 80)
    print("BAGIAN 1: EKSTRAKSI ULANG KEYWORD 'GULA' DENGAN MAX_LENGTH CAP (8000)")
    print("=" * 80)

    articles = search_keyword("gula", delay=0.5)
    total_articles = len(articles)
    print(f"Total artikel diproses: {total_articles}")

    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {
            executor.submit(fetch_and_extract_one, idx, item): idx
            for idx, item in enumerate(articles, start=1)
        }
        for future in as_completed(future_map):
            results.append(future.result())

    results.sort(key=lambda x: x["index"])

    success_items = [r for r in results if r["is_success"]]
    fail_items = [r for r in results if not r["is_success"]]
    capped_items = [r for r in results if r["is_capped"]]
    short_items = [r for r in results if r["is_short"]]

    total_capped_chars = sum(r["char_len"] for r in success_items)
    avg_len_capped = total_capped_chars / len(success_items) if success_items else 0

    print("\n" + "=" * 80)
    print("LAPORAN STATISTIK EKSTRAKSI KONTEN SETELAH CAPPING")
    print("=" * 80)
    print(f"Total artikel               : {total_articles}")
    print(f"Berhasil diekstrak          : {len(success_items)} artikel")
    print(f"Gagal diekstrak             : {len(fail_items)} artikel")
    print(f"Kena Cap (dipotong >8000)   : {len(capped_items)} artikel")
    if capped_items:
        print("  Daftar artikel yang kena cap:")
        for c in capped_items:
            print(f"  - [{c['char_len']} chars] {c['title']}")
            print(f"    URL: {c['resolved_link']}")

    print(f"\nDitandai 'is_suspiciously_short' (<300 chars) : {len(short_items)} artikel")
    if short_items:
        print("  Daftar artikel terlalu pendek:")
        for s in short_items:
            print(f"  - [{s['char_len']} chars] {s['title']}")
            print(f"    Cuplikan: {s['text'][:100]}...")

    print(f"\nRata-rata panjang teks baru : {avg_len_capped:.1f} karakter per artikel")

    # BAGIAN 2: Uji Entity Mapper pada 5 Sampel Relevan
    print("\n" + "=" * 80)
    print("BAGIAN 2: UJI ENTITY MAPPER PADA 5 ARTIKEL SAMPEL RELEVAN")
    print("=" * 80)

    name_map = load_spokesperson_map("keyword_nama.xlsx")
    print(f"Daftar Pejabat yang Dimuat ({len(name_map)} nama):")
    for k, v in name_map.items():
        print(f"  - {k.title()}: {v}")

    # Ambil artikel sampel yang cocok
    sample_matches = {}
    for r in results:
        key = r["sample_key"]
        if key and key not in sample_matches and r["is_success"]:
            sample_matches[key] = r

    print("\nHasil Identifikasi Spokesperson & Unit Eselon:")
    print("-" * 80)

    sample_order = [
        ("Madukismo", "serunya naik lori di madukismo bantul"),
        ("CISDI", "cisdi: 9 dari 10 produk pangan kemasan"),
        ("Ngopibareng PG Ngadiredjo", "program bongkar ratoon pg ngadiredjo kediri"),
        ("Databoks Harga Gula", "harga gula pasir lokal di pasar modern jawa barat"),
        ("Gubernur Khofifah PG Ngadirejo", "gubernur khofifah tinjau pg ngadirejo kediri"),
    ]

    for label, key in sample_order:
        item = sample_matches.get(key)
        print(f"\n>>> Sampel: [{label}]")
        if item:
            title = item["title"]
            text = item["text"]
            sp1, sp2, unit = find_spokespersons(text, name_map)

            print(f"    Judul          : {title}")
            print(f"    Panjang Teks   : {len(text)} karakter")
            print(f"    Spokesperson 1 : '{sp1}'" if sp1 else "    Spokesperson 1 : (Tidak terdeteksi)")
            print(f"    Spokesperson 2 : '{sp2}'" if sp2 else "    Spokesperson 2 : (Tidak terdeteksi)")
            print(f"    Unit Eselon    : '{unit}'" if unit else "    Unit Eselon    : (Tidak terdeteksi)")
        else:
            print("    (Artikel tidak ditemukan dalam hasil fetch saat ini)")
        print("-" * 80)


if __name__ == "__main__":
    main()
