"""
config.py
Konfigurasi filtering domain (denylist-first), blocklist marketplace/aset, dan loader dataset.
"""

from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd
import os
import time
import threading
from urllib.parse import urlparse

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

# Flag YouTube: dinonaktifkan sementara sesuai instruksi user (default: False)
ENABLE_YOUTUBE = os.environ.get("ENABLE_YOUTUBE", "false").lower() in ("true", "1", "yes")


def get_date_range(target_date: date | datetime | tuple | list | None = None):
    """
    Menghitung rentang tanggal dinamis: persis kemarin (H-1 dari hari eksekusi)
    atau rentang tanggal (start_date, end_date) jika diberikan.
    """
    if target_date is not None:
        if isinstance(target_date, (tuple, list)):
            d1 = target_date[0].date() if isinstance(target_date[0], datetime) else target_date[0]
            d2 = target_date[1].date() if isinstance(target_date[1], datetime) else target_date[1]
            return d1, d2
        d = target_date.date() if isinstance(target_date, datetime) else target_date
        return d, d
    override = os.environ.get("OVERRIDE_DATE", "").strip()
    if override:
        try:
            for sep in (":", "_sd_", "..", " to ", " - "):
                if sep in override:
                    p1, p2 = override.split(sep, 1)
                    return datetime.strptime(p1.strip(), "%Y-%m-%d").date(), datetime.strptime(p2.strip(), "%Y-%m-%d").date()
            d = datetime.strptime(override, "%Y-%m-%d").date()
            return d, d
        except Exception:
            pass
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    return yesterday, yesterday


def get_date_range_custom(target_date):
    """
    Override tanggal spesifik untuk pengujian/backfill (bukan rolling 'kemarin').
    Menerima target_date sebagai date, datetime, string format 'YYYY-MM-DD', atau tuple/list.
    """
    return get_date_range(target_date)


def get_date_folder(target_date: date | datetime | tuple | list | None = None) -> str:
    """
    Menghasilkan path folder terorganisir per tanggal atau rentang tanggal:
    hasil_scrapping/<YYYY-MM-DD> atau hasil_scrapping/<YYYY-MM-DD>_sd_<YYYY-MM-DD>
    Membuat folder jika belum ada (os.makedirs(folder, exist_ok=True)).
    """
    start_d, end_d = get_date_range(target_date)
    if start_d == end_d:
        folder = f"hasil_scrapping/{start_d.strftime('%Y-%m-%d')}"
    else:
        folder = f"hasil_scrapping/{start_d.strftime('%Y-%m-%d')}_sd_{end_d.strftime('%Y-%m-%d')}"
    os.makedirs(folder, exist_ok=True)
    return folder


