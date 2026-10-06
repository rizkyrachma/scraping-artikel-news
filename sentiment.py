"""
sentiment.py
Klasifikasi tone/sentimen berita industri berbasis aturan (Rule-based):
- NEGATIVE_SIGNALS: mendeteksi isu krisis, kerugian, kriminalitas, penyelundupan, kebakaran/karhutla, sengketa/protes.
- Default tone: Positif (karena berita industri/ekonomi formal yang tidak memuat masalah merupakan sentimen positif bagi industri).
"""

import re

# Daftar kata kunci sinyal negatif pada berita industri agro & manufaktur
NEGATIVE_SIGNALS = [
    # Krisis / Finansial / Bisnis / Penurunan Harga & Nilai
    r"\bphk\b", r"\bpemutusan hubungan kerja\b", r"\bbangkrut\b", r"\bpailit\b", r"\bgulung tikar\b",
    r"\banjlok\b", r"\bmerosot\b", r"\bterpuruk\b", r"\bdefisit\b",
    r"\bkerugian\b", r"\btutup pabrik\b", r"\bmenutup pabrik\b", r"\blesu\b",
    # Penurunan harga/nilai komoditas
    r"\bterjun\s+bebas\b", r"\bmelorot\b", r"\bturun\s+drastis\b", r"\bturun\s+tajam\b",
    r"\b(harga|nilai|kurs|rupiah)\b[^\.\,\;\:\!\?]{0,25}\bjatuh\b",
    r"\bjatuh\b[^\.\,\;\:\!\?]{0,25}\b(harga|nilai|kurs|rupiah|ke\s+rp|di\s+bawah)\b",
    r"\bjatuh\s+bebas\b",
    # Kelangkaan / Gangguan Pasokan / Krisis
    r"\blangka\b", r"\bkelangkaan\b", r"\bantre\b", r"\bantrean\b", r"\bmelonjak\b", r"\bmeroket\b",
    r"\bgagal panen\b", r"\bhama\b", r"\bkrisis\b",
    # Hukum / Kriminalitas / Ilegal / Penyelundupan / Cukai / Oplosan
    r"\bkorupsi\b", r"\bsuap\b", r"\bgratifikasi\b", r"\bpenyelundupan\b", r"\bselundup\b",
    r"\bilegal\b", r"\boplosan\b", r"\bmengoplos\b", r"\bpalsu\b", r"\btiruan\b",
    r"\bsita\b", r"\bdisita\b", r"\bpenyitaan\b", r"\brazia\b", r"\bgerebek\b", r"\bpenggerebekan\b",
    r"\bditangkap\b", r"\btertangkap\b", r"\bdiamankan\s+(polisi|petugas|aparat|tni|polres|polsek)\b", r"\bpenangkapan\b",
    r"\btersangka\b", r"\bterdakwa\b", r"\bdidakwa\b", r"\bdakwaan\b", r"\bpidana\b",
    r"\bpenjara\b", r"\bvonis\b", r"\bpenipuan\b", r"\bpenggelapan\b", r"\bmafia\b", r"\bkartel\b",
    # Bencana / Kecelakaan / Bahaya Lingkungan
    r"\bkebakaran\b", r"\bterbakar\b", r"\bhangus\b", r"\bledakan\b", r"\bmeledak\b",
    r"\bkarhutla\b", r"\bkarhulta\b", r"\brusak\b", r"\bbencana\b",
    r"\bkorban jiwa\b", r"\btewas\b", r"\bmeninggal dunia\b", r"\bluka-luka\b",
    r"\bkecelakaan\b", r"\bpencemaran\b", r"\blimbah beracun\b", r"\bracun\b",
    # Kriminal / Pelanggaran / Hukum
    r"\bcuri\b", r"\bpencuri\b", r"\bpencurian\b", r"\bmaling\b", r"\bmerugikan\b", r"\bterancam\b", r"\bancaman\b",
    # Konflik / Protes / Polemik
    r"\bdemo\b", r"\bdemonstrasi\b", r"\bunjuk rasa\b", r"\bmogok\b", r"\bboikot\b",
    r"\bprotes\b", r"\bmemprotes\b", r"\bpenolakan\b", r"\bmenolak\b", r"\bmengecam\b",
    r"\bkecaman\b", r"\bpolemik\b", r"\bkonflik\b", r"\bsengketa\b", r"\bgugatan\b",
    r"\bgugat\b", r"\bdigugat\b",
    # Keluhan / Kekhawatiran / Tuntutan Petani & Pemangku Kepentingan
    r"\bkeluhkan\b", r"\bmengeluh\b", r"\bkeluhan\b", r"\bdikeluhkan\b",
    r"\bkhawatir\b", r"\bkekhawatiran\b",
    r"\bdesak\b", r"\bmendesak\b", r"\bdesakan\b",
    r"\bresah\b", r"\bmeresahkan\b", r"\bkeresahan\b",
    r"\bwas-was\b", r"\bwas\s+was\b",
    r"\btuntut\b", r"\bmenuntut\b", r"\btuntutan\b",
]

