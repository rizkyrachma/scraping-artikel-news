"""
relevance_filter.py
Filter relevansi artikel berbasis judul dan cuplikan teks menggunakan pencocokan word boundary (regex \\b...\\b):
1. Menyaring artikel non-industri (kesehatan/gaya hidup murni)
2. Menyaring konten resep/kuliner (is_recipe)
3. Menyaring materi promosi/iklan ritel (is_promotional)
"""

import re

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
]

# Kata kunci konten resep / kuliner
RECIPE_WORDS = [
    "resep", "bahan-bahan", "cara membuat", "cara memasak", "sendok teh",
    "sendok makan", "bumbu halus", "adonan", "kukus", "panggang", "tumis",
]

# Kata kunci promosi / iklan ritel
PROMO_WORDS = [
    "syarat dan ketentuan", "syarat & ketentuan", "periode promo",
    "dapatkan", "diskon", "supermarket", "minimal pembelian",
    "minimum transaksi", "cashback", "voucher", "katalog promo",
    "harga promo", "promo bca",
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


def is_likely_relevant(title: str) -> bool:
    """
    Memeriksa relevansi awal berdasarkan judul menggunakan regex word boundary:
    - Return False jika judul mengandung salah satu HEALTH_LIFESTYLE_WORDS
      DAN tidak mengandung satu pun INDUSTRY_CONTEXT_WORDS.
    - Return True untuk kasus lainnya.
    """
    if not title:
        return True

    has_health_word = any_word_boundary_match(HEALTH_LIFESTYLE_WORDS, title)
    has_industry_word = any_word_boundary_match(INDUSTRY_CONTEXT_WORDS, title)

    if has_health_word and not has_industry_word:
        return False

    return True


def is_recipe(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi apakah artikel merupakan konten resep / panduan memasak kuliner:
    - Judul atau 300 karakter awal memuat indikator resep kuat ('resep', 'cara membuat', 'bahan-bahan')
    - Atau terdapat pola takaran bahan berulang (misal '150 gram', '2 sendok makan', dll.)
    """
    title_text = title or ""
    snippet = text[:300] if text else ""

    # 1. Cek indikator kata resep di judul atau 300 karakter pertama
    if any_word_boundary_match(["resep", "cara membuat", "cara memasak"], title_text):
        return True
    if any_word_boundary_match(RECIPE_WORDS, snippet):
        return True

    # 2. Cek pola format takaran bahan berulang di 300 karakter pertama
    measurement_pattern = r"\b\d+[\s\w]*(gram|gr|ml|mililiter|sendok makan|sendok teh|sdm|sdt|butir|lembar|siung)\b"
    matches = re.findall(measurement_pattern, snippet, flags=re.IGNORECASE)
    if len(matches) >= 2:
        return True

    return False


def is_promotional(title: str = "", text: str = "") -> bool:
    """
    Mendeteksi apakah artikel merupakan materi promosi / iklan ritel komersial:
    - Judul atau 300 karakter awal teks memuat frasa PROMO_WORDS
    """
    title_text = title or ""
    snippet = text[:300] if text else ""
    combined = f"{title_text} {snippet}"

    return any_word_boundary_match(PROMO_WORDS, combined)


def count_keyword_occurrences(text: str, keyword: str) -> int:
    """
    Menghitung jumlah kemunculan keyword dalam teks menggunakan word boundary (\\b...\\b).
    """
    if not text or not keyword:
        return 0
    pattern = rf"\b{re.escape(keyword)}\b"
    return len(re.findall(pattern, text, flags=re.IGNORECASE))


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

    search_terms = [keyword]
    OFFICIAL_NAMES = [
        "agus gumiwang", "putu juli ardika", "merrijantij punguan",
        "dyan garneta", "rr citra rapati", "krisna septiningrum",
    ]
    kw_lower = keyword.lower()
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

# Sinyal kata kunci artikel kesehatan / nutrisi pribadi
HEALTH_PERSONAL_SIGNALS = [
    "kesehatan tubuh", "gizi", "diet", "kalori", "diabetes",
    "gula darah", "kemenkes", "puskesmas", "manfaat", "khasiat",
    "efek samping", "penyakit", "menu sarapan", "menu sehat",
    "pola makan", "asupan", "konsumsi harian", "tips kesehatan",
    "detoksifikasi", "resep",
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


def is_industry_policy_topic(title: str = "", text: str = "") -> bool:
    """
    Memeriksa apakah artikel bertema industri / kebijakan pemerintah vs kesehatan / nutrisi pribadi:
    - industry_score > health_score : LOLOS (True)
    - health_score > industry_score : DIBUANG (False)
    - skor sama-sama 0 atau seri    : LOLOS by default (True)
    """
    combined = f"{title or ''} {text or ''}"
    ind_score = count_signal_occurrences(INDUSTRY_POLICY_SIGNALS, combined)
    health_score = count_signal_occurrences(HEALTH_PERSONAL_SIGNALS, combined)

    if health_score > ind_score:
        return False

    return True


# Sinyal eksplisit institusi Kemenperin (nama institusi langsung disebut)
EXPLICIT_KEMENPERIN_SIGNALS = [
    "kemenperin", "kementerian perindustrian", "menperin",
    "wamenperin", "wakil menteri perindustrian", "direktorat jenderal industri agro",
    "ditjen agro", "ditjen industri agro",
]


def get_kemenperin_signal(
    title: str = "", text: str = "", spokesperson_map: dict | None = None
) -> tuple[bool, str, str]:
    """
    Mengecek apakah artikel terkait Kemenperin melalui sinyal EKSPLISIT atau IMPLISIT:
    1. SINYAL EKSPLISIT: Menyebut nama institusi Kemenperin dalam EXPLICIT_KEMENPERIN_SIGNALS
       menggunakan word boundary matching regex.
    2. SINYAL IMPLISIT: Mengutip salah satu nama pejabat dari spokesperson_map
       menggunakan match_name_in_text() dari entity_mapper.py.

    Returns:
        tuple (is_related: bool, signal_type: str, matched_detail: str)
        - signal_type: 'EKSPLISIT', 'IMPLISIT', atau 'NONE'
        - matched_detail: frasa eksplisit atau nama pejabat yang terdeteksi
    """
    from entity_mapper import match_name_in_text

    if spokesperson_map is None:
        try:
            from config import load_spokesperson_map
            spokesperson_map = load_spokesperson_map()
        except Exception:
            spokesperson_map = {}

    combined = f"{title or ''} {text or ''}"

    # 1. Cek Sinyal Eksplisit
    for signal in EXPLICIT_KEMENPERIN_SIGNALS:
        if matches_word_boundary(signal, combined):
            return True, "EKSPLISIT", signal

    # 2. Cek Sinyal Implisit (dari spokesperson_map)
    for official_name in spokesperson_map.keys():
        if match_name_in_text(official_name, combined):
            return True, "IMPLISIT", official_name

    return False, "NONE", ""


def is_kemenperin_related(
    title: str = "", text: str = "", spokesperson_map: dict | None = None
) -> bool:
    """
    Filter institusi: Mengembalikan True jika artikel memiliki sinyal EKSPLISIT atau IMPLISIT Kemenperin,
    False jika tidak ada sama sekali.
    """
    is_related, _, _ = get_kemenperin_signal(title, text, spokesperson_map)
    return is_related
