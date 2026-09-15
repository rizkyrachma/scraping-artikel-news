"""
entity_mapper.py
Pencocokan nama pejabat, spokesperson (1 & 2), dan unit eselon dari teks artikel
menggunakan kombinasi exact match berbasis word boundary dan fuzzy matching (rapidfuzz).
"""

import re
from rapidfuzz import fuzz


def match_name_in_text(name: str, text: str, threshold: int = 85) -> bool:
    """
    Mencocokkan nama dalam teks dengan proteksi word boundary:
    1. Exact match berbasis regex \\b...\\b
    2. Fuzzy match berbasis window n-gram kata berurutan untuk mencegah substring bug
       (misal kata 'bagus' tidak boleh memicu match 100% untuk nama 'agus').
    """
    # 1. Exact match berbasis word boundary
    if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
        return True

    # 2. Fuzzy match pada window n-gram kata
    words = re.findall(r"\b\w+\b", text.lower())
    n = len(name.split())
    if len(words) < n:
        return False

    for i in range(len(words) - n + 1):
        window = " ".join(words[i : i + n])
        if fuzz.ratio(name, window) >= threshold:
            return True

    return False


def find_spokespersons(
    text: str,
    name_map: dict[str, str],
    threshold: int = 85,
) -> tuple[str, str, str]:
    """
    Mencocokkan nama pejabat dari name_map pada teks isi artikel:
    - Cek exact match dan fuzzy match dengan batas kata (word boundary)
    - Mengambil maksimal 2 nama pertama yang cocok sebagai Spokesperson 1 dan 2
    - Mengambil Unit Eselon dari jabatan Spokesperson 1

    Returns:
        tuple (spokesperson_1, spokesperson_2, unit_eselon)
    """
    if not text or not name_map:
        return "", "", ""

    candidates = list(name_map.keys())

    found = []
    for name in candidates:
        if match_name_in_text(name, text, threshold=threshold):
            found.append(name)

    found = found[:2]  # Maksimal 2 sesuai kolom Spokesperson 1 & 2

    spokesperson_1 = found[0].title() if len(found) > 0 else ""
    spokesperson_2 = found[1].title() if len(found) > 1 else ""
    unit_eselon = name_map.get(found[0], "") if found else ""

    return spokesperson_1, spokesperson_2, unit_eselon
