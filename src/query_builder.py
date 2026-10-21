"""
query_builder.py
Penyusunan search query Google News RSS dengan denylist filtering marketplace dan asset host.
"""

from urllib.parse import quote
from config import MARKETPLACE_BLOCKLIST, ASSET_HOST_BLOCKLIST, GOV_DOMAIN_SUFFIX


def format_keyword_query(keyword: str | list[str]) -> str:
    """
    Memformat keyword menjadi ekspresi query pencarian.
    Jika input berupa list/tuple varian (misal ['gula', 'industri gula', 'industri gula rafinasi']),
    disusun menjadi: ("gula" OR "industri gula" OR "industri gula rafinasi")
    Jika berupa string tunggal, dikembalikan langsung.
    """
    if isinstance(keyword, (list, tuple)):
        clean_parts = []
        for k in keyword:
            k_clean = str(k).strip()
            if not (k_clean.startswith('"') and k_clean.endswith('"')):
                clean_parts.append(f'"{k_clean}"')
            else:
                clean_parts.append(k_clean)
        if len(clean_parts) == 1:
            return clean_parts[0]
        return f"({' OR '.join(clean_parts)})"
    return str(keyword).strip()


def build_media_query(
    keyword: str | list[str],
    blocklist: list[str] | None = None,
    asset_hosts: list[str] | None = None,
    encode: bool = True,
) -> str:
    """
    Menyusun query pencarian berita media dengan filter negatif (exclude marketplace & asset host).
    Mendukung list varian keyword yang digabungkan dengan OR: ("gula" OR "industri gula").
    """
    if blocklist is None:
        blocklist = MARKETPLACE_BLOCKLIST
    if asset_hosts is None:
        asset_hosts = ASSET_HOST_BLOCKLIST

    kw_str = format_keyword_query(keyword)
    all_blocks = blocklist + asset_hosts
    exclude_filter = " ".join(f"-site:{d}" for d in all_blocks)
    query = f"{kw_str} {exclude_filter}".strip()
    return quote(query) if encode else query


def build_gov_query(keyword: str | list[str], encode: bool = True) -> str:
    """
    Menyusun query pencarian situs pemerintah (.go.id).
    Mendukung list varian keyword yang digabungkan dengan OR: ("gula" OR "industri gula").
    """
    kw_str = format_keyword_query(keyword)
    query = f"{kw_str} site:{GOV_DOMAIN_SUFFIX}"
    return quote(query) if encode else query


def build_rss_url(encoded_query: str) -> str:
    """
    Menghasilkan URL Google News RSS berdasarkan query yang sudah di-encode.
    """
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=id&gl=ID&ceid=ID:id"
