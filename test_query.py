"""
test_query.py
Script pengujian pembentukan query dan verifikasi filter:
1. SOCIAL_MEDIA_BLOCKLIST pada is_valid_domain()
2. Filter relevansi berbasis judul (relevance_filter.is_likely_relevant)
3. Hasil akhir search_keyword("gula")
"""

import sys
import feedparser  # type: ignore

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from query_builder import build_media_query, build_gov_query, build_rss_url
from fetch_news import search_keyword, is_valid_domain
from relevance_filter import is_likely_relevant


def test_relevance_filter(keyword: str = "gula"):
    print("=" * 80)
    print(f"UJI FILTER RELEVANSI DAN SOCIAL MEDIA UNTUK KEYWORD: '{keyword.upper()}'")
    print("=" * 80)

    # 1. Fetch raw entries langsung dari feed
    raw_media_rss = build_rss_url(build_media_query(keyword))
    raw_gov_rss = build_rss_url(build_gov_query(keyword))

    feed_media = feedparser.parse(raw_media_rss)
    feed_gov = feedparser.parse(raw_gov_rss)

    all_raw_entries = feed_media.entries + feed_gov.entries
    print(f"\n1. Total artikel mentah dari Google News RSS : {len(all_raw_entries)}")
    print(f"   - Media Query : {len(feed_media.entries)}")
    print(f"   - Gov Query   : {len(feed_gov.entries)}")

    # 2. Filter domain (marketplace, asset host, social media, asset extension)
    valid_domain_entries = []
    social_media_rejected = []
    for entry in all_raw_entries:
        link = entry.get("link", "")
        source_href = entry.get("source", {}).get("href", "")
        if is_valid_domain(link) and (not source_href or is_valid_domain(source_href)):
            valid_domain_entries.append(entry)
        else:
            social_media_rejected.append(entry)

    print(f"\n2. Hasil Validasi Domain (setelah Marketplace, Asset Host & Social Media Blocklist):")
    print(f"   - Lolos domain valid  : {len(valid_domain_entries)} artikel")
    print(f"   - Dibuang blocklist    : {len(social_media_rejected)} artikel")
    if social_media_rejected:
        print(f"   - Contoh yang dibuang blocklist domain:")
        for e in social_media_rejected[:3]:
            print(f"     * [{e.get('source', {}).get('title', 'Unknown')}] {e.get('title')}")

    # 3. Analisis Relevance Filter berbasis Judul
    kept_by_relevance = []
    rejected_by_relevance = []

    for entry in valid_domain_entries:
        title = entry.get("title", "")
        if is_likely_relevant(title):
            kept_by_relevance.append(entry)
        else:
            rejected_by_relevance.append(entry)

    print(f"\n3. Hasil Filter Relevansi Judul (Industri vs Kesehatan/Gaya Hidup):")
    print(f"   - Artikel yang DIBUANG oleh relevance filter : {len(rejected_by_relevance)} artikel")
    print(f"   - Artikel yang TERSISA                       : {len(kept_by_relevance)} artikel")

    print(f"\n4. Contoh 5 Judul yang DIBUANG (topik kesehatan/gaya hidup tanpa konteks industri):")
    for idx, e in enumerate(rejected_by_relevance[:5], start=1):
        print(f"   {idx}. [{e.get('source', {}).get('title', '')}] {e.get('title')}")

    print(f"\n5. Contoh 5 Judul yang TERSISA (topik industri/ekonomi/kebijakan):")
    for idx, e in enumerate(kept_by_relevance[:5], start=1):
        print(f"   {idx}. [{e.get('source', {}).get('title', '')}] {e.get('title')}")

    # 4. Verifikasi fungsi search_keyword("gula") langsung dari fetch_news.py
    print("\n" + "=" * 80)
    print(f"VERIFIKASI LANGSUNG search_keyword('{keyword}')")
    print("=" * 80)
    actual_results = search_keyword(keyword, delay=0.5)
    print(f"Total hasil dari search_keyword('{keyword}'): {len(actual_results)} artikel")
    print("Contoh 3 hasil teratas dari fungsi:")
    for idx, res in enumerate(actual_results[:3], start=1):
        print(f"  {idx}. [{res['source']}] {res['title']}")


if __name__ == "__main__":
    test_relevance_filter("gula")
