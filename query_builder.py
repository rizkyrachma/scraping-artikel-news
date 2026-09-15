"""
query_builder.py
Penyusunan search query Google News RSS dengan denylist filtering marketplace dan asset host.
"""

from urllib.parse import quote
from config import MARKETPLACE_BLOCKLIST, ASSET_HOST_BLOCKLIST, GOV_DOMAIN_SUFFIX


def build_media_query(
    keyword: str,
    blocklist: list[str] | None = None,
    asset_hosts: list[str] | None = None,
    encode: bool = True,
) -> str:
    """
    Menyusun query pencarian berita media dengan filter negatif (exclude marketplace & asset host).
    Tidak menggunakan filter 'site: OR' agar mencakup seluruh media nasional dan lokal.
    """
    if blocklist is None:
        blocklist = MARKETPLACE_BLOCKLIST
    if asset_hosts is None:
        asset_hosts = ASSET_HOST_BLOCKLIST

    all_blocks = blocklist + asset_hosts
    exclude_filter = " ".join(f"-site:{d}" for d in all_blocks)
    query = f"{keyword} {exclude_filter}".strip()
    return quote(query) if encode else query


def build_gov_query(keyword: str, encode: bool = True) -> str:
    """
    Menyusun query pencarian situs pemerintah (.go.id).
    """
    query = f"{keyword} site:{GOV_DOMAIN_SUFFIX}"
    return quote(query) if encode else query


def build_rss_url(encoded_query: str) -> str:
    """
    Menghasilkan URL Google News RSS berdasarkan query yang sudah di-encode.
    """
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=id&gl=ID&ceid=ID:id"
