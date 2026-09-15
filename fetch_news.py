"""
fetch_news.py
Pengambilan data Google News RSS feed, verifikasi denylist domain & ekstensi aset, serta deduplikasi artikel.
"""

import time
from urllib.parse import urlparse
import feedparser  # type: ignore

from query_builder import build_media_query, build_gov_query, build_rss_url
from config import (
    MARKETPLACE_BLOCKLIST,
    ASSET_HOST_BLOCKLIST,
    SOCIAL_MEDIA_BLOCKLIST,
    JOB_PORTAL_BLOCKLIST,
    ASSET_EXTENSION_BLOCKLIST,
    JOB_URL_PATTERNS,
    GOV_DOMAIN_SUFFIX,
)
from relevance_filter import is_likely_relevant
from rapidfuzz import fuzz



def is_domain_in_blocklist(netloc: str, blocklist: list[str]) -> bool:
    """Mengecek apakah domain sama persis atau merupakan subdomain dari blocklist."""
    for domain in blocklist:
        d = domain.lower()
        if netloc == d or netloc.endswith(f".{d}"):
            return True
    return False


def is_valid_domain(url: str) -> bool:
    """
    Validasi domain dan ekstensi URL dengan strategi denylist-first:
    - Tolak jika path berakhiran ekstensi aset (ASSET_EXTENSION_BLOCKLIST)
    - Tolak jika URL mengandung pola URL lowongan kerja (JOB_URL_PATTERNS)
    - Domain .go.id otomatis lolos (jalur terpisah)
    - Tolak jika netloc match MARKETPLACE_BLOCKLIST, ASSET_HOST_BLOCKLIST, SOCIAL_MEDIA_BLOCKLIST, atau JOB_PORTAL_BLOCKLIST
    - Terima domain lainnya
    """
    if not url:
        return False

    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    full_url = url.lower()

    # 1. Tolak jika match ekstensi aset non-artikel (.pdf, .mp4, dll.)
    if any(path.endswith(ext.lower()) for ext in ASSET_EXTENSION_BLOCKLIST):
        return False

    # 2. Tolak pola path/URL lowongan kerja
    if any(p in full_url for p in JOB_URL_PATTERNS):
        return False

    # 3. Domain .go.id tetap otomatis lolos (jalur terpisah)
    if netloc.endswith(GOV_DOMAIN_SUFFIX) or f"{GOV_DOMAIN_SUFFIX}:" in netloc:
        return True

    # 4. Tolak jika domain atau subdomain match marketplace, host aset, media sosial, atau portal loker
    if is_domain_in_blocklist(netloc, MARKETPLACE_BLOCKLIST):
        return False
    if is_domain_in_blocklist(netloc, ASSET_HOST_BLOCKLIST):
        return False
    if is_domain_in_blocklist(netloc, SOCIAL_MEDIA_BLOCKLIST):
        return False
    if is_domain_in_blocklist(netloc, JOB_PORTAL_BLOCKLIST):
        return False

    # 5. Terima domain media apa pun yang tersisa
    return True


def clean_title_suffix(raw_title: str, source_title: str | None) -> str:
    """
    Menghapus suffix ' - <source_title>' dari judul mentah jika ada.
    Menggunakan pencocokan exact suffix berdasarkan entry.source.title dari feedparser,
    BUKAN split ' - ' membabi-buta, sehingga nama media yang mengandung tanda strip
    (contoh: 'DINAS PERPUSTAKAAN DAN KEARSIPAN - Kabupaten Sidoarjo') tidak terpotong keliru.
    """
    if not raw_title:
        return ""
    title = raw_title.strip()
    if source_title:
        clean_source = source_title.strip()
        suffix = f" - {clean_source}"
        while title.endswith(suffix) or title.lower().endswith(suffix.lower()):
            title = title[:-len(suffix)].strip()
    return title


