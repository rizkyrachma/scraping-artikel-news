"""
test_investigate_10.py
Investigasi 10 artikel mencurigakan dan pengujian dedup judul.
"""
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import re
from rapidfuzz import fuzz
from fetch_news import search_keyword
from extract_content import extract_article_text
from relevance_filter import matches_word_boundary

def count_keyword_occurrences(text: str, keyword: str) -> int:
    if not text or not keyword:
        return 0
    pattern = rf"\b{re.escape(keyword)}\b"
    return len(re.findall(pattern, text, flags=re.IGNORECASE))

def is_keyword_primary_topic(title: str, text: str, keyword: str, min_content_occurrences: int = 2) -> bool:
    if not keyword:
        return False
    # 1. Cek kemunculan di judul
    if title and matches_word_boundary(keyword, title):
        return True
    # 2. Cek frekuensi kemunculan di isi artikel penuh
    if text and count_keyword_occurrences(text, keyword) >= min_content_occurrences:
        return True
    return False

def clean_title(t: str) -> str:
    if " - " in t:
        return t.rsplit(" - ", 1)[0].strip()
    return t.strip()

def is_near_duplicate_title(title_a: str, title_b: str, threshold: int = 85) -> bool:
    if not title_a or not title_b:
        return False
    if fuzz.ratio(title_a.lower().strip(), title_b.lower().strip()) >= threshold:
        return True
    if fuzz.ratio(clean_title(title_a).lower(), clean_title(title_b).lower()) >= threshold:
        return True
    return False

# Target 10 artikel yang dicurigai oleh user
SUSPICIOUS_KEYWORDS = [
    "Pelayanan Kesehatan Sampai ke Pintu Rumah, Home Care",
    "Homecare Jadi Cara Kecamatan Sumbersari",
    "Jumat Berkah, Polres Karimun Salurkan Bantuan Sembako",
    "Lewat Program Homecare Kelurahan Sumbersari",
    "Kisah Pilu Disabilitas Tuai Atensi",
    "Pasca Erupsi Sinabung, Kapolsek Simpang Empat",
    "Kunjungan Home Care Dispusip Dekatkan Pelayanan",
    "Polsek Sekar Lakukan Patroli Pastikan Harga Sembako",
    "Gubernur Kaltara Kenang Keramahan Warga Jateng, MTQ",
    "Kepedulian Polres Musi Rawas: Sisihkan Rezeki Demi",
]

def main():
    print("Mengambil artikel 'gula'...")
    raw = search_keyword("gula", delay=0.5)
    print(f"Total raw: {len(raw)}")

    # Cari artikel yang cocok
    matched_suspicious = []
    padang_items = []
    air_kelapa_items = []

    for item in raw:
        title = item["title"]
        for target in SUSPICIOUS_KEYWORDS:
            if target.lower() in title.lower():
                matched_suspicious.append(item)
                break
        if "padang" in title.lower() and "gula" in title.lower():
            padang_items.append(item)
        if "takaran air kelapa" in title.lower():
            air_kelapa_items.append(item)

    print(f"\nDitemukan {len(matched_suspicious)} artikel dari daftar 10 artikel yang dicurigai:")
    print("=" * 90)
    for idx, item in enumerate(matched_suspicious, start=1):
        text = extract_article_text(item["link"], max_length=8000)
        count = count_keyword_occurrences(text, "gula")
        has_in_title = matches_word_boundary("gula", item["title"])
        is_primary = is_keyword_primary_topic(item["title"], text, "gula")

        status = "LOLOS" if is_primary else "DIBUANG"
        print(f"{idx}. Judul: {item['title']}")
        print(f"   In Title? {has_in_title} | Muncul di isi: {count}x | Keputusan: [{status}]")
        print("-" * 90)

    print("\nPengujian Duplikat Padang:")
    print("=" * 90)
    for p in padang_items:
        print(f"- {p['title']} ({p['link']})")

    print("\nPengujian Duplikat Air Kelapa:")
    print("=" * 90)
    for a in air_kelapa_items:
        print(f"- {a['title']} ({a['link']})")

if __name__ == "__main__":
    main()
