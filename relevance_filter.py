"""
relevance_filter.py
Filter relevansi artikel berbasis judul dan cuplikan teks menggunakan pencocokan word boundary (regex \\b...\\b):
1. Menyaring artikel non-industri (kesehatan/gaya hidup murni)
2. Menyaring konten resep/kuliner (is_recipe)
3. Menyaring materi promosi/iklan ritel (is_promotional)
"""

import re
from urllib.parse import urlparse


def is_foreign_noise_domain(url: str) -> bool:
    """
    Menolak domain luar negeri non-relevan seperti .vn (Vietnam) yang mengindeks artikel lokal berbahasa asing/auto-translate.
    """
    if not url:
        return False
    try:
        netloc = urlparse(url).netloc.lower().split(":")[0]
        return netloc.endswith(".vn")
    except Exception:
        return False


def is_pdf_document(url: str = "", title: str = "", sumber_data: str = "") -> bool:
    """
    Mendeteksi dokumen PDF agar tidak diambil / diblokir total:
    - Sumber Data bernilai PDF
    - Ekstensi atau pola URL memuat .pdf, /pdf/, /unduh/, /download/, digivla.id
    - Judul berakhiran .pdf atau mengandung [PDF] / (PDF)
    """
    if sumber_data and str(sumber_data).upper() == "PDF":
        return True
    u = (url or "").lower()
    if any(p in u for p in [".pdf", "/pdf/", "digivla.id", "/unduh/", "/download/"]):
        return True
    t = (title or "").lower()
    if t.endswith(".pdf") or "[pdf]" in t or "(pdf)" in t:
        return True
    return False


# Kata kunci konteks industri/ekonomi
INDUSTRY_CONTEXT_WORDS = [
    "industri", "ekspor", "impor", "produksi", "pabrik", "kemenperin",
    "kementerian", "perdagangan", "komoditas", "investasi", "harga",
    "ton", "kuintal", "petani", "perkebunan", "swasembada", "giling",
    "rendemen", "tebu",
]

# Kata kunci artikel kesehatan/gaya hidup murni
HEALTH_LIFESTYLE_WORDS = [
    "gula darah", "diabetes", "kalori", "diet", "kesehatan tubuh",
    "manfaat", "efek samping", "penyakit", "gejala", "kolesterol",
    "behel", "kawat gigi", "skors", "gigi berlubang",
]

# Kata kunci konten resep / kuliner
RECIPE_WORDS = [
    "resep", "bahan-bahan", "cara membuat", "cara memasak", "sendok teh",
    "sendok makan", "bumbu halus", "adonan", "kukus", "panggang", "tumis",
    "tips membuat", "cara seduh", "tips memasak",
]

# Kata kunci promosi / iklan ritel
PROMO_WORDS = [
    "syarat dan ketentuan", "syarat & ketentuan", "periode promo",
    "dapatkan", "diskon", "supermarket", "minimal pembelian",
    "minimum transaksi", "cashback", "voucher", "katalog promo",
    "harga promo", "promo bca", "promo", "katalog", "brosur",
    "promo mingguan", "promo ssr", "promo jsm",
]


def matches_word_boundary(pattern: str, text: str) -> bool:
    """
    Pencocokan berbasis word boundary (\\b...\\b) agar tidak salah mencocokkan substring
    (contoh: 'gula' tidak boleh mencocokkan 'regulasi').
    """
    if not text or not pattern:
        return False
    return bool(re.search(rf"\b{re.escape(pattern)}\b", text, flags=re.IGNORECASE))


def any_word_boundary_match(word_list: list[str], text: str) -> bool:
    """
    Mengecek apakah salah satu kata/frasa dalam word_list cocok dengan word boundary pada teks.
    """
    if not text or not word_list:
        return False
    pattern = r"\b(" + "|".join(re.escape(w) for w in word_list) + r")\b"
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


# Pola indikator interaksi / polling / Call-to-Action (CTA) media sosial (Shorts, Reels, TikTok)
SOCIAL_MEDIA_ENGAGEMENT_PATTERNS = [
    r"\bshare\s+di\s+kolom\s+komentar\b",
    r"\btulis\s+di\s+kolom\s+komentar\b",
    r"\btulis\s+komentar(mu| kalian| sobat)?\b",
    r"\bkomen\s+di\s+bawah\b",
    r"\bkomentar\s+di\s+bawah\b",
    r"\btinggalkan\s+komentar\b",
    r"\bmenurut\s+(kamu|mu|kalian|sobat)\b",
    r"\bgimana\s+menurut\s+(kamu|mu|kalian|sobat)\b",
    r"\bbagaimana\s+menurut\s+(kamu|mu|kalian|sobat)\b",
    r"\bshare\s+pendapat(mu| kalian| sobat)?\b",
    r"\byuk\s+share\b",
    r"\bshare.*yuk\b",
    r"\bjangan\s+lupa\s+(like|subscribe)\b",
]

_SOCIAL_ENGAGEMENT_REGEX = re.compile("|".join(SOCIAL_MEDIA_ENGAGEMENT_PATTERNS), re.IGNORECASE)