def search_keyword(keyword: str, delay: float = 3.5) -> list[dict]:
    """
    Mengambil berita untuk satu keyword dari Google News RSS (media query dan gov query).
    Menerapkan validasi domain, ekstraksi media_name, pembersihan title, serta filter relevansi.
    """
    results = []
    for query_fn in (build_media_query, build_gov_query):
        encoded = query_fn(keyword)
        rss_url = build_rss_url(encoded)
        feed = feedparser.parse(rss_url)

        for entry in feed.entries:
            link = entry.get("link", "")
            source_info = entry.get("source", {})
            source_href = source_info.get("href", "") if isinstance(source_info, dict) else ""
            raw_source_title = source_info.get("title") if isinstance(source_info, dict) else None
            source_title = str(raw_source_title).strip() if raw_source_title else None

            # 1. Validasi URL link dan URL domain asli penerbit
            if not is_valid_domain(link) or (source_href and not is_valid_domain(source_href)):
                continue

            # 2. Bersihkan suffix nama media dari judul mentah
            raw_title = entry.get("title", "")
            clean_title = clean_title_suffix(raw_title, source_title)

            # 3. Filter relevansi berbasis judul (buang topik kesehatan/lifestyle murni)
            if not is_likely_relevant(clean_title):
                continue

            results.append({
                "keyword": keyword,
                "title": clean_title,
                "raw_title": raw_title,
                "link": link,
                "media_name": source_title,
                "source": source_title or "",
                "source_url": source_href,
                "published": entry.get("published", ""),
            })

        time.sleep(delay)

    return results


def dedup_by_link(items: list[dict]) -> list[dict]:
    """
    Deduplikasi hasil berdasarkan URL link (tanpa parameter query string).
    """
    seen = set()
    unique = []
    for item in items:
        key = item["link"].split("?")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def is_near_duplicate_title(title_a: str, title_b: str, threshold: int = 85) -> bool:
    """
    Mengecek apakah dua judul artikel hampir duplikat menggunakan rapidfuzz.fuzz.ratio().
    Memeriksa kemiripan judul asli dan judul setelah dibersihkan dari suffix sumber berita (' - Media').
    """
    if not title_a or not title_b:
        return False

    # 1. Kemiripan judul asli
    if fuzz.ratio(title_a.lower().strip(), title_b.lower().strip()) >= threshold:
        return True

    # 2. Kemiripan judul setelah strip nama penerbit Google News (" - <Media>")
    def clean(t: str) -> str:
        return t.rsplit(" - ", 1)[0].strip() if " - " in t else t.strip()

    if fuzz.ratio(clean(title_a).lower().strip(), clean(title_b).lower().strip()) >= threshold:
        return True

    return False


def dedup_by_title(items: list[dict], threshold: int = 85) -> list[dict]:
    """
    Deduplikasi artikel berbasis kemiripan judul (rapidfuzz).
    Diterapkan sebagai lapis dedup tambahan setelah dedup_by_link().
    Jika ditemukan artikel dengan judul mirip (>= threshold), simpan artikel
    yang isinya lebih lengkap/panjang.
    """
    unique: list[dict] = []
    for item in items:
        title = item.get("title") or item.get("Title") or ""
        text = item.get("text", "")
        matched_idx = -1

        for idx, existing in enumerate(unique):
            if is_near_duplicate_title(title, existing.get("title", ""), threshold):
                matched_idx = idx
                break

        if matched_idx == -1:
            unique.append(item)
        else:
            # Simpan artikel yang isinya lebih lengkap / panjang
            existing_text = unique[matched_idx].get("text", "")
            if len(text) > len(existing_text):
                unique[matched_idx] = item

    return unique


def collect_all(keywords: list[str], delay: float = 1.0) -> list[dict]:
    """
    Mengumpulkan dan menduplikasi hasil pencarian untuk seluruh daftar keyword
    (dedup berbasis URL link dilanjutkan dedup berbasis kemiripan judul).
    """
    all_results = []
    for kw in keywords:
        all_results.extend(search_keyword(kw, delay=delay))
    link_deduped = dedup_by_link(all_results)
    return dedup_by_title(link_deduped)

