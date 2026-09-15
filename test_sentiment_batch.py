"""
test_sentiment_batch.py
Script untuk:
1. Menyaring artikel keyword 'gula' (membuang kosong & suspiciously short < 300 karakter).
2. Melaporkan jumlah artikel yang tersisa.
3. Menjalankan analisis sentimen IndoBERT (sentiment.classify_tone) pada seluruh artikel tersisa.
4. Mencetak tabel hasil: No, Title, 150 Karakter Pertama, dan Tone.
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fetch_news import search_keyword
from extract_content import extract_article_text, is_suspiciously_short
from main import filter_valid_articles
from sentiment import classify_tone


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
    item_dict["is_suspiciously_short"] = is_suspiciously_short(text, min_length=300)
    return item_dict


def main():
    print("=" * 80)
    print("1. MEMULAI FETCH DAN EKSTRAKSI KONTEN KEYWORD 'GULA'")
    print("=" * 80)

    articles = search_keyword("gula", delay=0.5)
    print(f"Total artikel hasil fetch Google News RSS: {len(articles)}")

    extracted_list = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(extract_item, idx, item) for idx, item in enumerate(articles, start=1)]
        for f in as_completed(futures):
            extracted_list.append(f.result())

    extracted_list.sort(key=lambda x: x["index"])

    # 2. Filter Valid Articles (buang kosong dan suspiciously short < 300)
    valid_articles, discarded = filter_valid_articles(extracted_list, min_length=300)
    extracted_success = [a for a in extracted_list if a["text"]]
    short_discarded = [a for a in discarded if a["text"] and a["is_suspiciously_short"]]
    empty_discarded = [a for a in discarded if not a["text"]]

    print("\n" + "=" * 80)
    print("2. HASIL FILTER ARTIKEL VALID (SEBELUM SENTIMENT ANALYSIS)")
    print("=" * 80)
    print(f"Total artikel berhasil diekstrak           : {len(extracted_success)}")
    print(f"Dibuang karena 'is_suspiciously_short' (<300): {len(short_discarded)}")
    print(f"Dibuang karena gagal/kosong                : {len(empty_discarded)}")
    print(f"Artikel BERSIH yang siap dianalisis        : {len(valid_articles)} artikel")

    # 3. Klasifikasi Sentimen IndoBERT
    print("\n" + "=" * 80)
    print(f"3. MENJALANKAN INDOBERT SENTIMENT PADA SELURUH {len(valid_articles)} ARTIKEL BERSIH")
    print("=" * 80)

    results = []
    positive_count = 0
    negative_count = 0

    for idx, item in enumerate(valid_articles, start=1):
        text = item["text"]
        tone = classify_tone(text)
        if tone == "Positif":
            positive_count += 1
        else:
            negative_count += 1

        snippet = text[:150].replace("\n", " ").replace("\r", " ").strip()
        results.append({
            "no": idx,
            "title": item["title"],
            "snippet": snippet,
            "tone": tone,
        })

    # Cetak tabel
    print(f"{'No':<3} | {'Tone':<7} | {'Title':<60} | 150 Karakter Pertama Teks")
    print("-" * 120)
    for r in results:
        title_truncated = (r['title'][:57] + '...') if len(r['title']) > 60 else r['title']
        print(f"{r['no']:<3} | {r['tone']:<7} | {title_truncated:<60} | {r['snippet']}")

    print("\n" + "=" * 80)
    print("RINGKASAN HASIL ANALISIS SENTIMEN (TONE)")
    print("=" * 80)
    print(f"Total artikel dianalisis : {len(valid_articles)}")
    print(f"Tone POSITIF             : {positive_count} ({positive_count/len(valid_articles)*100:.1f}%)")
    print(f"Tone NEGATIF             : {negative_count} ({negative_count/len(valid_articles)*100:.1f}%)")
    print("=" * 80)


if __name__ == "__main__":
    main()
