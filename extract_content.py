"""
extract_content.py
Ekstraksi isi/konten teks artikel berita menggunakan trafilatura dengan fallback newspaper3k.
Mendukung resolusi/dekoding URL Google News RSS, pembatasan panjang teks (capping), dan deteksi artikel pendek.
"""

import trafilatura
from newspaper import Article  # type: ignore

try:
    import googlenewsdecoder  # type: ignore
except ImportError:
    googlenewsdecoder = None


def resolve_article_url(url: str) -> str:
    """
    Menyelesaikan URL Google News (news.google.com/rss/articles/...)
    menjadi URL asli situs penerbit.
    """
    if "news.google.com" in url and googlenewsdecoder is not None:
        try:
            res = googlenewsdecoder.new_decoderv1(url)
            if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
                return res["decoded_url"]
        except Exception:
            pass
    return url


def is_suspiciously_short(text: str, min_length: int = 300) -> bool:
    """
    Memeriksa apakah hasil ekstraksi teks mencurigakan karena terlalu pendek (< 300 karakter).
    """
    if not text:
        return False
    return len(text.strip()) < min_length


def extract_article_text(url: str, max_length: int = 8000) -> str:
    """
    Mengekstrak teks isi berita dari URL.
    Menggunakan trafilatura sebagai parser utama, dan newspaper3k sebagai fallback.
    Memotong teks ke max_length karakter jika melebihi batas dan mencetak warning log.
    """
    target_url = resolve_article_url(url)
    raw_text = ""

    # 1. Ekstraksi utama dengan trafilatura
    try:
        downloaded = trafilatura.fetch_url(target_url)
        if downloaded:
            text = trafilatura.extract(downloaded, favor_precision=True)
            if text and text.strip():
                raw_text = text.strip()
    except Exception:
        pass

    # 2. Fallback dengan newspaper3k jika trafilatura gagal / kosong
    if not raw_text:
        try:
            article = Article(target_url, language="id")
            article.download()
            article.parse()
            if article.text and article.text.strip():
                raw_text = article.text.strip()
        except Exception:
            pass

    if not raw_text:
        return ""

    # 3. Content Length Cap (default 8000 karakter)
    if len(raw_text) > max_length:
        print(f"[WARNING] Konten artikel ({len(raw_text)} chars) melebihi batas {max_length}. Dipotong untuk URL: {target_url}")
        return raw_text[:max_length]

    return raw_text
