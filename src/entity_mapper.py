"""
entity_mapper.py
Pencocokan nama pejabat, spokesperson (1 & 2), dan unit eselon dari teks artikel
menggunakan kombinasi exact match berbasis word boundary dan fuzzy matching (rapidfuzz).
"""

import re
from rapidfuzz import fuzz


COMMON_NAME_PREFIX_STOPWORDS = {
    "dan", "di", "ke", "dari", "yang", "pada", "untuk", "dengan", "oleh",
    "atau", "saat", "ini", "itu", "juga", "kita", "bisa", "akan", "ada",
    "tersebut", "tentang", "seperti", "jika", "karena", "maka", "adalah",
}


def match_name_in_text(name: str, text: str, threshold: int = 90) -> bool:
    """
    Mencocokkan nama dalam teks dengan proteksi word boundary:
    1. Exact match berbasis regex \\b...\\b
    2. Fuzzy match berbasis window n-gram kata berurutan untuk mencegah substring bug
       dengan proteksi stop words (misal 'dan greta' tidak boleh memicu 'dyan garneta').
    """
    # 1. Exact match berbasis word boundary
    if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
        return True

    # 2. Fuzzy match pada window n-gram kata
    # Khusus akronim jabatan sensitif (menperin vs wamenperin), tidak boleh fuzzy match
    if name.lower() in ("wamenperin", "menperin"):
        return False

    words = re.findall(r"\b\w+\b", text.lower())
    name_words = name.lower().split()
    n = len(name_words)
    if len(words) < n:
        return False

    for i in range(len(words) - n + 1):
        w_slice = words[i : i + n]
        # Tolak window jika kata pertama adalah stop word umum bahasa Indonesia
        if w_slice[0] in COMMON_NAME_PREFIX_STOPWORDS and name_words[0] not in COMMON_NAME_PREFIX_STOPWORDS:
            continue
        # Untuk nama multi-kata, kata pertama harus cukup mirip (>= 85%)
        if n > 1 and fuzz.ratio(name_words[0], w_slice[0]) < 85:
            continue
        window = " ".join(w_slice)
        if fuzz.ratio(name.lower(), window) >= threshold:
            return True

    return False


def find_spokespersons(
    text: str,
    name_map: dict[str, str] | None = None,
    threshold: int = 90,
) -> tuple[str, str, str]:
    """
    Mencocokkan nama pejabat pada teks isi artikel:
    - Cek alias nama pejabat dengan word boundary exact match & fuzzy match
    - Diurutkan berdasarkan KEMUNCULAN PERTAMA di teks (earliest position)
    - Mengambil maksimal 2 nama pertama yang cocok sebagai Spokesperson 1 dan 2
    - Mengambil Unit Eselon dari database pejabat untuk Spokesperson 1

    Returns:
        tuple (spokesperson_1, spokesperson_2, unit_eselon)
    """
    if not text:
        return "", "", "-"

    from config import load_spokesperson_details
    details = load_spokesperson_details()

    matches = []
    for official in details:
        earliest_pos = None
        for alias in official.get("aliases", []):
            # 1. Exact match regex dengan word boundary
            m = re.search(rf"\b{re.escape(alias)}\b", text, flags=re.IGNORECASE)
            if m:
                pos = m.start()
                if earliest_pos is None or pos < earliest_pos:
                    earliest_pos = pos

            # 2. Fuzzy match fallback
            if earliest_pos is None and alias.lower() not in ("wamenperin", "menperin"):
                words = re.findall(r"\b\w+\b", text.lower())
                alias_words = alias.lower().split()
                n = len(alias_words)
                if len(words) >= n:
                    for i in range(len(words) - n + 1):
                        w_slice = words[i : i + n]
                        if w_slice[0] in COMMON_NAME_PREFIX_STOPWORDS and alias_words[0] not in COMMON_NAME_PREFIX_STOPWORDS:
                            continue
                        if n > 1 and fuzz.ratio(alias_words[0], w_slice[0]) < 85:
                            continue
                        window = " ".join(w_slice)
                        if fuzz.ratio(alias.lower(), window) >= threshold:
                            # Perkiraan posisi karakter
                            sub_idx = text.lower().find(words[i])
                            if sub_idx != -1:
                                if earliest_pos is None or sub_idx < earliest_pos:
                                    earliest_pos = sub_idx
                            break

        if earliest_pos is not None:
            matches.append((earliest_pos, official["nama"], official.get("unit_eselon", "-")))

    if not matches:
        return "", "", "-"

    # Urutkan berdasarkan posisi kemunculan pertama di dalam teks artikel
    matches.sort(key=lambda x: x[0])

    spokesperson_1 = matches[0][1] if len(matches) > 0 else ""
    unit_eselon = matches[0][2] if len(matches) > 0 else "-"
    spokesperson_2 = matches[1][1] if len(matches) > 1 else ""

    return spokesperson_1, spokesperson_2, unit_eselon

