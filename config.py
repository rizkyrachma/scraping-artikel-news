"""
config.py
Konfigurasi filtering domain (denylist-first), blocklist marketplace/aset, dan loader dataset.
"""

from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd


import os

def load_env_file(env_path: Path | str | None = None) -> None:
    """Membaca file .env jika ada dan memasukkan key-value ke os.environ jika belum ada."""
    if env_path is None:
        env_path = Path(__file__).parent / ".env"
    path = Path(env_path)
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

load_env_file()


def get_date_range(target_date: datetime | None = None):
    """
    Menghitung rentang tanggal dinamis: persis kemarin (H-1 dari hari eksekusi).
    Tidak menggunakan hardcode tanggal. Mendukung OVERRIDE_DATE di environment untuk pengujian.
    """
    if target_date is not None:
        d = target_date.date() if isinstance(target_date, datetime) else target_date
        return d, d
    override = os.environ.get("OVERRIDE_DATE", "").strip()
    if override:
        try:
            d = datetime.strptime(override, "%Y-%m-%d").date()
            return d, d
        except Exception:
            pass
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    return yesterday, yesterday


def get_date_folder(target_date: date | datetime | None = None) -> str:
    """
    Menghasilkan path folder terorganisir per tanggal: hasil_scrapping/<YYYY-MM-DD>
    Membuat folder jika belum ada (os.makedirs(folder, exist_ok=True)).
    Panggil fungsi ini di AWAL proses sebelum fetch keyword pertama.
    """
    if target_date is None:
        eval_date, _ = get_date_range()
    elif isinstance(target_date, datetime):
        eval_date = target_date.date()
    else:
        eval_date = target_date
    folder = f"hasil_scrapping/{eval_date.strftime('%Y-%m-%d')}"
    os.makedirs(folder, exist_ok=True)
    return folder


def is_published_yesterday(published_str: str, target_date: datetime | None = None) -> bool:
    """
    Memeriksa apakah tanggal publikasi artikel sama persis dengan 'kemarin'.
    Artikel yang lolos HANYA yang tanggal publikasinya persis sama dengan 'kemarin',
    bukan hari ini, bukan juga tanggal sebelum kemarin.
    Mendukung format absolut maupun relatif (misal '1 day ago' dari Serper).
    """
    if not published_str:
        return False
    try:
        dt = pd.to_datetime(published_str, errors="coerce")
        if pd.isna(dt):
            import dateparser
            dt = dateparser.parse(published_str)
            if dt is None:
                return False
        # Konversi timezone jika ada ke waktu lokal WIB (Asia/Jakarta)
        if dt.tzinfo is not None:
            dt = dt.tz_convert("Asia/Jakarta")
        elif str(published_str).endswith("Z"):
            dt = pd.to_datetime(published_str).tz_localize("UTC").tz_convert("Asia/Jakarta")
        yesterday_start, _ = get_date_range(target_date)
        return dt.date() == yesterday_start
    except Exception:
        return False


def is_single_word_keyword(keyword: str) -> bool:
    """
    Mengecek apakah keyword hanya terdiri dari satu kata.
    Contoh: 'gula' -> True, 'industri agro' -> False.
    Otomatis tanpa hardcode, dihitung dari panjang keyword.strip().split().
    """
    if not keyword:
        return False
    return len(keyword.strip().split()) == 1


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
    "linkedin.com",
]

# Blocklist portal lowongan kerja / karir
JOB_PORTAL_BLOCKLIST = [
    "glints.com", "kitalulus.com", "bebee.com", "jobstreet.co.id",
    "jobstreet.com", "kalibrr.com", "karir.com", "loker.id",
    "indeed.com", "jobsdb.com", "prosple.com",
]

# Blocklist ekstensi file non-artikel pada URL
ASSET_EXTENSION_BLOCKLIST = [
    ".pdf", ".mp4", ".jpg", ".jpeg", ".png", ".mp3",
]

# Pola URL komersial yang diabaikan
BLOCKED_URL_PATTERNS = ["jual", "beli", "produk", "harga", "toko", "review"]

# Pola URL lowongan kerja yang diabaikan
JOB_URL_PATTERNS = [
    "/lowongan", "/jobs/", "/job/", "/opportunities/jobs",
    "/career", "/karir", "/loker",
]


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


def load_spokesperson_details(path: str | Path = "keyword_nama.xlsx") -> list[dict]:
    """
    Membaca keyword_nama.xlsx secara lengkap termasuk unit_eselon, kategori, dan level,
    serta menghasilkan alias pencocokan nama yang fleksibel.
    """
    df = pd.read_excel(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    records = []
    for _, row in df.iterrows():
        raw_nama = str(row.get("nama", "")).strip() if pd.notna(row.get("nama")) else ""
        if not raw_nama:
            continue
        jabatan = str(row.get("jabatan", "")).strip() if pd.notna(row.get("jabatan")) else ""
        unit_eselon = str(row.get("unit_eselon", "-")).strip() if pd.notna(row.get("unit_eselon")) else "-"
        kategori = str(row.get("kategori", "")).strip() if pd.notna(row.get("kategori")) else ""
        level = str(row.get("level", "")).strip() if pd.notna(row.get("level")) else ""

        canonical_name = " ".join(raw_nama.split())
        lower_name = canonical_name.lower()

        aliases = [lower_name]
        # Buat variasi alias umum di media
        words = lower_name.split()
        if len(words) >= 3:
            aliases.append(" ".join(words[:2]))
        if "eko" in lower_name and ("s.a." in lower_name or "cahyanto" in lower_name):
            aliases.extend(["eko s.a. cahyanto", "eko sa cahyanto", "eko cahyanto"])
        elif "citra" in lower_name and "rapati" in lower_name:
            aliases.extend(["rr citra rapati", "rr. citra rapati", "citra rapati"])
        elif lower_name in ["m. rum", "m rum"]:
            aliases.extend(["m. rum", "m rum"])
        elif "putu" in lower_name and "juli" in lower_name:
            aliases.extend(["putu juli ardika", "putu juli"])
        elif "agus" in lower_name and "gumiwang" in lower_name:
            aliases.extend(["agus gumiwang kartasasmita", "agus gumiwang"])

        # Dedup alias mempertahankan urutan dari yang paling panjang ke pendek
        unique_aliases = []
        for a in sorted(set(aliases), key=len, reverse=True):
            if a and a not in unique_aliases:
                unique_aliases.append(a)

        records.append({
            "nama": canonical_name,
            "jabatan": jabatan,
            "unit_eselon": unit_eselon,
            "kategori": kategori,
            "level": level,
            "aliases": unique_aliases,
        })
    return records


def load_general_kemenperin_keywords(path: str | Path = "keyword_kemenperin.csv") -> list[str]:
    """Membaca daftar keyword umum Kemenperin."""
    if not os.path.exists(path):
        return ["kemenperin", "kementerian perindustrian", "menperin", "wamenperin", "kemenperin ri"]
    df = pd.read_csv(path)
    return [str(w).strip().lower() for w in df["keyword"].dropna() if str(w).strip()]


def load_ia_topic_map(path: str | Path = "keyword_topik_ia.csv") -> dict[str, dict]:
    """Membaca daftar 46 topik Ditjen Industri Agro beserta unit_eselon dan category."""
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    topic_map = {}
    for _, row in df.iterrows():
        kw = str(row.get("keyword", "")).strip().lower()
        if kw:
            topic_map[kw] = {
                "unit_eselon": str(row.get("unit_eselon", "IA")).strip(),
                "category": str(row.get("category", "03. Industri Agro")).strip(),
            }
    return topic_map