def is_published_yesterday(published_str: str, target_date: date | datetime | tuple | list | None = None) -> bool:
    """
    Memeriksa apakah tanggal publikasi artikel berada dalam rentang target_date
    (persis kemarin atau rentang start_date..end_date).
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
        start_d, end_d = get_date_range(target_date)
        return start_d <= dt.date() <= end_d
    except Exception:
        return False


def is_single_word_keyword(keyword: str | list[str]) -> bool:
    """
    Mengecek apakah keyword dasar hanya terdiri dari satu kata.
    Contoh: 'gula' -> True, 'industri agro' -> False.
    Jika input berupa list varian (misal ['gula', 'industri gula']),
    atau query OR (misal '("gula" OR "industri gula")'),
    pengecekan otomatis dilakukan pada KEYWORD DASAR (kata kunci pokok).
    """
    if not keyword:
        return False
    if isinstance(keyword, (list, tuple)):
        if not keyword:
            return False
        return len(str(keyword[0]).strip().split()) == 1

    clean = str(keyword).strip()
    if clean.startswith("(") and " OR " in clean:
        first_part = clean.lstrip("(").split(" OR ")[0].strip().strip("\"'")
        return len(first_part.split()) == 1

    return len(clean.split()) == 1


def build_keyword_groups(path: str | Path = "keyword_data.txt") -> dict[str, list[str]]:
    """
    Membaca keyword_data.txt dan mengelompokkan otomatis:
    - 46 komoditas dasar (baris 1-46) sebagai key grup
    - Variannya ('industri X') dan frasa khusus ('industri rokok ilegal', 'industri gula rafinasi')
      digabungkan ke dalam list varian masing-masing komoditas dasar.
    Hasilnya berupa dictionary 46 grup dengan daftar varian frasa.
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        all_lines = [l.strip() for l in f if l.strip()]

    # Pisahkan base keywords dan variant lines secara dinamis (tanpa hardcode jumlah baris)
    base_keywords = [
        l for l in all_lines
        if not l.lower().startswith("industri ") or l.lower() == "industri agro"
    ]
    other_lines = [
        l for l in all_lines
        if l.lower().startswith("industri ") and l.lower() != "industri agro"
    ]

    groups: dict[str, list[str]] = {base: [base] for base in base_keywords}

    for line in other_lines:
        line_clean = line.strip()
        matched = False
        # 1. Cek pola langsung 'industri <base>'
        for base in base_keywords:
            if line_clean.lower() == f"industri {base.lower()}":
                if line_clean not in groups[base]:
                    groups[base].append(line_clean)
                matched = True
                break
        if not matched:
            # 2. Frasa khusus (misal 'industri gula rafinasi', 'industri rokok ilegal')
            candidates = [
                b for b in base_keywords
                if any(w in line_clean.lower().split() for w in b.lower().split())
            ]
            if candidates:
                best_base = max(candidates, key=lambda b: len(set(b.lower().split()) & set(line_clean.lower().split())))
                if line_clean not in groups[best_base]:
                    groups[best_base].append(line_clean)
                matched = True
    # Perkaya varian pencarian Google News agar tidak kehilangan artikel di lapangan:
    # 1. Rokok Ilegal: jurnalis sering tidak menulis 'djbc', melainkan 'rokok ilegal'
    if "djbc rokok ilegal" in groups:
        for extra in ["rokok ilegal"]:
            if extra not in groups["djbc rokok ilegal"]:
                groups["djbc rokok ilegal"].append(extra)

    # 2. Rokok Elektrik: jurnalis sering tidak menulis 'bnn', melainkan 'rokok elektrik' / 'rokok elektronik'
    if "bnn rokok elektrik" in groups:
        for extra in ["rokok elektrik", "rokok elektronik"]:
            if extra not in groups["bnn rokok elektrik"]:
                groups["bnn rokok elektrik"].append(extra)

    # 3. Gula Rafinasi: pastikan mencakup 'industri gula rafinasi'
    if "gula rafinasi" in groups:
        for extra in ["industri gula rafinasi"]:
            if extra not in groups["gula rafinasi"]:
                groups["gula rafinasi"].append(extra)

    return groups


def get_officials_query_variants(path: str | Path = "keyword_nama.xlsx", max_per_chunk: int = 7) -> list[list[str]]:
    """
    Mengambil representasi nama/alias paling efektif dari 13 pejabat Kemenperin
    di keyword_nama.xlsx untuk disusun menjadi query pencarian gabungan OR.
    Dipecah menjadi sub-grup (maksimal 7 nama per chunk) agar aman dari batas
    panjang query parser Google News RSS yang mengabaikan filter tanggal jika > 9 nama.
    """
    if not os.path.exists(path):
        return []
    details = load_spokesperson_details(path)
    query_parts = []
    for d in details:
        n = d.get("nama", "").strip()
        if not n:
            continue
        if "Muhammad Sarmuji" in n or "Sarmuji" in n:
            query_parts.append("Sarmuji")
        elif "Agus Gumiwang" in n:
            query_parts.append("Agus Gumiwang")
        elif "Eko S.A. Cahyanto" in n:
            query_parts.append("Eko Cahyanto")
        elif "Citra Rapati" in n:
            query_parts.append("Citra Rapati")
        else:
            query_parts.append(n)

    chunks = [query_parts[i : i + max_per_chunk] for i in range(0, len(query_parts), max_per_chunk)]
    return chunks