# Sinyal positif pada berita industri & ekonomi
POSITIVE_SIGNALS = [
    r"\bpertumbuhan\b", r"\btumbuh\b", r"\bmeningkat\b", r"\bkenaikan\b", r"\bekspansi\b",
    r"\binvestasi\b", r"\bresmikan\b", r"\bmeresmikan\b", r"\bperkuat\b", r"\bmemperkuat\b",
    r"\bsurplus\b", r"\bsukses\b", r"\bprestasi\b", r"\bnaik kelas\b", r"\bapresiasi\b",
    r"\boptimis\b", r"\boptimisme\b", r"\bdorong\b", r"\bmendorong\b", r"\bdaya saing\b",
    r"\bpenghargaan\b", r"\bkinerja positif\b", r"\blaba\b", r"\buntung\b", r"\bkeuntungan\b",
    r"\bpotensi besar\b", r"\bkolaborasi\b", r"\bdukungan\b", r"\bterobosan\b", r"\binovasi\b",
    # Kemandirian, Prestasi, dan Kedaulatan Industri
    r"\bajaib\b", r"\btanaman ajaib\b", r"\bmiracle\b", r"\bmandiri\b", r"\bkemandirian\b",
    r"\bswasembada\b", r"\bberhasil\b", r"\bkeberhasilan\b", r"\bunggul\b", r"\bkeunggulan\b",
    r"\bkarunia\b", r"\bstrategis\b",
]

_NEG_REGEX = re.compile("|".join(NEGATIVE_SIGNALS), re.IGNORECASE)
_POS_REGEX = re.compile("|".join(POSITIVE_SIGNALS), re.IGNORECASE)

# Konjungsi pertentangan untuk mendeteksi mixed sentiment ("X, tapi/namun [masalah]")
CONTRAST_CONJUNCTIONS = re.compile(
    r"\b(tapi|tetapi|namun|meski|meskipun|walau|walaupun|sayangnya)\b",
    re.IGNORECASE
)

# Frasa negasi atau kata desakan/tuntutan yang membatalkan sinyal positif (misal: "tak naik", "desak kenaikan")
_NEGATION_OR_DEMAND_PATTERN = re.compile(
    r"\b(tak|tidak|belum|bukan|gagal|tanpa|kurang|desak|mendesak|tuntut|menuntut|minta|meminta)\s+(?:\w+\s+)?$",
    re.IGNORECASE
)


def count_effective_positive_signals(text: str) -> int:
    """
    Menghitung sinyal positif yang tidak didahului negasi (misal: 'tak naik', 'belum tumbuh')
    dan bukan merupakan objek desakan/tuntutan (misal: 'desak kenaikan', 'tuntut kenaikan').
    """
    if not text:
        return 0
    valid_count = 0
    for match in _POS_REGEX.finditer(text):
        start = match.start()
        prefix = text[max(0, start - 35):start]
        if _NEGATION_OR_DEMAND_PATTERN.search(prefix):
            continue
        valid_count += 1
    return valid_count


def classify_tone(text: str = "", title: str = "") -> str:
    """
    Mengklasifikasikan tone artikel secara rule-based (Positif, Netral, Negatif):
    1. Pola pertentangan di judul ("X, tapi/namun [sinyal negatif]"): Prioritaskan 'Negatif'.
    2. Jika terdapat sinyal negatif kuat di judul atau frekuensi negatif dominan -> 'Negatif'
    3. Jika terdapat sinyal positif kuat di judul atau frekuensi positif dominan -> 'Positif'
    4. Selain itu (berita informatif umum, kuotasi harga rutin, atau sinyal seimbang) -> 'Netral'
    """
    combined_title = (title or "").strip()
    combined_text = (text or "").strip()
    combined_all = f"{combined_title} {combined_text}"

    # 1. Penanganan judul berpola "X, TAPI/NAMUN Y NEGATIF" (Mixed Sentiment)
    if combined_title:
        contrast_match = CONTRAST_CONJUNCTIONS.search(combined_title)
        if contrast_match:
            after_contrast = combined_title[contrast_match.end():]
            if _NEG_REGEX.search(after_contrast):
                return "Negatif"

    # 2. Cek di judul terlebih dahulu
    title_neg = len(_NEG_REGEX.findall(combined_title)) if combined_title else 0
    title_pos = count_effective_positive_signals(combined_title) if combined_title else 0

    if title_neg > title_pos:
        return "Negatif"
    if title_pos > title_neg:
        return "Positif"

    # 3. Cek frekuensi di teks keseluruhan
    total_neg = len(_NEG_REGEX.findall(combined_all))
    total_pos = count_effective_positive_signals(combined_all)

    if total_neg >= 2 and total_neg > total_pos:
        return "Negatif"
    if total_pos >= 2 and total_pos > total_neg:
        return "Positif"

    return "Netral"


if __name__ == "__main__":
    # Self-check assert: 5 target headlines and edge cases
    assert classify_tone("", "Harga Kelapa Sumsel Terjun Bebas, dari Rp4.000 Kini Tinggal Rp1.800 per Butir") == "Negatif"
    assert classify_tone("", "Hilirisasi Kelapa Potensi Perkuat Ekonomi, Tapi Harga Pasar Anjlok") == "Negatif"
    assert classify_tone("", "HPP Gula Tak Naik 3 Tahun, Petani Tebu Desak Kenaikan Jadi Rp15.500 per Kg") == "Negatif"
    assert classify_tone("", "APTRI Keluhkan Impor Gula 150 Ribu Ton saat Musim Giling") == "Negatif"
    assert classify_tone("", "Petani Tebu Khawatir Pemerintah Buka Impor 150 Ribu Ton Gula") == "Negatif"
    assert classify_tone("", "Kemenperin Dorong Hilirisasi Industri Kelapa Sawit") == "Positif"
    assert classify_tone("", "Prabowo: Kelapa Sawit Adalah Tanaman Ajaib, The Miracle Plant") == "Positif"
    print("All sentiment self-checks passed successfully!")



