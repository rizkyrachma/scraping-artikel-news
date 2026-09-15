"""
config.py
Konfigurasi filtering domain (denylist-first), blocklist marketplace/aset, dan loader dataset.
"""

from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd


def get_date_range():
    """
    Menghitung rentang tanggal dinamis: persis kemarin (H-1 dari hari eksekusi).
    Tidak menggunakan hardcode tanggal.
    """
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    return yesterday, yesterday


def is_published_yesterday(published_str: str) -> bool:
    """
    Memeriksa apakah tanggal publikasi artikel sama persis dengan 'kemarin'.
    Artikel yang lolos HANYA yang tanggal publikasinya persis sama dengan 'kemarin',
    bukan hari ini, bukan juga tanggal sebelum kemarin.
    """
    if not published_str:
        return False
    try:
        dt = pd.to_datetime(published_str, errors="coerce")
        if pd.isna(dt):
            return False
        yesterday_start, _ = get_date_range()
        return dt.date() == yesterday_start
    except Exception:
        return False

# Suffix domain pemerintah (otomatis diizinkan pada jalur terpisah)
GOV_DOMAIN_SUFFIX = ".go.id"

# Blocklist marketplace / e-commerce
MARKETPLACE_BLOCKLIST = [
    "shopee.co.id", "tokopedia.com", "bukalapak.com",
    "lazada.co.id", "blibli.com", "jd.id",
]

# Blocklist host aset kliping/video non-artikel
ASSET_HOST_BLOCKLIST = [
    "api.digivla.id",
]

# Blocklist platform media sosial / non-berita
SOCIAL_MEDIA_BLOCKLIST = [
    "youtube.com", "instagram.com", "tiktok.com",
    "wikipedia.org", "x.com", "facebook.com", "twitter.com",
]

# Blocklist ekstensi file non-artikel pada URL
ASSET_EXTENSION_BLOCKLIST = [
    ".pdf", ".mp4", ".jpg", ".jpeg", ".png", ".mp3",
]

# Pola URL komersial yang diabaikan
BLOCKED_URL_PATTERNS = ["jual", "beli", "produk", "harga", "toko", "review"]


def load_keywords(path: str | Path = "keyword_data.txt") -> list[str]:
    """
    Membaca keyword_data.txt, kembalikan list keyword (strip whitespace, buang baris kosong).
    """
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_spokesperson_map(path: str | Path = "keyword_nama.xlsx") -> dict[str, str]:
    """
    Membaca keyword_nama.xlsx menggunakan pandas.read_excel(),
    mengambil kolom 'nama' dan 'jabatan', lalu mengembalikan dictionary dengan:
    - key: nama dalam lowercase, whitespace dirapikan
    - value: jabatan dalam title case
    """
    df = pd.read_excel(path)

    # Standarisasi nama kolom ke huruf kecil dan strip whitespace
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "nama" not in df.columns or "jabatan" not in df.columns:
        raise ValueError(f"Kolom 'nama' dan 'jabatan' harus ada di file {path}. Kolom ditemukan: {list(df.columns)}")

    spokesperson_map = {}
    for _, row in df.iterrows():
        raw_nama = str(row["nama"]).strip() if pd.notna(row["nama"]) else ""
        raw_jabatan = str(row["jabatan"]).strip() if pd.notna(row["jabatan"]) else ""

        if not raw_nama:
            continue

        clean_nama = " ".join(raw_nama.split()).lower()
        clean_jabatan = " ".join(raw_jabatan.split()).title()

        spokesperson_map[clean_nama] = clean_jabatan

    return spokesperson_map