def load_pejabat_precision_mapping(path: str | Path = "pejabat_keyword_mapping.csv", active_only: bool = True) -> list[dict]:
    """
    Memuat daftar pemetaan pejabat dan keyword spesifik komoditas dari pejabat_keyword_mapping.csv.
    Jika active_only=True, hanya memuat 9 pejabat relevan (Menteri, Wamen, Sekjen, Irjen, Dirjen Agro,
    dan 4 Direktur Agro), mengecualikan 4 pejabat non-Agro yang berada di luar scope saat ini.
    """
    if not os.path.exists(path):
        return []
    import csv
    results = []
    out_of_scope_names = {"taufiek bawazier", "setia diarta", "reni yanita", "tri supondy"}
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nama = row.get("nama_pejabat", "").strip()
            jabatan = row.get("jabatan", "").strip()
            raw_kws = row.get("keyword_terkait", "").strip()
            if not nama:
                continue
            is_out_of_scope = (
                nama.lower() in out_of_scope_names
                or "di luar scope" in raw_kws.lower()
            )
            if active_only and is_out_of_scope:
                continue
            kws = [k.strip() for k in raw_kws.split(";") if k.strip() and "di luar scope" not in k.lower()]
            results.append({
                "nama": nama,
                "jabatan": jabatan,
                "keywords": kws,
                "is_out_of_scope": is_out_of_scope,
            })
    return results



# Suffix domain pemerintah (otomatis diizinkan pada jalur terpisah)
GOV_DOMAIN_SUFFIX = ".go.id"

# Blocklist marketplace / e-commerce
MARKETPLACE_BLOCKLIST = [
    "shopee.co.id", "tokopedia.com", "bukalapak.com",
    "lazada.co.id", "blibli.com", "jd.id",
    "astronauts.id", "grab.com", "researchgate.net", "bible.com",
]

# Blocklist host aset kliping/video non-artikel (api.digivla.id dialihkan ke modul OCR, bukan dibuang)
ASSET_HOST_BLOCKLIST = []

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

# Blocklist ekstensi file non-artikel pada URL (.pdf diarahkan ke pipeline OCR)
ASSET_EXTENSION_BLOCKLIST = [
    ".mp4", ".jpg", ".jpeg", ".png", ".mp3",
]

# Pola URL komersial yang diabaikan
BLOCKED_URL_PATTERNS = ["jual", "beli", "produk", "harga", "toko", "review"]

# Pola URL lowongan kerja yang diabaikan
JOB_URL_PATTERNS = [
    "/lowongan", "/jobs/", "/job/", "/opportunities/jobs",
    "/career", "/karir", "/loker",
]


# Daftar nama event pameran industri rutin/tahunan (agro, pangan, mamin, kemasan, furnitur)
# Terpisah dari 48 komoditas dasar untuk menangkap lonjakan liputan berbasis event
INDUSTRY_EVENT_KEYWORDS = [
    "Fi Asia Indonesia",
    "Trade Expo Indonesia",
    "SIAL InterFOOD",
    "Food & Hotel Indonesia",
    "AllPack Indonesia",
    "IFFINA",
    "Indo Livestock",
    "Agrinex Expo",
]


def load_industry_event_keywords() -> list[str]:
    """Mengembalikan daftar keyword nama event dan pameran industri agro/pangan rutin di Indonesia."""
    return list(INDUSTRY_EVENT_KEYWORDS)


# Daftar keyword institusi khusus / program strategis Kemenperin (frasa langsung)
INSTITUTIONAL_KEYWORDS = [
    "akademi komunitas bambu kemenperin",
]


def load_institutional_keywords() -> list[str]:
    """Mengembalikan daftar keyword institusi khusus Kemenperin (frasa langsung)."""
    return list(INSTITUTIONAL_KEYWORDS)



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
    out_of_scope_names = {"taufiek bawazier", "setia diarta", "reni yanita", "tri supondy"}
    for _, row in df.iterrows():
        raw_nama = str(row["nama"]).strip() if pd.notna(row["nama"]) else ""
        raw_jabatan = str(row["jabatan"]).strip() if pd.notna(row["jabatan"]) else ""
        if not raw_nama:
            continue
        clean_nama = " ".join(raw_nama.split()).lower()
        if clean_nama in out_of_scope_names:
            continue

        clean_jabatan = " ".join(raw_jabatan.split()).title()
        spokesperson_map[clean_nama] = clean_jabatan

    return spokesperson_map


