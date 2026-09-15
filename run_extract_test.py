"""
run_extract_test.py
Script untuk menguji extract_content.py pada seluruh artikel hasil search_keyword("gula").
Menggunakan ThreadPoolExecutor (max_workers=5) agar ekstraksi efisien namun tetap terkendali.
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fetch_news import search_keyword
from extract_content import extract_article_text, resolve_article_url

SUSPICIOUS_TITLES = [
    "berapa sendok gula yang aman dikonsumsi dalam sehari",
    "kenali buah musiman yang tinggi gula",
]


def is_suspicious_target(title: str) -> bool:
    t = title.lower()
    return any(target in t for target in SUSPICIOUS_TITLES)


def process_article(idx: int, item: dict) -> dict:
    title = item["title"]
    link = item["link"]
    resolved_link = resolve_article_url(link)

    try:
        text = extract_article_text(link)
    except Exception as e:
        text = ""
        err_msg = str(e)
    else:
        err_msg = "konten kosong / proteksi bot / timeout"

    is_success = bool(text and len(text.strip()) > 0)
    return {
        "index": idx,
        "title": title,
        "link": link,
        "resolved_link": resolved_link,
        "text": text if is_success else "",
        "is_success": is_success,
        "char_len": len(text) if is_success else 0,
        "err_msg": err_msg,
        "is_suspicious": is_suspicious_target(title),
    }


def main():
    print("=" * 80)
    print("MEMULAI EKSTRAKSI KONTEN UNTUK KEYWORD 'GULA'")
    print("=" * 80)

    articles = search_keyword("gula", delay=0.5)
    total_articles = len(articles)
    print(f"Total artikel yang akan diekstrak: {total_articles}\n")

    results = []
    # Jalankan dengan pool 5 worker terkendali
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_article = {
            executor.submit(process_article, idx, item): idx
            for idx, item in enumerate(articles, start=1)
        }
        for future in as_completed(future_to_article):
            res = future.result()
            results.append(res)

    # Urutkan kembali berdasarkan index awal
    results.sort(key=lambda x: x["index"])

    success_count = 0
    fail_count = 0
    total_chars = 0
    suspicious_items = []

    for item in results:
        idx = item["index"]
        title = item["title"]
        resolved_link = item["resolved_link"]
        is_success = item["is_success"]
        char_len = item["char_len"]
        text = item["text"]

        if is_success:
            status = f"berhasil diekstrak ({char_len} karakter)"
            success_count += 1
            total_chars += char_len
            snippet = text[:200].replace("\n", " ") + "..."
        else:
            status = f"gagal ({item['err_msg']})"
            fail_count += 1
            snippet = "(tidak ada teks)"

        print(f"[{idx}/{total_articles}] Title : {title}")
        print(f"       Status: {status}")
        print(f"       Link  : {resolved_link}")
        print(f"       200 Karakter Pertama: {snippet}")
        print("-" * 80)

        if item["is_suspicious"]:
            suspicious_items.append(item)

    # Tampilkan artikel khusus yang dicurigai noise secara lengkap
    print("\n" + "=" * 80)
    print("PEMERIKSAAN MENDALAM: ISI LENGKAP ARTIKEL YANG DICURIGAI NOISE")
    print("=" * 80)

    if not suspicious_items:
        print("Tidak ada artikel dengan target judul mencurigakan yang ditemukan.")
    else:
        for s_item in suspicious_items:
            print(f"\n>>> JUDUL : {s_item['title']}")
            print(f">>> LINK  : {s_item['resolved_link']}")
            print(">>> ISI LENGKAP ARTIKEL:")
            print("-" * 60)
            if s_item["text"]:
                print(s_item["text"])
            else:
                print("(Gagal mengekstrak isi teks artikel ini)")
            print("-" * 60)

    # Laporan Akhir
    avg_len = (total_chars / success_count) if success_count > 0 else 0
    print("\n" + "=" * 80)
    print("RINGKASAN EKSTRAKSI KONTEN")
    print("=" * 80)
    print(f"Total artikel diproses : {total_articles}")
    print(f"Berhasil diekstrak     : {success_count} artikel ({success_count/total_articles*100:.1f}%)")
    print(f"Gagal diekstrak        : {fail_count} artikel ({fail_count/total_articles*100:.1f}%)")
    print(f"Rata-rata panjang teks : {avg_len:.0f} karakter per artikel berhasil")
    print("=" * 80)


if __name__ == "__main__":
    main()