def is_social_media_engagement_noise(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi konten interaktif media sosial (YouTube Shorts / Reels / TikTok)
    berupa polling, Q&A santai, atau ajakan komentar (Call-to-Action) yang bukan
    berita substantif kebijakan industri atau data komoditas.
    """
    title_clean = (title or "").strip()
    if not title_clean:
        return False
    return bool(_SOCIAL_ENGAGEMENT_REGEX.search(title_clean))


# =====================================================================================
# TAHAP 1: Pola Struktural Murah Tanpa AI
# =====================================================================================

def has_phone_number_or_wa_in_title(title: str = "") -> bool:
    """
    1. Deteksi nomor telepon / WhatsApp di judul:
    Regex pola nomor HP Indonesia (08xx, +628xx, 628xx) atau prefix WA/Telp.
    Digunakan untuk membuang iklan/listing bisnis, bukan artikel berita.
    Contoh: 'Search - WA 0859 3970 0884 [[Hatiga Furniture]]...', 'Jual Mebel WA 081234567890'.
    """
    if not title:
        return False
    # Prefix eksplisit WA / Telp / Hubungi / Call
    if re.search(r"\b(?:wa|whatsapp|telp|no\.?\s*hp|call|hubungi|kontak)\b[\s.:-]*\+?[0-9\s.-]{7,18}", title, re.IGNORECASE):
        return True
    # Pola nomor HP Indonesia mandiri: r'0\d{2,4}[-\s]?\d{3,4}[-\s]?\d{3,4}'
    if re.search(r"\b0\d{2,4}[-\s]?\d{3,4}[-\s]?\d{3,4}\b", title):
        return True
    # Pola nomor HP internasional (+628xx atau 628xx) dengan 9-14 digit angka
    for m in re.finditer(r"\b(?:\+?62|0)8[1-9][0-9\s.-]{6,16}\b", title):
        digits = re.sub(r"\D", "", m.group(0))
        if 9 <= len(digits) <= 14:
            return True
    return False


AGGREGATOR_PLACEHOLDER_PREFIXES = [
    r"^berita\s+(terbaru|terkini|hari\s+ini)(\s+hari\s+ini)?\s*[-–—:]\s*",
    r"^(kumpulan\s+berita|berita\s+dan\s+informasi)\b",
    r"^(tag|topik|indeks\s+berita)\s*[-–—:]\s*",
]
_AGGREGATOR_REGEX = re.compile("|".join(AGGREGATOR_PLACEHOLDER_PREFIXES), re.IGNORECASE)


def is_aggregator_placeholder_title(title: str = "") -> bool:
    """
    2. Deteksi halaman placeholder agregator / kategori / tag arsip otomatis:
    Pola 'Berita Terbaru Hari Ini - {apa saja}', 'Berita Terkini - {apa saja}',
    'Kumpulan Berita {apa saja}', 'Tag: {apa saja}' tanpa judul artikel spesifik.
    """
    if not title:
        return False
    t_clean = title.strip().lower()
    return bool(_AGGREGATOR_REGEX.search(t_clean))


def is_photo_stock_gallery_noise(title: str = "", text: str = "") -> bool:
    """
    3. Deteksi halaman galeri foto / stock image:
    Title mengandung kombinasi angka+'+' diikuti 'Foto', atau mengandung
    frasa 'pictures', 'stock photo', 'download gratis', 'unduh gratis'
    bersamaan dengan 'gambar'/'background'.
    Contoh: '84+ Foto Stik Biskuit Pictures, Gambar Dan Background Untuk Unduh Gratis'.
    """
    if not title:
        return False
    t_lower = title.lower()
    # Angka + '+' diikuti 'Foto' (misal: '84+ Foto', '900 + Foto')
    if re.search(r"\b\d+\s*\+\s*foto\b", t_lower):
        return True
    if re.search(r"\b\d+\+?\s+foto\b.*\b(pictures|gambar|background)\b.*\b(unduh|download)\s+gratis\b", t_lower):
        return True
    if re.search(r"pictures,\s*gambar\s+dan\s+background\s+untuk\s+(unduh|download)\s+gratis", t_lower):
        return True
    has_stock = any(s in t_lower for s in ["stock photo", "stock photography", "royalty-free", "royalty free"])
    if has_stock:
        return True
    has_gallery_terms = any(s in t_lower for s in ["pictures", "gambar dan background", "vektor & foto", "vektor dan foto", "images", "download gratis", "unduh gratis"])
    has_image_terms = any(g in t_lower for g in ["gambar", "background", "foto", "vektor"])
    if has_gallery_terms and has_image_terms and any(d in t_lower for d in ["unduh gratis", "download gratis", "free download"]):
        return True
    if re.search(r"^\d+[\d.,]*\+?\s+(foto|gambar|vektor)\s+.*\b(gratis|free)\b", t_lower):
        return True
    return False


DONATION_CAMPAIGN_PATTERNS = [
    r"^campaign\s*[-–—:]",
    r"\b(galang\s+dana|penggalangan\s+dana|donasi\s+online|bantu\s+wujudkan|patungan\s+untuk|sedekah\s+subuh|sedekah\s+jariyah|wakaf\s+produktif)\b",
    r"\b(kitabisa|amalsholeh|ayobantu|rumahzakat|dompetdhuafa|wecare\.id)\b",
    r"\b(sedekah|infaq|zakat|donasi)\s+(untuk\s+pembangunan|musholla|masjid|yatim|dhuafa|pesantren)\b",
    r"\b(bantu\s+renovasi|renovasi\s+musholla|pembangunan\s+musholla|pembangunan\s+masjid)\b",
]
_DONATION_REGEX = re.compile("|".join(DONATION_CAMPAIGN_PATTERNS), re.IGNORECASE)


def is_donation_campaign_noise(title: str = "", text: str = "") -> bool:
    """
    4. Deteksi campaign donasi / crowdfunding / sedekah:
    Title diawali 'Campaign -' atau memuat 'bantu wujudkan', 'galang dana',
    nama platform donasi umum (Kitabisa, dll), atau sedekah pembangunan ibadah.
    Contoh: 'Campaign - Bantu Wujudkan Musholla Terang untuk Pejuang Iman...'.
    """
    if not title:
        return False
    t_lower = title.lower()
    if _DONATION_REGEX.search(t_lower):
        return True
    if "wujudkan" in t_lower and any(w in t_lower for w in ["musholla", "masjid", "pesantren", "donasi", "sedekah", "bantu"]):
        return True
    return False


SCHOOL_PREFIX_PATTERN = r"^(profil\s+|akreditasi\s+|sejarah\s+)?(smk|smkn|sma|sman|smp|smpn|sd|sdn|madrasah|man|mts|mis|universitas|institut|politeknik|akademi|sekolah tinggi)\b"
SCHOOL_DIRECTORY_PATTERN = r"\b(data pokok pendidikan|dapodik|profil sekolah|akreditasi sekolah)\b"

EDUCATIONAL_JOURNALISTIC_VERBS = {
    "resmikan", "meresmikan", "gelar", "menggelar", "adakan", "mengadakan",
    "umumkan", "mengumumkan", "raih", "meraih", "juara", "kunjungi", "mengunjungi",
    "lepas", "melepas", "teken", "tandatangani", "menandatangani", "terima", "menerima",
    "buka", "membuka", "luncurkan", "meluncurkan", "ciptakan", "menciptakan",
    "inovasi", "kembangkan", "kolaborasi", "kerjasama", "kerja sama", "bantu",
    "dukung", "dorong", "siapkan", "tinjau", "meninjau", "panen", "produksi",
    "pamerkan", "wisuda", "workshop", "pelatihan", "sosialisasi", "seminar",
    "gagas", "rilis", "pameran", "capai", "mencapai",
}


def is_static_educational_profile_noise(title: str = "", text: str = "") -> bool:
    """
    5. Deteksi profil sekolah / institusi pendidikan tanpa konten berita:
    Title berpola nama sekolah ('SMK Negeri...', 'SMA...', 'SMP...', 'Universitas...', 'Politeknik...')
    TANPA kata kerja berita di sekitarnya ('resmikan', 'gelar', 'umumkan', 'raih', 'capai', 'luncurkan', dst).
    Contoh: 'SMK Negeri 4 Teknologi dan Rekayasa Sarmi', 'SMK Negeri 5 Seni Dan Industri Kreatif Kota Jayapura'.
    """
    if not title:
        return False
    t_clean = title.strip().lower()

    is_school = bool(re.search(SCHOOL_PREFIX_PATTERN, t_clean)) or bool(re.search(SCHOOL_DIRECTORY_PATTERN, t_clean))
    if not is_school:
        return False

    # Pengecualian mutlak: unit pendidikan resmi Kemenperin
    if "kemenperin" in t_clean or "kementerian perindustrian" in t_clean:
        return False

    # Jika mengandung kata kerja jurnalistik, LOLOSKAN (bukan profil statis)
    has_news_verb = any_word_boundary_match(list(EDUCATIONAL_JOURNALISTIC_VERBS), t_clean)
    if has_news_verb:
        return False

    return True


def is_non_article_structural_noise(title: str = "") -> bool:
    """
    BAGIAN 1: FILTER POLA STRUKTURAL (RULE-BASED, GRATIS, DIJALANKAN LEBIH DULU)
    Mendeteksi 5 pola noise non-artikel di judul:
    1. NOMOR TELEPON/WA DI JUDUL (iklan/listing bisnis)
    2. HALAMAN PLACEHOLDER AGREGATOR ('Berita Terbaru Hari Ini - {topik}' dll)
    3. HALAMAN GALERI FOTO/STOCK (angka+'+' diikuti 'Foto', stock photo, pictures, download gratis)
    4. CAMPAIGN DONASI ('Campaign -', 'bantu wujudkan', 'galang dana', platform Kitabisa, dll)
    5. PROFIL SEKOLAH/INSTITUSI STATIS (nama sekolah tanpa kata kerja berita di sekitarnya)
    """
    if not title:
        return False
    if has_phone_number_or_wa_in_title(title):
        return True
    if is_aggregator_placeholder_title(title):
        return True
    if is_photo_stock_gallery_noise(title):
        return True
    if is_donation_campaign_noise(title):
        return True
    if is_static_educational_profile_noise(title):
        return True
    return False


def is_likely_relevant(title: str) -> bool:
    """
    Memeriksa relevansi awal berdasarkan judul menggunakan regex word boundary:
    - Return False jika judul memuat pola struktural murah tanpa AI (nomor HP/WA,
      agregator placeholder, galeri stock foto, campaign donasi, profil sekolah statis).
    - Return False jika judul mengandung salah satu HEALTH_LIFESTYLE_WORDS
      DAN tidak mengandung satu pun INDUSTRY_CONTEXT_WORDS.
    - Return False jika judul merupakan ajakan interaksi / CTA komentar media sosial.
    - Return True untuk kasus lainnya.
    """
    if not title:
        return True

    # Tahap 1: Pola struktural murah tanpa AI
    if is_non_article_structural_noise(title):
        return False
    if is_social_media_engagement_noise(title):
        return False

    title_lower = title.lower()
    # Tolak judul event non-Agro / otomotif murni
    if any(p in title_lower for p in ["gaikindo auto week", "pameran otomotif", "penjualan mobil", "dealer mobil", "pembiayaan kendaraan"]):
        return False

    has_health_word = any_word_boundary_match(HEALTH_LIFESTYLE_WORDS, title)
    has_industry_word = any_word_boundary_match(INDUSTRY_CONTEXT_WORDS, title)

    if has_health_word and not has_industry_word:
        return False

    return True


def is_recipe(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi apakah artikel merupakan konten resep / panduan memasak kuliner:
    - Judul memuat indikator resep ('resep', 'cara membuat', 'cara memasak', 'cara buat', 'yuk buat', 'yuk bikin', 're-cook', dll.)
    - Atau snippet 1500 karakter awal memuat indikator resep dan takaran bahan berulang.
    """
    title_text = title or ""
    snippet = text[:1500] if text else ""

    # 1. Cek indikator kata resep di judul
    if any_word_boundary_match(["resep", "cara membuat", "cara memasak", "cara buat", "yuk buat", "yuk bikin", "re-cook", "resep praktis"], title_text):
        return True
    if any_word_boundary_match(RECIPE_WORDS, snippet):
        return True

    # 2. Cek pola format takaran bahan berulang di snippet awal teks
    measurement_pattern = r"\b\d+[\s\w]*(gram|gr|ml|mililiter|sendok makan|sendok teh|sdm|sdt|butir|lembar|siung|bungkus|cup)\b"
    matches = re.findall(measurement_pattern, snippet, flags=re.IGNORECASE)
    if len(matches) >= 2 and any_word_boundary_match(["bahan", "bumbu", "resep", "cara memasak", "langkah membuat", "masak", "goreng", "tumis"], snippet):
        return True

    return False


# Kata kunci indikator promosi ritel / supermarket / belanja konsumen langsung (BUANG)
RETAIL_PROMO_PATTERNS = [
    r"\bsyarat\s+dan\s+ketentuan\b",
    r"\bsyarat\s*&\s*ketentuan\b",
    r"\bs&k\s+berlaku\b",
    r"\bperiode\s+promo\b",
    r"\bdiskon\b",
    r"\bsupermarket\b",
    r"\bminimarket\b",
    r"\bhypermarket\b",
    r"\bminimal\s+pembelian\b",
    r"\bminimum\s+transaksi\b",
    r"\bcashback\b",
    r"\bvoucher\b",
    r"\bkatalog\s+promo\b",
    r"\bharga\s+promo\b",
    r"\bpromo\s+bca\b",
    r"\bpromo\s+mingguan\b",
    r"\bpromo\s+ssr\b",
    r"\bpromo\s+jsm\b",
    r"\bbeli\s+1\s+gratis\s+1\b",
    r"\bbeli\s+2\s+gratis\s+1\b",
    r"\bpotongan\s+harga\b",
    r"\bkupon\s+belanja\b",
    r"\btoko\s+alat\s+rumah\s+tangga\b",
    r"^(toko|grosir|distributor)\s+.*\b(murah|terlengkap|terdekat|diskon)\b",
]

# Pola nama event pameran industri resmi
OFFICIAL_EVENT_PATTERNS = [
    r"\bfi\s+asia\b",
    r"\bfood\s+ingredients\s+asia\b",
    r"\btrade\s+expo\b",
    r"\btei\b",
    r"\bsial\s+interfood\b",
    r"\binterfood\b",
    r"\bfood\s*&\s*hotel\b",
    r"\bfhi\b",
    r"\ballpack\b",
    r"\biffina\b",
    r"\bindo\s+livestock\b",
    r"\bagrinex\b",
    r"\bpameran\b",
    r"\bexpo\b",
    r"\bexhibition\b",
]

# Pola tindakan partisipasi brand/perusahaan di pameran/event industri
BRAND_EVENT_ACTION_PATTERNS = [
    r"\b(hadir\s+di|hadir\s+dalam)\b",
    r"\b(perkenalkan|memperkenalkan)\b",
    r"\b(pamerkan|memamerkan)\b",
    r"\b(tampilkan|menampilkan)\b",
    r"\b(unjuk\s+gigi\s+di)\b",
    r"\b(ramaikan|meramaikan)\b",
    r"\b(berpartisipasi\s+di|berpartisipasi\s+dalam|partisipasi\s+di|partisipasi\s+dalam)\b",
    r"\b(ikut\s+serta\s+di|ikut\s+serta\s+dalam)\b",
    r"\b(luncurkan|meluncurkan)\b",
]


def is_brand_event_participation(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi apakah artikel merupakan liputan partisipasi brand/perusahaan di pameran/event industri resmi.
    Contoh: '[Brand] Hadir di [Nama Event]', '[Brand] Perkenalkan [Produk] di [Nama Pameran]'.
    """
    t_clean = (title or "").lower()
    snip_clean = (text[:400] if text else "").lower()
    combined = f"{t_clean} {snip_clean}"

    has_event = any(re.search(pat, combined) for pat in OFFICIAL_EVENT_PATTERNS)
    has_action = any(re.search(pat, t_clean) for pat in BRAND_EVENT_ACTION_PATTERNS) or \
                 (has_event and any(re.search(pat, snip_clean) for pat in BRAND_EVENT_ACTION_PATTERNS))

    return bool(has_event and has_action)


def is_promotional(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi apakah artikel merupakan materi promosi / iklan komersial:
    1. BUANG: Promosi ritel/supermarket, diskon, cashback, voucher, katalog promo, syarat dan ketentuan berlaku.
    2. LOLOSKAN: Partisipasi brand/perusahaan di event/pameran industri resmi (Fi Asia, TEI, SIAL InterFOOD, dll.)
       tanpa pola promosi ritel konsumen langsung.
    3. BUANG: Materi promo lainnya yang memuat PROMO_WORDS.
    """
    title_text = title or ""
    snippet = text[:300] if text else ""
    combined = f"{title_text} {snippet}"

    # 1. Cek promosi ritel / belanja konsumen langsung (BUANG)
    if any(re.search(p, combined, flags=re.IGNORECASE) for p in RETAIL_PROMO_PATTERNS):
        return True

    # 2. Cek partisipasi brand di event industri resmi (LOLOSKAN)
    if is_brand_event_participation(title_text, text):
        return False

    # 3. Fallback promo words biasa
    return any_word_boundary_match(PROMO_WORDS, combined)


# Kata kunci indikator lowongan pekerjaan / karir
JOB_TITLE_KEYWORDS = [
    "lowongan", "loker", "dibutuhkan", "we are hiring", "open recruitment",
    "job vacancy", "buka lowongan", "pelamar kerja", "drafter", "quality control",
    "workshop furniture", "marketing furniture", "staff admin", "graphic design",
]

JOB_CONTENT_KEYWORDS = [
    "kualifikasi:", "persyaratan:", "job description", "deskripsi pekerjaan",
    "tanggung jawab pekerjaan", "rentang gaji", "kirim cv", "lamar pekerjaan",
    "apply now", "cara melamar",
]


def is_job_posting(title: str = "", text: str = "", url: str = "") -> bool:
    """
    Mendeteksi apakah artikel merupakan materi lowongan pekerjaan / rekrutmen lowongan:
    - URL memuat pola direktori lowongan (/job/, /career, /loker, dll.)
    - Judul memuat indikator lowongan / posisi kerja
    - Atau teks awal memuat pola instruksi lamaran kerja / kualifikasi pelamar
    """
    url_lower = (url or "").lower()
    if any(p in url_lower for p in ["/job/", "/jobs/", "/loker/", "/career", "/karir", "/lowongan"]):
        return True

    title_lower = (title or "").lower()
    snippet = (text[:1000] if text else "").lower()

    if any(matches_word_boundary(w, title_lower) for w in JOB_TITLE_KEYWORDS):
        return True

    if any(kw in snippet for kw in JOB_CONTENT_KEYWORDS):
        if any(matches_word_boundary(w, title_lower) for w in ["lowongan", "loker", "rekrutmen", "karir", "career"]):
            return True
        if any(matches_word_boundary(w, snippet) for w in ["lowongan", "loker", "dibutuhkan", "hiring"]):
            return True

    return False


CRITICAL_INCIDENT_TITLE_PHRASES = [
    "meninggal dunia", "ditemukan tewas", "tewas", "mayat", "pembunuhan",
    "diserang beruang", "diterkam buaya", "diserang buaya", "kebakaran lahan",
    "pemadaman", "laka lantas", "kecelakaan maut", "kecelakaan fatal", "tabrakan beruntun",
    "tabrakan", "orang hilang", "serangan jantung", "bakar lahan", "membakar lahan", "karhutla",
    "diterkam", "meninggal", "gantung diri", "bunuh diri",
    "densus 88", "terduga teroris", "teroris", "giro kosong", "bilyet giro kosong",
]

CRIME_ACCIDENT_TITLE_KEYWORDS = [
    "bobol", "pembobolan", "curi", "mencuri", "pencurian",
    "residivis", "maling", "perampokan", "rampok", "kebakaran",
    "korban", "pembunuhan", "mayat", "laka lantas", "tewas",
    "teroris", "ditangkap", "dibekuk", "diringkus", "tabrakan",
]

CELEBRITY_TITLE_KEYWORDS = [
    "ji chang-wook", "aktor korea", "artis korea", "drakor", "k-pop", "konser",
    "lirik lagu", "chord gitar", "kunci gitar", "makna lagu", "viral tiktok", "ig nobel",
    "minidrama", "mini drama", "sinetron", "film pendek", "trailer", "teaser", "webseries",
    "betrand peto", "karaoke betrand", "ruben onsu", "sarwendah",
]


def is_crime_or_accident(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi berita kriminal, kecelakaan maut, atau musibah kebakaran di mana
    komoditas hanya muncul sebagai barang bukti curian, lokasi musibah, atau bantuan darurat.
    """
    title_lower = (title or "").lower()
    if any(phrase in title_lower for phrase in CRITICAL_INCIDENT_TITLE_PHRASES):
        return True

    if any(matches_word_boundary(w, title_lower) for w in CRIME_ACCIDENT_TITLE_KEYWORDS):
        comb = f"{title_lower} {(text or '').lower()}"
        ind = count_signal_occurrences(INDUSTRY_POLICY_SIGNALS, comb)
        if ind < 2:
            return True
    return False


CRIME_ACCIDENT_PHRASES = [
    # Multi-word phrases safe to match directly
    "puntung rokok", "dilalap api", "kobaran api",
    "densus 88", "terduga teroris", "tabrakan beruntun", "kecelakaan maut",
    "kecelakaan fatal", "laka lantas", "truk terbalik", "truk terguling",
    "korban tewas", "meninggal dunia", "ditemukan tewas", "bunuh diri",
    "habisi pelajar", "habisi nyawa", "buang jasad", "pelaku nekat",
    "polisi amankan ibadah", "bhabinkamtibmas", "naik penyidikan",
    "patroli dialogis", "jumat curhat", "cipta kondisi", "operasi cipta kondisi",
    "razia miras", "botol miras", "miras ilegal", "beasiswa sawit", "toko miras",
    "faktor kasus kriminal", "polwan sapa",
    "giro kosong", "bilyet giro kosong", "bilyet giro",
    "ular piton", "ular kobra", "teror ular", "diserang buaya",
    "diterkam buaya", "diserang beruang", "penunggu kebun",
]

CRIME_ACCIDENT_SINGLE_WORDS = [
    # Single words that MUST match word boundary (mencegah false match seperti 'Kolaka' -> 'laka')
    "kebakaran", "terbakar", "hangus", "curi", "pencuri", "pencurian",
    "maling", "rampok", "perampokan", "bobol", "pembobolan",
    "digerebek", "gerebek", "penggerebekan", "sabu", "narkoba",
    "narkotika", "ganja", "ekstasi", "ditangkap", "tertangkap",
    "tangkap", "diamankan", "dibekuk", "diringkus", "terciduk",
    "tersangka", "residivis", "buronan", "teroris", "terorisme",
    "radikalisme", "tabrakan", "kecelakaan", "menabrak", "ditabrak",
    "tewas", "mayat", "pembunuhan", "penipuan", "penggelapan", "hantu",
    "polsek", "polresta", "polres", "kamtibmas", "brimob",
]

CRIME_ACCIDENT_SIGNALS = CRIME_ACCIDENT_PHRASES + CRIME_ACCIDENT_SINGLE_WORDS

POLICY_INSTITUTION_TITLE_SIGNALS = [
    "kemenperin", "kementerian perindustrian", "menperin", "wamenperin",
    "ditjen agro", "menteri perindustrian", "kebijakan", "regulasi", "ekspor",
    "impor", "produksi nasional", "investasi", "hilirisasi",
]


def is_crime_accident_noise(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi berita kriminal, kecelakaan, musibah kebakaran, atau narkoba yang lolos
    karena kebetulan menyebut nama komoditas sebagai lokasi/objek/bahan (bukan topik industrinya).
    True jika salah satu sinyal CRIME_ACCIDENT_SIGNALS muncul di TITLE dan TIDAK disertai
    konteks kebijakan/institusi (Kemenperin, ekspor, produksi nasional, dst) di title yang sama.
    """
    title_lower = (title or "").lower()
    if not title_lower:
        return False

    # Pengecualian khusus: penindakan rokok ilegal / cukai oleh Bea Cukai / DJBC adalah bagian dari monitoring hasil tembakau
    if any(k in title_lower for k in ["rokok ilegal", "pita cukai", "bea cukai", "djbc"]):
        return False

    has_phrase = any(p in title_lower for p in CRIME_ACCIDENT_PHRASES)
    has_word = any(matches_word_boundary(w, title_lower) for w in CRIME_ACCIDENT_SINGLE_WORDS)
    if not (has_phrase or has_word):
        return False

    has_policy_exception = any(
        matches_word_boundary(exc, title_lower) or exc in title_lower
        for exc in POLICY_INSTITUTION_TITLE_SIGNALS
    )
    return not has_policy_exception


def is_celebrity_entertainment(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi berita infotainment/gaya hidup selebriti murni (misal aktor Korea, konser, drakor).
    """
    title_lower = (title or "").lower()
    return any(w in title_lower for w in CELEBRITY_TITLE_KEYWORDS)


NON_ARTICLE_TITLE_PATTERNS = [
    # Bab skripsi / tesis / buku akademik
    r"^\s*(bab|chapter)\s+([ivxlcdm]+|\d+)\b",
    # Template jurnal / format penulisan
    r"\btemplate\b",
    # Elemen struktural dokumen / skripsi / jurnal akademik
    r"^\s*(daftar\s+isi|daftar\s+tabel|daftar\s+gambar|daftar\s+pustaka|lembar\s+pengesahan|kata\s+pengantar|halaman\s+judul|lampiran)\b",
    r"^\s*(abstrak|abstract)\b",
    r"\b(ijccs|ijccs-style)\b",
    r"\blaporan\s+magang\b",
    r"\bbuku\s+karya\s+ilmiah\b",
    r"\bbuku\s+tulis\b",
    r"\bjurnal\s+ilmiah\s+kesehatan\b",
    r"\bkejadian\s+ispa\b",
    r"\bstudi\s+kasus\s+pada\s+konsumen\b",
    r"\bjenis\s+packing\s+agar\s+barang\s+aman\b",
]

_NON_ARTICLE_REGEX = re.compile("|".join(NON_ARTICLE_TITLE_PATTERNS), re.IGNORECASE)


def is_non_article_document_noise(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi dokumen non-artikel berita seperti bab skripsi/tesis (BAB II),
    template jurnal akademik (Template Jurnal IJCCS), daftar isi, kata pengantar,
    atau abstrak skripsi tanpa konteks berita industri.
    """
    title_clean = (title or "").strip().lower()
    if not title_clean:
        return False

    # 1. Cek pola judul dokumen akademik / non-artikel
    if _NON_ARTICLE_REGEX.search(title_clean):
        # Kecualikan jika judul secara eksplisit memuat konteks industri/kebijakan formal
        if any_word_boundary_match(["kemenperin", "kementerian", "ekspor", "impor", "pabrik", "produksi"], title_clean):
            return False
        return True

    # 2. Cek judul terlalu pendek & generik (misal: "BAB 2", "COVER", "LAMPIRAN")
    if len(title_clean) < 15 and re.match(r"^(bab|cover|lampiran|skripsi|tesis)\b", title_clean):
        return True

    return False


GENERIC_PLACEHOLDER_TITLES = {
    "resource discovery", "untitled", "no title", "error", "404 not found",
    "access denied", "blocked", "document", "halaman tidak ditemukan",
    "search results", "katalog induk", "informasi paket", "garba rujukan digital",
    "index", "home", "beranda", "loading", "sipp", "das kelapa", "daftar umkm",
    "pencarian data umkm", "icgab 2026", "proyek tunggal", "simponi sumut",
    "kelapaaa", "pecinta kopi",
    "berita terbaru hari ini", "berita terkini", "berita hari ini", "kumpulan berita",
    "indeks berita", "berita dan informasi",
}

NON_NEWS_DOMAINS = [
    "order.lottemart.co.id", "tiket.com", "chandrakarya.com", "jadesta.kemenpar.go.id",
    "eorder-bppbj.jakarta.go.id", "jobrapido.com", "confbeam.org", "hidrologi.net",
    "data-umkm.babelprov.go.id", "nimbuflyk.digital", "simponisumut.sumutprov.go.id",
    "pustaka.badanpangan.go.id", "spse.inaproc.id", "garuda.kemdiktisaintek.go.id",
    "katalog.kemendikdasmen.go.id", "sipp.pn-", "siplah.", "repository.", "repositori.",
    "multidisipliner.org", "kailogistik.id",
]


def is_placeholder_or_error_title(title: str = "", text: str = "", url: str = "") -> bool:
    """
    Mendeteksi judul placeholder / pesan error / artifact halaman sistem non-berita:
    1. Judul sama persis / diawali string generik ('Resource discovery', 'Untitled', 'No title', 'Error', '404', 'Beranda', 'SIPP', 'Informasi Paket', dll)
    2. Judul merupakan halaman agregator tag / arsip berita otomatis ('Berita Terbaru Hari Ini - {topik}', dll)
    3. Judul terlalu pendek (< 5 karakter) atau format non-berita.
    4. Berasal dari domain katalog/pengadaan/hotel/e-commerce non-berita.
    """
    t_clean = (title or "").strip().lower()
    if not t_clean or len(t_clean) < 5:
        return True
    if t_clean in GENERIC_PLACEHOLDER_TITLES or is_aggregator_placeholder_title(title):
        return True
    if any(t_clean.startswith(prefix) for prefix in ["search results", "katalog induk", "informasi paket", "garba rujukan digital", "error 404", "halaman tidak ditemukan"]) or "peraturan ditemukan" in t_clean:
        return True
    url_lower = (url or "").lower()
    if any(d in url_lower for d in NON_NEWS_DOMAINS):
        return True
    return False


def is_viral_social_media_drama(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi berita drama / video viral / kontroversi media sosial non-industri:
    Contoh: 'Video Bupati Siak Viral di Medsos, Wapres Gibran Kirim Tim Khusus ke Wilayah 3T'.
    True jika memuat frasa 'viral di medsos', 'viral di media sosial', 'video viral', 'heboh di medsos'
    dan TIDAK memuat konteks industri/kebijakan formal (kemenperin, ekspor, impor, produksi, hilirisasi, pabrik, harga, investasi).
    """
    title_lower = (title or "").lower()
    if any(p in title_lower for p in ["viral di medsos", "viral di media sosial", "video viral", "heboh di medsos", "viral tiktok"]):
        has_industry_context = any(k in title_lower for k in POLICY_INSTITUTION_TITLE_SIGNALS + ["harga", "pabrik", "tbs", "petani sawit", "sawit rakyat", "kebun sawit"])
        if not has_industry_context:
            return True
    return False


def is_lifestyle_tourism_noise(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi konten rekreasi wisata, liburan, ulasan kedai kopi/kafe, dan panduan nongkrong
    yang tidak memuat konteks kebijakan industri atau korporasi manufaktur.
    Contoh: 'Kampung Coklat Blitar', 'OSMA Osmanthus Tea, Kedai Teh Baru Solo', '3 Rekomendasi Library Cafe di Bandung'.
    """
    t_clean = (title or "").lower()
    tourism_signals = [
        "kampung coklat blitar", "library cafe", "kedai teh", "kedai kopi bah sipit",
        "catra kopi batang", "ketika kopi dan seni bertemu", "festival nyusu bareng",
        "kampung susu brau", "ekowisata berbasis masyarakat", "harga tiket masuk",
        "oleh-oleh cokelat",
    ]
    return any(s in t_clean for s in tourism_signals)


def is_personal_blog_noise(title: str = "", text: str = "", url: str = "") -> bool:
    """
    Mendeteksi esai pribadi, diary, puisi, atau renungan personal dari platform blog/UGC (seperti Kompasiana)
    yang bukan artikel berita industri maupun kebijakan resmi.
    """
    u_lower = (url or "").lower()
    if "kompasiana.com" not in u_lower:
        return False
    t_clean = (title or "").lower()
    blog_markers = [
        "tektok part 2", "ketika kebahagiaan tidak butuh mahal", "bapak, orang pertama",
        "bosan nunggu panggilan kerja", "lira playdate", "festival kali maro",
        "tiga buah kakao", "pabrik energi di dalam sel", "pencegahan cvs",
        "rahasia genetik karang", "roti gandum vs roti tawar",
    ]
    return any(m in t_clean for m in blog_markers)


RETAIL_ENFORCEMENT_SIGNALS = [
    "satpol pp", "disegel", "penyegelan", "raperda", "ranperda",
    "moratorium izin", "moratorium perizinan", "moratorium rhu",
    "ketenagakerjaan", "pengawasan usaha karaoke", "usaha karaoke",
    "izin usaha", "penertiban minol", "penertiban miras", "riuh malam",
    "diskotek baru", "pembatasan miras", "pengendalian miras",
]

RETAIL_INDUSTRY_EXCEPTIONS = [
    "pabrik", "fasilitas produksi", "kapasitas produksi", "hilirisasi",
    "ekspor", "impor", "kemenperin", "kementerian perindustrian",
    "ditjen agro", "investasi", "kawasan industri",
]


def is_local_retail_enforcement(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi berita penegakan hukum ritel lokal, penertiban perizinan oleh Pemda/Satpol PP,
    raperda/pansus DPRD kota/kabupaten terkait miras/RHU, atau penyegelan toko eceran yang berada
    di luar lingkup industri (produksi, pabrik, ekspor, hilirisasi, kebijakan nasional Kemenperin).

    True jika judul/teks mengandung RETAIL_ENFORCEMENT_SIGNALS dan tidak memuat konteks industri/pabrik.
    Pengecualian khusus: Razia/penindakan rokok ilegal dan pita cukai oleh Bea Cukai / DJBC tetap dipertahankan.
    """
    title_lower = (title or "").lower()
    text_lower = (text or "").lower()

    # Pengecualian mutlak: monitoring DJBC / Bea Cukai / pita cukai / rokok ilegal di title tetap dipertahankan
    if any(k in title_lower for k in ["rokok ilegal", "pita cukai", "bea cukai", "djbc"]):
        return False

    # Pengecualian: Moratorium sawit perkebunan nasional
    if "moratorium sawit" in title_lower or ("moratorium" in title_lower and "sawit" in title_lower):
        return False

    # Pengecualian: Investigasi atau perlindungan investasi pabrik industri
    if any(matches_word_boundary(ind, title_lower) or ind in title_lower for ind in RETAIL_INDUSTRY_EXCEPTIONS):
        return False

    # Cek sinyal penegakan ritel lokal pada title
    for sig in RETAIL_ENFORCEMENT_SIGNALS:
        if sig in title_lower:
            return True

    # Cek sinyal pada text jika title berkaitan dengan miras/karaoke/toko eceran
    if any(w in title_lower for w in ["miras", "mihol", "minol", "minuman beralkohol", "karaoke", "rhu"]):
        for sig in ["satpol pp", "disegel", "penyegelan", "moratorium", "penertiban", "raperda"]:
            if sig in text_lower:
                return True

    return False


SHORTS_ENTERTAINMENT_PATTERNS = [
    r"#shorts\b", r"#fyp\b", r"#viral\b", r"#trending\b", r"#shortvideo\b",
    r"#short\b", r"#reels\b", r"#tiktok\b",
]

FORMAL_NEWS_INSTITUTIONS_MEDIA = [
    "kemenperin", "kementerian", "ditjen", "dinas", "bps", "ojk", "bi",
    "presiden", "wapres", "menteri", "menperin", "wamenperin", "dirjen",
    "antara", "kompas", "detik", "tempo", "kontan", "bisnis.com", "tribun",
    "republika", "liputan6", "suara.com", "metrotv", "kompastv", "tvone",
    "cnn", "cnbc", "inews", "rri", "tvri", "bumn", "ptpn", "holding",
]

JOURNALISTIC_VERBS = [
    "resmikan", "meresmikan", "umumkan", "mengumumkan", "laporkan", "melaporkan",
    "capai", "mencapai", "targetkan", "menargetkan", "tegaskan", "menegaskan",
    "dorong", "mendorong", "tinjau", "meninjau", "luncurkan", "meluncurkan",
    "gelar", "menggelar", "buka", "membuka", "bahas", "soroti", "ungkap",
    "paparkan", "beberkan", "catat", "mencatat", "tumbuh", "meningkat",
    "anjlok", "turun", "ekspor", "impor", "investasi", "hilirisasi", "produksi",
]


def is_shorts_entertainment_noise(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi konten hiburan pendek (YouTube Shorts / Reels / TikTok) tanpa substansi berita formal:
    1. Title memuat 3+ hashtag (#kata1 #kata2 #kata3).
    2. ATAU title memuat hashtag/pola hiburan (#shorts, #fyp, #viral, #trending, #shortvideo)
       DIGABUNG dengan tidak adanya nama media/institusi formal dan tidak ada kata kerja jurnalistik.
    3. ATAU memuat pola gaming/meme/lucu/hewan peliharaan murni (#roblox, #minecraft, smackdown, lucu, kocak, prank).
    """
    title_text = (title or "").strip()
    if not title_text:
        return False
    title_lower = title_text.lower()

    # 1. Title mengandung 3+ hashtag
    tags = re.findall(r"#\w+", title_text)
    if len(tags) >= 3:
        return True

    # 2. Pola umum konten hiburan pendek digabung tidak ada format berita formal
    has_short_pattern = any(re.search(p, title_lower) for p in SHORTS_ENTERTAINMENT_PATTERNS)
    if has_short_pattern:
        has_formal_inst = any(matches_word_boundary(w, title_lower) or w in title_lower for w in FORMAL_NEWS_INSTITUTIONS_MEDIA)
        has_journalistic_verb = any(matches_word_boundary(v, title_lower) or v in title_lower for v in JOURNALISTIC_VERBS)
        if not (has_formal_inst or has_journalistic_verb):
            return True

    # 3. Konten gaming / meme / hewan peliharaan / humor pendek
    if any(g in title_lower for g in ["#roblox", "#minecraft", "roblox", "smackdown", "kocak", "#lucu", "prank"]):
        return True

    return False


SAWIT_EXCLUDE_PHRASES = [
    "duren sawit",
    "kecamatan duren sawit",
    "kelurahan duren sawit",
    "polsek duren sawit",
]
SAWIT_INDUSTRY_TERMS = [
    "kelapa sawit", "minyak sawit", "perkebunan sawit", "kebun sawit", "cpo",
    "tbs", "tandan buah segar", "petani sawit", "industri sawit", "pabrik sawit",
    "ekspor sawit", "hilirisasi sawit", "bpdpks", "gapki", "sawit rakyat",
]


def is_sawit_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'sawit' agar tidak tercampur nama lokasi kecamatan/jalan ('Duren Sawit')
    kecuali jika benar-benar membahas industri kelapa sawit / CPO.
    """
    combined = f"{title} {text}".lower()
    if any(phrase in combined for phrase in SAWIT_EXCLUDE_PHRASES):
        has_industry = any(matches_word_boundary(term, combined) for term in SAWIT_INDUSTRY_TERMS)
        if not has_industry:
            return False
    return True


PULP_EXCLUDE_PHRASES = ["pulp fiction"]
PULP_INDUSTRY_TERMS = [
    "pabrik pulp", "industri pulp", "bubur kertas", "kayu pulp",
    "produksi pulp", "ekspor pulp", "impor pulp", "toba pulp",
    "serat kayu", "hutan tanaman industri", "hti",
]


def is_pulp_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'pulp' agar tidak mencocokkan parfum 'Pulp Fiction' atau referensi film/pop culture.
    """
    combined = f"{title} {text}".lower()
    if any(phrase in combined for phrase in PULP_EXCLUDE_PHRASES):
        has_industry = any(matches_word_boundary(term, combined) for term in PULP_INDUSTRY_TERMS)
        if not has_industry:
            return False
    return True


# Frasa dengan makna ganda yang bukan merujuk pada komoditas/industri kertas
KERTAS_EXCLUDE_PHRASES = [
    "kertas kerja",
    "di atas kertas",
    "uang kertas",
    "tiket kertas",
    "wayang kertas",
    "ujian kertas",
    "kertas ujian",
    "ujian berbasis komputer atau kertas",
    "era kertas",
    "menandatangani kertas",
    "selembar kertas",
    "kantong kertas",
    "kertas suara",
    "kertas kado",
    "pesawat kertas",
    "antara kertas dan realita",
]

KERTAS_INDUSTRY_TERMS = [
    "pabrik kertas",
    "industri kertas",
    "bahan baku kertas",
    "produksi kertas",
    "produsen kertas",
    "ekspor kertas",
    "impor kertas",
    "kertas bekas",
    "limbah kertas",
    "daur ulang kertas",
    "pulp",
    "kertas kemasan",
    "kertas karton",
    "tjiwi kimia",
    "indah kiat",
]


def is_kertas_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi apakah artikel benar-benar membahas kertas sebagai komoditas industri,
    bukan penggunaan non-industri (uang kertas, tiket, wayang kertas, dokumen ujian/kantor).
    """
    combined = f"{title} {text}".lower()
    title_lower = (title or "").lower()

    if any(phrase in title_lower for phrase in KERTAS_EXCLUDE_PHRASES):
        return False

    has_industry = any(matches_word_boundary(term, combined) for term in KERTAS_INDUSTRY_TERMS)
    if has_industry:
        return True

    return False


KELAPA_EXCLUDE_PHRASES = [
    "kelapa gading",
    "talang kelapa",
    "tanjung kelapa",
    "pulau kelapa",
    "kelapa dua",
    "kelapa lima",
]
KELAPA_INDUSTRY_TERMS = [
    "pohon kelapa", "minyak kelapa", "kelapa parut", "kopra", "sabut kelapa",
    "perkebunan kelapa", "petani kelapa", "olahan kelapa", "batok kelapa",
    "air kelapa", "hilirisasi kelapa", "kelapa kopyor", "tunas kelapa",
    "daging kelapa", "ekspor kelapa", "industri kelapa", "produksi kelapa",
]


def is_kelapa_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'kelapa' agar tidak tercampur nama lokasi ('Kelapa Gading', 'Talang Kelapa', dll.)
    atau spam judi/slot ('bet tunas kelapa').
    """
    combined = f"{title} {text}".lower()
    if "bet tunas kelapa" in combined or "situs resmi indonesia" in combined:
        return False

    if any(phrase in combined for phrase in KELAPA_EXCLUDE_PHRASES):
        has_industry = any(matches_word_boundary(term, combined) for term in KELAPA_INDUSTRY_TERMS)
        if not has_industry:
            return False
    return True


KARET_EXCLUDE_PHRASES = [
    "jam karet", "perahu karet", "ban karet", "gelang karet", "celana karet",
    "tali karet", "permainan karet", "lompat tali", "stasiun karet",
]
KARET_INDUSTRY_TERMS = [
    "kebun karet", "perkebunan karet", "petani karet", "harga karet",
    "ekspor karet", "industri karet", "sadap karet", "getah karet",
    "lateks", "apkarindo", "gabungan perusahaan karet", "produksi karet",
    "tanaman karet", "pohon karet", "kayu karet", "hilirisasi",
]


def is_karet_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'karet' agar tidak tercampur idiom 'jam karet',
    kecelakaan kapal / evakuasi perahu karet, Stasiun Karet, permainan anak, atau aksesoris non-industri.
    """
    combined = f"{title} {text}".lower()

    # Jika mengandung frasa exclude (misal stasiun karet, permainan karet)
    if any(phrase in combined for phrase in KARET_EXCLUDE_PHRASES):
        has_strong_industry = any(
            matches_word_boundary(w, combined)
            for w in ["hilirisasi", "apkarindo", "harga karet", "ekspor karet", "industri karet", "pabrik karet"]
        )
        if not has_strong_industry:
            return False

    has_industry = any(matches_word_boundary(term, combined) for term in KARET_INDUSTRY_TERMS)
    if has_industry:
        return True

    title_lower = (title or "").lower()
    if any(w in title_lower for w in ["jam karet", "kapal", "km ", "tenggelam", "perahu"]):
        return False

    raw_karet = len(re.findall(r"\bkaret\b", combined, flags=re.IGNORECASE))
    if raw_karet == 0:
        return True

    excluded_count = sum(
        len(re.findall(rf"\b{re.escape(phrase)}\b", combined, flags=re.IGNORECASE))
        for phrase in KARET_EXCLUDE_PHRASES
    )
    if raw_karet - excluded_count <= 0:
        return False

    return True


KAKAO_EXCLUDE_PHRASES = ["kakao entertainment", "kakao page", "kakaotalk", "kakao corp", "the boyz", "label 78"]
KAKAO_INDUSTRY_TERMS = [
    "kebun kakao", "perkebunan kakao", "petani kakao", "biji kakao",
    "olahan kakao", "harga kakao", "produksi kakao", "ekspor kakao",
    "industri kakao", "pohon kakao", "cokelat",
]


def is_kakao_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'kakao' agar tidak mencocokkan entitas hiburan / K-pop Korea (Kakao Corp / Entertainment).
    """
    combined = f"{title} {text}".lower()
    if any(phrase in combined for phrase in KAKAO_EXCLUDE_PHRASES):
        has_industry = any(matches_word_boundary(term, combined) for term in KAKAO_INDUSTRY_TERMS)
        if not has_industry:
            return False
    return True


COKELAT_EXCLUDE_PHRASES = [
    "amplop cokelat", "warna cokelat", "baju cokelat", "seragam cokelat",
    "celana cokelat", "sepatu cokelat", "kulit cokelat", "mata cokelat",
    "rambut cokelat", "beras cokelat", "gula cokelat",
]
COKELAT_INDUSTRY_TERMS = [
    "biji cokelat", "kebun cokelat", "petani cokelat", "perkebunan cokelat",
    "olahan cokelat", "produk cokelat", "batang cokelat", "pabrik cokelat",
    "industri cokelat", "bubuk cokelat", "ekspor cokelat", "harga cokelat",
    "kakao", "kudapan cokelat", "kue cokelat", "manisan cokelat", "bikin cokelat",
    "makan cokelat", "cokelat batang", "cokelat batangan",
]


def is_cokelat_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'cokelat' agar tidak mencocokkan benda berwarna cokelat non-makanan
    (misal 'amplop cokelat', 'baju cokelat', 'seragam cokelat').
    """
    combined = f"{title} {text}".lower()
    title_lower = (title or "").lower()
    if any(phrase in title_lower for phrase in ["amplop cokelat", "baju cokelat", "seragam cokelat", "celana cokelat"]):
        return False
    if any(phrase in combined for phrase in COKELAT_EXCLUDE_PHRASES):
        has_industry = any(matches_word_boundary(term, combined) for term in COKELAT_INDUSTRY_TERMS)
        if not has_industry:
            return False
    return True


TAR_INDUSTRY_TERMS = [
    "rokok", "tembakau", "sigaret", "nikotin", "asap rokok", "kretek",
    "kadar tar", "kandungan tar", "senyawa tar", "vape",
]


def is_tar_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'tar' agar tidak mencocokkan singkatan inisial merek atau kata umum.
    Harus berkaitan dengan residu tembakau/rokok atau industri hasil tembakau.
    """
    combined = f"{title} {text}".lower()
    return any(matches_word_boundary(t, combined) for t in TAR_INDUSTRY_TERMS)


TEH_EXCLUDE_TITLE_PHRASES = [
    "teh cely", "teh rina", "teh nia", "teh melly", "teh nita", "teh novi",
    "tulus", "cover", "singing battle", "dj teh", "remix", "chord", "kunci gitar",
    "ami awards", "lagu", "music video", "official lyric", "song", "lirik lagu",
    "makna lagu", "lagu pop", "single baru",
]
TEH_INDUSTRY_TERMS = [
    "kebun teh", "perkebunan teh", "petani teh", "daun teh", "pabrik teh",
    "industri teh", "produksi teh", "ekspor teh", "harga teh", "pucuk teh",
    "minuman teh", "teh kemasan", "teh hitam", "teh hijau", "teh wangi",
]


def is_teh_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'teh' agar tidak mencocokkan panggilan kehormatan Sunda ('Teh Cely', dsb)
    atau judul lagu/musik/penyanyi (Tulus - Teh Hijau, cover, singing battle, remix).
    """
    title_lower = (title or "").lower()
    if any(p in title_lower for p in TEH_EXCLUDE_TITLE_PHRASES):
        return False
    combined = f"{title} {text}".lower()
    has_industry = any(matches_word_boundary(t, combined) for t in TEH_INDUSTRY_TERMS)
    if re.search(r"\bTeh\s+[A-Z][a-z]+", title or "") and not has_industry:
        return False
    return True


SUSU_EXCLUDE_PHRASES = [
    "gigi susu", "warna kopi susu", "berwarna kopi susu", "susu kecoa", "susu kecoak",
]


def is_susu_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'susu' agar tidak mencocokkan istilah 'gigi susu' (kedokteran gigi),
    metafora warna air 'kopi susu', atau parodi riset 'susu kecoa'.
    """
    title_lower = (title or "").lower()
    combined = f"{title} {text}".lower()
    if any(p in title_lower for p in SUSU_EXCLUDE_PHRASES):
        return False
    if "susu kecoa" in combined or "susu kecoak" in combined:
        return False
    if any(w in title_lower for w in ["gigi susu", "gigi berlubang", "rekomendasi susu oat"]):
        return False
    return True


KOPI_EXCLUDE_TITLE_PHRASES = [
    "kena skors", "etiket makan", "perkembangan anak", "tumbuh kembang",
    "asam lambung", "rekomendasi susu oat", "aeropress", "french press",
    "#cari_aman",
]


def is_kopi_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'kopi' agar tidak mencocokkan artikel parenting/akronim komunitas,
    tips lambung/kesehatan pribadi, peralatan seduh barista, atau insiden disiplin sekolah.
    """
    title_lower = (title or "").lower()
    if any(p in title_lower for p in KOPI_EXCLUDE_TITLE_PHRASES):
        return False
    if "perkembangan anak" in title_lower or "pola asuh" in title_lower:
        return False
    return True


FAME_EXCLUDE_PHRASES = [
    "hall of fame", "walk of fame", "the fame", "fame and fortune", "fame got",
    "rise to fame", "claim to fame", "star", "celebrity", "hollywood", "actress",
    "actor", "barbie", "movie", "song", "album",
]
FAME_INDUSTRY_TERMS = [
    "fatty acid", "methyl ester", "metil ester", "biodiesel", "oleokimia",
    "sawit", "minyak sawit", "b35", "b40", "b50", "bioenergi", "ebt",
    "bahan bakar nabati", "bbn", "cpo", "solar",
]


def is_fame_context_valid(title: str, text: str) -> bool:
    """
    Memvalidasi keyword 'fame' agar merujuk pada Fatty Acid Methyl Ester (FAME) bahan baku biodiesel/oleokimia,
    BUKAN penghargaan olahraga/hiburan 'Hall of Fame' atau ketenaran selebriti/bahasa Inggris sehari-hari.
    Syarat:
    1. Tidak memuat frasa eksklusi hiburan / selebriti.
    2. HARUS memuat konteks industri/kimia (biodiesel, oleokimia, metil ester, minyak sawit, sawit, bbn, dll).
    """
    combined = f"{title or ''} {text or ''}"
    combined_lower = combined.lower()

    if any(p in combined_lower for p in FAME_EXCLUDE_PHRASES):
        return False

    return any(matches_word_boundary(t, combined_lower) for t in FAME_INDUSTRY_TERMS)


POME_REJECT_WORDS = [
    "dog", "pomeranian", "anjing", "pet", "pets", "puppy", "cute", "cutedog",
]
POME_INDUSTRY_WORDS = [
    "limbah", "sawit", "pabrik", "pengolahan", "cpo", "biogas", "ebt",
    "palm oil mill effluent", "palmco", "sludge", "bioetanol", "energi bersih",
    "energi terbarukan", "emisi karbon", "kek sei mangkei",
]


def is_pome_context_valid(title: str = "", text: str = "") -> bool:
    """
    Memvalidasi keyword 'pome' agar merujuk pada Palm Oil Mill Effluent (limbah cair pabrik kelapa sawit),
    BUKAN anjing Pomeranian, suplemen permen gummy colagen, atau musik produser.
    Syarat:
    1. TOLAK jika disertai kata anjing/pomeranian/pet/puppy.
    2. WAJIB disertai konteks industri limbah/sawit/biogas/pabrik/pengolahan di title ATAU text.
    """
    combined = f"{title or ''} {text or ''}".lower()
    if any(matches_word_boundary(w, combined) for w in POME_REJECT_WORDS):
        return False
    return any(matches_word_boundary(term, combined) or term in combined for term in POME_INDUSTRY_WORDS)


# ==============================================================================
# FILTER RELEVANSI SUBSTANTIF DITJEN INDUSTRI AGRO
# ==============================================================================

NON_AGRO_TOPIC_PATTERNS = [
    r"\brangkap\s+jabatan\b",
    r"\bbupati\s+gowa\b",
    r"\btipidkor\b",
    r"\bbatik\b",
    r"\bnet\s+zero\s+emission\b",
    r"\bdekarbonisasi\b",
    r"\bemisi\s+karbon\b",
    r"\bindustri\s+hijau\b",
    r"\bsertifikasi\s+halal\b",
    r"\bwajib\s+halal\b",
    r"\bindustri\s+halal\b",
    r"\bhalal\s+industry\s+awards\b",
    r"\bkonsultasi\s+bisnis\b",
    r"\bperguruan\s+tinggi\b",
    r"\bdaya\s+saing\s+ikm\b",
    r"\bindustrial\s+festival\b",
    r"\bfestival\s+industri\b",
    r"\botomotif\b",
    r"\bgaikindo\b",
]

SPECIFIC_AGRO_COMMODITIES = [
    # Sawit & Turunan
    r"\bsawit\b", r"\bkelapa\s+sawit\b", r"\bcpo\b", r"\bcrude\s+palm\s+oil\b", r"\bminyak\s+sawit\b",
    r"\bminyak\s+goreng\b", r"\btbs\b", r"\bbiodiesel\b", r"\bfame\b", r"\bpome\b", r"\bbioethanol\b",
    r"\boleokimia\b", r"\bb35\b", r"\bb40\b", r"\bb50\b",
    # Makanan & Minuman
    r"\bmamin\b", r"\bmakanan\s+dan\s+minuman\b", r"\bindustri\s+makanan\b", r"\bindustri\s+minuman\b",
    r"\bmakanan\s+kemasan\b", r"\bbiskuit\b", r"\bolahan\s+daging\b", r"\bdaging\s+olahan\b",
    r"\bmi\s+instan\b", r"\bmie\s+instan\b", r"\bikan\s+kaleng\b", r"\bsarden\b",
    # Kelapa
    r"\bkelapa\b", r"\bkopra\b", r"\bsantan\b", r"\bnata\s+de\s+coco\b",
    # Gula
    r"\bgula\b", r"\bgula\s+rafinasi\b", r"\bgkm\b", r"\btebu\b", r"\bpabrik\s+gula\b",
    # Tepung & Pati
    r"\btepung\b", r"\bterigu\b", r"\btapioka\b", r"\bsingkong\b", r"\bsagu\b", r"\bpati\b",
    # Hasil Laut & Perikanan
    r"\brumput\s+laut\b", r"\balga\b", r"\bspirulina\b",
    # Kertas, Pulp & Kayu
    r"\bpulp\b", r"\bbubur\s+kertas\b", r"\bkertas\b", r"\bkayu\s+lapis\b", r"\bplywood\b",
    r"\bmebel\b", r"\bfurniture\b", r"\bfurnitur\b", r"\bbambu\b", r"\bolahan\s+bambu\b",
    # Atsiri
    r"\batsiri\b", r"\bminyak\s+atsiri\b", r"\bnilam\b", r"\bserai\s+wangi\b",
    # Karet
    r"\bkaret\b", r"\blateks\b", r"\bcrumb\s+rubber\b",
    # Tembakau & Rokok
    r"\btembakau\b", r"\bhasil\s+tembakau\b", r"\brokok\b", r"\bcukai\s+rokok\b",
    r"\brokok\s+ilegal\b", r"\brokok\s+elektrik\b", r"\brokok\s+tanpa\s+pita\s+cukai\b",
    r"\btar\b", r"\bnikotin\b",
    # Kakao & Cokelat
    r"\bkakao\b", r"\bbiji\s+kakao\b", r"\bcokelat\b", r"\bcoklat\b",
    # Minuman
    r"\bminuman\s+beralkohol\b", r"\bminuman\s+berpemanis\b", r"\bamdk\b",
    r"\bair\s+minum\s+dalam\s+kemasan\b", r"\bgalon\b",
    # Teh
    r"\bteh\b", r"\bpucuk\s+teh\b",
    # Susu
    r"\bsusu\b", r"\bproduk\s+susu\b", r"\bolahan\s+susu\b",
    # Kopi
    r"\bkopi\b", r"\bbiji\s+kopi\b",
    # Pakan
    r"\bpakan\s+ternak\b", r"\bpakan\b",
]

DITJEN_AGRO_EXPLICIT = [
    r"\bditjen\s+agro\b", r"\bditjen\s+industri\s+agro\b", r"\bdirektorat\s+jenderal\s+industri\s+agro\b",
    r"\bindustri\s+agro\b", r"\bsektor\s+agro\b",
    r"\bhasil\s+hutan\s+dan\s+perkebunan\b", r"\bmakanan\s+hasil\s+laut\s+dan\s+perikanan\b",
    r"\bminuman\s+hasil\s+tembakau\b", r"\bkemurgi\b",
    r"\bakademi\s+komunitas\s+bambu\b",
]

_NON_AGRO_REGEX = re.compile("|".join(NON_AGRO_TOPIC_PATTERNS), re.IGNORECASE)
_SPECIFIC_COMMODITY_REGEX = re.compile("|".join(SPECIFIC_AGRO_COMMODITIES), re.IGNORECASE)
_DITJEN_AGRO_REGEX = re.compile("|".join(DITJEN_AGRO_EXPLICIT), re.IGNORECASE)


def is_agro_relevant_content(title: str = "", text: str = "") -> bool:
    """
    Memeriksa apakah isi artikel BENAR-BENAR menyinggung salah satu dari 48 keyword komoditas Agro
    ATAU istilah Ditjen Industri Agro secara substantif:
    1. Menolak noise selebriti / hiburan / kementerian luar negeri (Margot Robbie, Barbie, Afghanistan).
    2. True jika judul atau teks secara eksplisit menyebutkan Ditjen Industri Agro / direktorat bawahnya.
    3. Jika topik didominasi isu non-agro (halal/batik/net zero/politik/hukum/tipidkor/ikm umum),
       HANYA lolos jika judul secara spesifik mengangkat komoditas Agro.
    4. True jika judul mengangkat komoditas Agro, atau komoditas muncul berulang (>= 2x) secara substantif.
    """
    title_clean = (title or "").strip()
    title_lower = title_clean.lower()
    combined = f"{title_clean} {text or ''}"
    combined_lower = combined.lower()

    if not combined.strip():
        return False

    # 1. False positive selebriti / hiburan / luar negeri / drama / sosmed CTA
    if any(p in title_lower for p in ["margot robbie", "barbie", "afghanistan", "imarah islam"]):
        return False
    if is_social_media_engagement_noise(title, text):
        return False

    # 2. Cek apakah ada istilah Ditjen Industri Agro eksplisit di judul
    if _DITJEN_AGRO_REGEX.search(title_lower):
        return True

    # 3. Cek apakah judul secara spesifik mengangkat komoditas Agro
    title_has_commodity = bool(_SPECIFIC_COMMODITY_REGEX.search(title_lower))

    # 4. Cek apakah topik didominasi isu non-agro (halal/batik/net zero/politik/hukum/ikm umum)
    has_non_agro_topic = bool(_NON_AGRO_REGEX.search(combined))
    if has_non_agro_topic and not title_has_commodity:
        return False

    # 5. Cek kemunculan komoditas di judul atau substantif di teks (minimal 2x)
    if title_has_commodity:
        return True

    commodity_matches = _SPECIFIC_COMMODITY_REGEX.findall(combined)
    if len(commodity_matches) >= 2:
        return True

    if _DITJEN_AGRO_REGEX.search(combined):
        return True

    return False


def count_keyword_occurrences(text: str, keyword: str) -> int:
    """
    Menghitung kemunculan kata kunci sebagai kata utuh (word boundary regex).
    """
    if not text or not keyword:
        return 0
    pattern = rf"\b{re.escape(keyword.lower())}\b"
    return len(re.findall(pattern, text.lower()))


def is_keyword_primary_topic(title: str, text: str, keyword: str, min_content_occurrences: int = 2) -> bool:
    """
    Memeriksa apakah keyword merupakan topik utama artikel:
    - True kalau keyword muncul di TITLE (word boundary regex), ATAU
    - True kalau keyword muncul minimal min_content_occurrences (default: 2) kali di isi artikel penuh
    - Mendukung query nama pejabat panjang (misal 'Menteri perindustrian agus gumiwang'):
      jika nama pejabat terdeteksi, nama tersebut juga dihitung sebagai term pencocokan.
    - False untuk kasus lainnya (misal hanya disebut 1 kali sebagai bagian dari daftar sembako/bantuan).
    """
    if not keyword:
        return False

    kw_lower = keyword.lower()

    # Khusus keyword kertas: buang jika didominasi makna dokumen non-industri ("kertas kerja" / "di atas kertas")
    if kw_lower == "kertas" and not is_kertas_context_valid(title, text):
        return False
    # Khusus keyword kelapa: buang jika terkait LRT Kelapa Gading / spam judi
    if kw_lower == "kelapa" and not is_kelapa_context_valid(title, text):
        return False
    # Khusus keyword karet: buang jika idiom jam karet / evakuasi kecelakaan laut
    if kw_lower == "karet" and not is_karet_context_valid(title, text):
        return False
    # Khusus keyword kakao: buang jika terkait Kakao Entertainment K-Pop
    if kw_lower == "kakao" and not is_kakao_context_valid(title, text):
        return False
    # Khusus keyword cokelat: buang jika hanya warna / amplop cokelat
    if kw_lower == "cokelat" and not is_cokelat_context_valid(title, text):
        return False
    # Khusus keyword tar: buang jika bukan terkait rokok/tembakau/cukai
    if kw_lower == "tar" and not is_tar_context_valid(title, text):
        return False
    # Khusus keyword teh: buang jika panggilan nama Sunda / lirik lagu
    if kw_lower == "teh" and not is_teh_context_valid(title, text):
        return False
    # Khusus keyword susu: buang jika gigi susu / metafora warna kopi susu
    if kw_lower == "susu" and not is_susu_context_valid(title, text):
        return False
    # Khusus keyword kopi: buang jika parenting/skors/alat seduh/tips lambung
    if kw_lower == "kopi" and not is_kopi_context_valid(title, text):
        return False
    # Khusus keyword fame: buang jika Hall of Fame olahraga / hiburan
    if kw_lower == "fame" and not is_fame_context_valid(title, text):
        return False

    search_terms = []
    if "," in keyword:
        for sub_kw in [k.strip() for k in keyword.split(",") if k.strip()]:
            search_terms.append(sub_kw)
    else:
        search_terms.append(keyword)

    if any(k in kw_lower for k in ["kemenperin", "perindustrian", "institusi", "agus gumiwang"]):
        search_terms.extend(["kemenperin", "kementerian perindustrian", "agus gumiwang", "menperin"])

    OFFICIAL_NAMES = [
        "agus gumiwang", "putu juli ardika", "merrijantij punguan",
        "dyan garneta", "rr citra rapati", "krisna septiningrum",
    ]
    for name in OFFICIAL_NAMES:
        if name in kw_lower and name != kw_lower:
            search_terms.append(name)

    # 1. True jika ada term yang muncul di TITLE
    for term in search_terms:
        if title and matches_word_boundary(term, title):
            return True

    # 2. True jika ada term yang muncul minimal min_content_occurrences kali di isi artikel
    for term in search_terms:
        if text and count_keyword_occurrences(text, term) >= min_content_occurrences:
            return True

    # 3. False untuk kasus lainnya
    return False


def contains_keyword_in_content(text: str, keyword: str, title: str = "") -> bool:
    """
    Fungsi kompatibilitas: memanggil is_keyword_primary_topic.
    """
    return is_keyword_primary_topic(title=title, text=text, keyword=keyword)


# Sinyal kata kunci artikel industri / kebijakan / pemerintah
INDUSTRY_POLICY_SIGNALS = [
    "kementerian", "kemenperin", "kementan", "dinas", "menteri",
    "wamenperin", "wamentan", "direktur jenderal", "dirjen", "gubernur",
    "bupati", "wali kota", "dprd", "dpr ri", "komisi vi", "pabrik",
    "pg ", "swasembada", "ekspor", "impor", "produksi", "produktivitas",
    "investasi", "petani", "perkebunan", "industri", "komoditas",
    "pasar global", "hilirisasi", "koperasi", "umkm", "perusahaan",
    "pt ", "tata niaga", "kuota", "rafinasi", "harga", "daya saing",
]

# Sinyal kata kunci artikel kesehatan / nutrisi pribadi & trivia non-industri
HEALTH_PERSONAL_SIGNALS = [
    "kesehatan tubuh", "gizi", "diet", "kalori", "diabetes",
    "gula darah", "kemenkes", "puskesmas", "manfaat", "khasiat",
    "efek samping", "penyakit", "menu sarapan", "menu sehat",
    "pola makan", "asupan", "konsumsi harian", "tips kesehatan",
    "detoksifikasi", "resep", "racun", "keracunan", "toksik",
    "toksisitas", "gangguan saraf", "kemandulan", "penurunan fungsi organ",
    "sejarah kuno", "romawi kuno", "zaman dulu", "fakta unik", "fakta menarik",
]


def count_signal_occurrences(signals: list[str], text: str) -> int:
    """
    Menghitung total kemunculan seluruh kata/frasa sinyal dalam teks
    menggunakan pencocokan word boundary regex (case-insensitive).
    """
    if not text or not signals:
        return 0

    total = 0
    for s in signals:
        if s.endswith(" "):
            pattern = rf"\b{re.escape(s.strip())}\s+"
        else:
            pattern = rf"\b{re.escape(s)}\b"
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        total += len(matches)
    return total


def is_industry_policy_topic(title: str = "", text: str = "", sumber_data: str = "") -> bool:
    """
    Memeriksa apakah artikel bertema industri / kebijakan pemerintah vs kesehatan / nutrisi pribadi / trivia:
    - industry_score > health_score : LOLOS (True)
    - health_score > industry_score : DIBUANG (False)
    - skor sama-sama 0 atau seri    : LOLOS by default (True) untuk teks berita formal
    - Khusus YouTube:
      * Tolak jika dominan musik/sound effect ([musik] >= 10 atau rasio > 15%)
      * Wajib minimal 2 sinyal industri (ind_score >= 2) untuk menyaring kata lepas di video trivia
    """
    combined = f"{title or ''} {text or ''}"
    ind_score = count_signal_occurrences(INDUSTRY_POLICY_SIGNALS, combined)
    health_score = count_signal_occurrences(HEALTH_PERSONAL_SIGNALS, combined)

    is_yt = (sumber_data or "").strip().lower() == "youtube" or "[musik]" in combined.lower()

    if is_yt:
        # 1. Tolak video dengan aksara non-Latin (Chinese/Japanese/Korean/Arabic) drama pendek auto-translate
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0600-\u06ff]", title or ""):
            return False

        # 2. Tolak video drama/skit/sinetron pendek
        title_lower = (title or "").lower()
        if any(tag in title_lower for tag in ["#drama", "#shortdrama", "#skit", "#alurcerita", "#sinetron", "#filmpendek", "#motivation"]):
            return False

        # 3. Tolak video katalog/toko mebel ritel
        if any(w in title_lower for w in ["grosir", "toko mebel", "toko furniture", "paket satua"]):
            return False

        # 4. Tolak video parade/karnaval musik latar tanpa dialog berita substantif
        musik_count = combined.lower().count("[musik]")
        words = len(combined.split())
        if musik_count >= 10 or (words > 0 and (musik_count / words) > 0.15):
            return False

        # 5. Tolak jika sinyal kesehatan/trivia lebih besar atau sama
        if health_score >= ind_score:
            return False

        # 6. Transkrip YouTube wajib memiliki minimal 3 sinyal industri agar tidak tertipu kata lepas
        if ind_score < 3:
            return False

        return True

    if health_score > ind_score:
        return False

    return True


# Sinyal eksplisit institusi Kemenperin (nama institusi langsung disebut)
EXPLICIT_KEMENPERIN_SIGNALS = [
    "kemenperin", "kementerian perindustrian", "menteri perindustrian",
    "menperin", "wamenperin", "wakil menteri perindustrian",
    "direktorat jenderal industri agro", "ditjen agro", "ditjen industri agro",
    "akademi komunitas bambu", "akademi komunitas bambu kemenperin",
]


def get_kemenperin_signal(
    title: str = "",
    text: str = "",
    spokesperson_map: dict | None = None,
    keyword: str = "",
    sumber_data: str = "",
) -> tuple[bool, str, str]:
    """
    Pengecekan KETAT dan SPESIFIK keterkaitan Kemenperin:
    HANYA bernilai True jika:
    1. Relevan dengan Ditjen Industri Agro secara substantif via is_agro_relevant_content(), ATAU
       menyebutkan pejabat spesifik Ditjen Industri Agro.
    2. Menyebut nama institusi secara eksplisit: "kemenperin", "kementerian perindustrian",
       "menperin", "wamenperin", "wakil menteri perindustrian", "direktorat jenderal industri agro",
       "ditjen agro", "ditjen industri agro" (word boundary matching), ATAU
    3. Mengutip salah satu nama pejabat di database (via find_spokespersons / match_name_in_text).
    
    Untuk pejabat lintas-direktorat (Menteri/Wamen/Sekjen/Irjen): HANYA lolos jika isi artikel
    BENAR-BENAR menyinggung komoditas Agro / Ditjen Industri Agro (bukan soal halal/batik/net zero/politik).
    """
    from entity_mapper import find_spokespersons

    clean_kw = (keyword or "").strip().lower()
    combined = f"{title or ''} {text or ''}"
    combined_lower = combined.lower()

    # Tolak kementerian luar negeri (misal Imarah Islam Afghanistan / Malaysia tanpa konteks RI)
    if "afghanistan" in combined_lower or "imarah islam" in combined_lower:
        return False, "NONE", ""

    # Tolak konten noise engagement media sosial (Shorts CTA / Q&A polling)
    if is_social_media_engagement_noise(title, text):
        return False, "NONE", ""

    # Cek apakah artikel substantif menyangkut Agro
    is_agro = is_agro_relevant_content(title, text)

    # Cek Spokesperson
    sp1, sp2, sp_unit = find_spokespersons(combined)
    is_specific_agro_official = (sp1.lower() in {
        "putu juli ardika", "merrijantij punguan", "dyan garneta",
        "rr citra rapati", "krisna septiningrum",
    })

    # 1. Cek Sumber Khusus Institusi / Pejabat / Direct Crawl
    if "pejabat_presisi" in clean_kw:
        if is_specific_agro_official or is_agro:
            return True, "EKSPLISIT", "pejabat_presisi"
        return False, "NONE", ""

    if clean_kw in ("pejabat_kemenperin", "pejabat kemenperin", "kemenperin_pejabat"):
        if is_specific_agro_official or is_agro:
            return True, "EKSPLISIT", "pejabat_kemenperin"
        return False, "NONE", ""

    if (sumber_data or "").strip().lower() == "direct crawl":
        if is_specific_agro_official or is_agro:
            return True, "EKSPLISIT", "Direct Crawl"
        return False, "NONE", ""

    # 2. Cek Sinyal Eksplisit Institusi
    for signal in EXPLICIT_KEMENPERIN_SIGNALS:
        if matches_word_boundary(signal, combined):
            if is_specific_agro_official or is_agro:
                return True, "EKSPLISIT", signal
            return False, "NONE", ""

    # 3. Cek Sinyal Pejabat di Database
    if sp1:
        if is_specific_agro_official or is_agro:
            return True, "IMPLISIT", sp1
        return False, "NONE", ""

    return False, "NONE", ""


def is_kemenperin_related(
    title: str = "",
    text: str = "",
    spokesperson_map: dict | None = None,
    keyword: str = "",
    sumber_data: str = "",
) -> bool:
    """
    Filter institusi ketat: Mengembalikan True HANYA jika artikel memiliki keterkaitan spesifik ke Kemenperin.
    """
    is_related, _, _ = get_kemenperin_signal(
        title=title, text=text, spokesperson_map=spokesperson_map, keyword=keyword, sumber_data=sumber_data
    )
    return is_related


_KEMENPERIN_OR_AGRO_PATTERN = re.compile(
    r"\b(kemenperin|kementerian\s+perindustrian|menteri\s+perindustrian|wamenperin|wakil\s+menteri\s+perindustrian|menperin|direktorat\s+jenderal\s+industri\s+agro|ditjen\s+agro|ditjen\s+industri\s+agro)\b",
    re.IGNORECASE,
)

_OFFICIALS_DETAILS_CACHE: list[dict] | None = None


def has_kemenperin_or_agro_override(title: str = "", text: str = "") -> bool:
    """
    Override khusus Kemenperin & Ditjen Industri Agro:
    Mengembalikan True jika salah satu terdeteksi pada title atau text (word boundary matching):
    1. Nama institusi: "kemenperin", "kementerian perindustrian", "menperin", "wamenperin",
       "direktorat jenderal industri agro", "ditjen agro" (atau "ditjen industri agro", "menteri perindustrian")
    2. Nama salah satu dari 13 pejabat di keyword_nama.xlsx (menggunakan match_name_in_text).
    """
    global _OFFICIALS_DETAILS_CACHE
    combined = f"{title or ''} {text or ''}"
    if not combined.strip():
        return False

    # 1. Cek regex nama institusi (sangat cepat)
    if _KEMENPERIN_OR_AGRO_PATTERN.search(combined):
        return True

    # 2. Cek nama salah satu dari 13 pejabat
    from entity_mapper import match_name_in_text
    if _OFFICIALS_DETAILS_CACHE is None:
        from config import load_spokesperson_details
        _OFFICIALS_DETAILS_CACHE = load_spokesperson_details()

    for d in _OFFICIALS_DETAILS_CACHE:
        for a in d.get("aliases", []):
            if match_name_in_text(a, combined):
                return True

    return False


# Alias backwards compatibility
has_ditjen_agro_override = has_kemenperin_or_agro_override


if __name__ == "__main__":
    assert is_non_article_document_noise("Template Jurnal IJCCS", "") is True
    assert is_non_article_document_noise("BAB II", "") is True
    assert is_non_article_document_noise("BAB 1. PENDAHULUAN 1 1.1 Latar Belakang Tepung terigu ...", "") is True
    assert is_non_article_document_noise("Daftar Isi", "") is True
    assert is_non_article_document_noise("Harga Kelapa Sumsel Terjun Bebas", "") is False
    assert is_social_media_engagement_noise("Menurut kamu, pelayanan publik yang ideal itu yang seperti apa sih? Share di kolom komentar, yuk!", "") is True
    assert is_social_media_engagement_noise("Yuk share di kolom komentar!", "") is True
    assert is_social_media_engagement_noise("Aturan Pasokan GKM Rafinasi: Kemenperin Tegaskan Tidak Ada Penambahan", "") is False
    # Check shorts
    assert is_shorts_entertainment_noise("part 1 Momen divine muncul diserver mamin #roblox #fyp #shorts #stealanegg", "") is True
    assert is_shorts_entertainment_noise("Kemenperin Resmikan Fasilitas Pengolahan Bambu di Bali", "") is False
    # Check pome
    assert is_pome_context_valid("Funny pome walking while hanging his one leg #pomeranian #dog #pets", "") is False
    assert is_pome_context_valid("PTPN IV PalmCo Olah Limbah POME Jadi Biogas EBT", "") is True
    # Check teh
    assert is_teh_context_valid("Tulus Masuk Nominasi AMI Awards Lewat Teh Hijau", "") is False
    assert is_teh_context_valid("TEH HIJAU Cover Trending ( Singing Battle ) #shorts", "") is False
    assert is_teh_context_valid("Petani Perkebunan Teh Jawa Barat Ekspor Daun Teh", "") is True
    # Check crime & accident
    assert is_crime_accident_noise("Densus 88 tangkap tiga terduga teroris di Sulteng", "") is True
    assert is_crime_accident_noise("Tabrakan Beruntun Truk Muatan Motor hingga Truk Sawit", "") is True
    assert is_crime_accident_noise("Order Makanan dan Minuman Rp1,2 Miliar, Dibayar Bilyet Giro Kosong, Pria di Baron Ditangkap di Depok", "") is True
    assert is_crime_accident_noise("Bea Cukai Sita 1 Juta Batang Rokok Ilegal di Kudus", "") is False
    assert is_crime_accident_noise("OJK dan Pemkab Kolaka Utara Bangun Ekosistem Kakao Terintegrasi", "") is False
    # Check placeholder & error titles
    assert is_placeholder_or_error_title("Resource discovery", "") is True
    assert is_placeholder_or_error_title("SIPP", "") is True
    assert is_placeholder_or_error_title("Beranda", "") is True
    assert is_placeholder_or_error_title("Informasi Paket", "") is True
    assert is_placeholder_or_error_title("Hilirisasi Sawit Nasional Capai Target", "") is False
    # Check viral medsos
    assert is_viral_social_media_drama("Video Bupati Siak Viral di Medsos, Wapres Gibran Kirim Tim Khusus ke Wilayah 3T", "") is True
    assert is_viral_social_media_drama("Harga TBS Sawit Riau Naik Pekan Ini", "") is False
    # Check lifestyle tourism
    assert is_lifestyle_tourism_noise("Kampung Coklat Blitar, Wisata Edukasi Kakao yang Menarik untuk Anak", "") is True
    assert is_lifestyle_tourism_noise("Kementan Perkuat Hilirisasi Kakao Nasional", "") is False
    # Check personal blog
    assert is_personal_blog_noise("Tektok Part 2, Bukit Lincing 1860 mdpL Halaman 1", "", "https://www.kompasiana.com/foo") is True
    assert is_personal_blog_noise("Harga Kopi Robusta Naik", "", "https://www.antaranews.com/bar") is False
    # Check police / kamtibmas
    assert is_crime_accident_noise("Polsek Pangkalan Susu Giatkan Patroli Dialogis, Pastikan Kamtibmas Desa Alur Cempedak Tetap Kondusi", "") is True
    assert is_crime_accident_noise("Gabungan Brimob Polda Lampung dan Polres Mesuji laksanakan patroli skala besar di areal PT PAL", "") is True
    assert is_crime_accident_noise("Polres Tuba Polda Lampung Gagalkan Penyelundupan 1,68 Juta Batang Rokok Ilegal", "") is False
    # Check celebrity gossip
    assert is_celebrity_entertainment("Singgung soal Minuman Beralkohol di Ruang Karaoke Betrand Peto", "") is True
    # Check retail enforcement
    assert is_local_retail_enforcement("Satpol PP Surabaya segel toko penjual minuman beralkohol eceran", "") is True
    assert is_local_retail_enforcement("Dukung Moratorium RHU, DPRD Surabaya Gagas Raperda Pengendalian Miras", "") is True
    assert is_local_retail_enforcement("Satpol PP Tulang Bawang Perkuat Pengawasan Usaha Karaoke", "") is True
    assert is_local_retail_enforcement("Bea Cukai Musnahkan Rokok Ilegal dan Minuman Beralkohol", "") is False
    assert is_local_retail_enforcement("DPRD Pasuruan Soroti Perlindungan Investasi Pabrik", "") is False
    # Check search result count placeholder
    assert is_placeholder_or_error_title("62.484 Peraturan ditemukan", "") is True

    # 5 POLA STRUKTURAL BARU (TAHAP 1)
    # 1. Deteksi nomor telepon / WA di judul
    assert has_phone_number_or_wa_in_title("Search - WA 0859 3970 0884 [[Hatiga Furniture]]...") is True
    assert has_phone_number_or_wa_in_title("Jual Mebel WA 081234567890") is True
    assert has_phone_number_or_wa_in_title("Pabrik Baru Dibuka Pukul 08.00 WIB Kemarin") is False
    # 2. Deteksi agregator placeholder
    assert is_aggregator_placeholder_title("Berita Terbaru Hari Ini - Kelapa") is True
    assert is_aggregator_placeholder_title("Berita Terkini - Industri Mebel") is True
    assert is_placeholder_or_error_title("Berita Terbaru Hari Ini - Kelapa", "") is True
    assert is_aggregator_placeholder_title("Menperin Resmikan Pabrik Pengolahan Kelapa") is False
    # 3. Deteksi galeri stock foto
    assert is_photo_stock_gallery_noise("900+ Foto Biskuit Pictures, Gambar dan Background untuk Unduh Gratis") is True
    assert is_photo_stock_gallery_noise("Biskuit Stock Photo and Royalty Free Images") is True
    assert is_photo_stock_gallery_noise("Presiden Resmikan Pabrik Biskuit Terbesar di Asia Tenggara") is False
    # 4. Deteksi campaign donasi
    assert is_donation_campaign_noise("Campaign - Bantu Wujudkan Renovasi Musholla Al-Ikhlas") is True
    assert is_donation_campaign_noise("Galang Dana Pembangunan Musholla") is True
    assert is_donation_campaign_noise("Kemenperin Wujudkan Kemandirian Industri Agro Nasional") is False
    # 5. Deteksi profil sekolah statis
    assert is_static_educational_profile_noise("SMK Negeri 1 Sarmi") is True
    assert is_static_educational_profile_noise("Profil SMKN 2 Kendal") is True
    assert is_static_educational_profile_noise("SMK Negeri 1 Sarmi Gelar Pameran Olahan Sagu") is False
    assert is_static_educational_profile_noise("Akademi Komunitas Bambu Kemenperin Buka Pendaftaran") is False
    # 6. Toko alat rumah tangga & di atas kertas
    assert is_promotional("Toko Alat Rumah Tangga Murah Meriah", "") is True
    assert is_kertas_context_valid("Di Atas Kertas Semua Setara", "") is False

    print("All relevance_filter self-checks passed successfully!")