def load_spokesperson_details(path: str | Path = "keyword_nama.xlsx") -> list[dict]:
    """
    Membaca keyword_nama.xlsx secara lengkap termasuk unit_eselon, kategori, dan level,
    serta menghasilkan alias pencocokan nama yang fleksibel.
    Mengecualikan 4 pejabat non-Agro (Taufiek Bawazier, Setia Diarta, Reni Yanita, Tri Supondy).
    """
    df = pd.read_excel(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    records = []
    out_of_scope_names = {"taufiek bawazier", "setia diarta", "reni yanita", "tri supondy"}
    for _, row in df.iterrows():
        raw_nama = str(row.get("nama", "")).strip() if pd.notna(row.get("nama")) else ""
        if not raw_nama:
            continue
        canonical_name = " ".join(raw_nama.split())
        lower_name = canonical_name.lower()
        if lower_name in out_of_scope_names:
            continue

        jabatan = str(row.get("jabatan", "")).strip() if pd.notna(row.get("jabatan")) else ""
        unit_eselon = str(row.get("unit_eselon", "-")).strip() if pd.notna(row.get("unit_eselon")) else "-"
        kategori = str(row.get("kategori", "")).strip() if pd.notna(row.get("kategori")) else ""
        level = str(row.get("level", "")).strip() if pd.notna(row.get("level")) else ""

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
        elif "sarmuji" in lower_name:
            aliases.extend(["muhammad sarmuji", "menperin sarmuji", "menteri perindustrian sarmuji", "m. sarmuji", "m sarmuji", "sarmuji"])
        elif "agus" in lower_name and "gumiwang" in lower_name:
            aliases.extend(["agus gumiwang kartasasmita", "agus gumiwang", "menperin agus gumiwang", "menteri perindustrian agus gumiwang"])
        elif "faisol" in lower_name and "riza" in lower_name:
            aliases.extend(["faisol riza", "wamenperin", "wakil menteri perindustrian"])

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


_last_log_time = time.time()
_heartbeat_thread = None
_heartbeat_lock = threading.Lock()


def log_granular(msg: str) -> None:
    """Mencetak log dengan flush seketika dan memperbarui stempel waktu heartbeat."""
    global _last_log_time
    _last_log_time = time.time()
    print(msg, flush=True)


def _heartbeat_worker() -> None:
    """Background worker yang mengirim tanda hidup jika tidak ada log baru dalam 30 detik."""
    while True:
        time.sleep(5)
        now = time.time()
        if now - _last_log_time >= 30:
            log_granular("   [MASIH BERJALAN] Belum ada update dalam 30 detik, proses tetap aktif...")


def start_heartbeat() -> None:
    """Memulai thread heartbeat latar belakang jika belum berjalan."""
    global _heartbeat_thread
    with _heartbeat_lock:
        if _heartbeat_thread is None or not _heartbeat_thread.is_alive():
            _heartbeat_thread = threading.Thread(target=_heartbeat_worker, daemon=True)
            _heartbeat_thread.start()


def format_display_url(item: dict) -> str:
    """Memformat URL atau nama media ringkas untuk ditampilkan di log progress live."""
    url = item.get("link", "") or item.get("resolved_url", "")
    media = item.get("media_name") or item.get("source") or ""
    try:
        p = urlparse(url)
        domain = p.netloc.replace("www.", "")
        if "news.google.com" in domain and media:
            clean_media = media.lower().replace(" ", "").replace(".com", "")
            return f"{clean_media}.com/..."
        path = p.path.strip("/")
        if len(path) > 30:
            path = path[:12] + "..." + path[-12:]
        return f"{domain}/{path}" if path else domain
    except Exception:
        return (media or url)[:35]

