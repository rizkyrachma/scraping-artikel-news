"""
sentiment.py
Klasifikasi tone/sentimen berita industri berbasis aturan (Rule-based):
- NEGATIVE_SIGNALS: mendeteksi isu krisis, kerugian, kriminalitas, penyelundupan, kebakaran/karhutla, sengketa/protes.
- Default tone: Positif (karena berita industri/ekonomi formal yang tidak memuat masalah merupakan sentimen positif bagi industri).
"""

import re

# Daftar kata kunci sinyal negatif pada berita industri agro & manufaktur
NEGATIVE_SIGNALS = [
    # Krisis / Finansial / Bisnis
    r"\bphk\b", r"\bpemutusan hubungan kerja\b", r"\bbangkrut\b", r"\bpailit\b", r"\bgulung tikar\b",
    r"\banjlok\b", r"\bmerosot\b", r"\bterpuruk\b", r"\bdefisit\b",
    r"\bkerugian\b", r"\btutup pabrik\b", r"\bmenutup pabrik\b", r"\blesu\b",
    # Kelangkaan / Gangguan Pasokan / Krisis
    r"\blangka\b", r"\bkelangkaan\b", r"\bantre\b", r"\bantrean\b", r"\bmelonjak\b", r"\bmeroket\b",
    r"\bgagal panen\b", r"\bhama\b", r"\bkrisis\b",
    # Hukum / Kriminalitas / Ilegal / Penyelundupan / Cukai / Oplosan
    r"\bkorupsi\b", r"\bsuap\b", r"\bgratifikasi\b", r"\bpenyelundupan\b", r"\bselundup\b",
    r"\bilegal\b", r"\boplosan\b", r"\bmengoplos\b", r"\bpalsu\b", r"\btiruan\b",
    r"\bsita\b", r"\bdisita\b", r"\bpenyitaan\b", r"\brazia\b", r"\bgerebek\b", r"\bpenggerebekan\b",
    r"\bditangkap\b", r"\bpenangkapan\b", r"\btersangka\b", r"\bterdakwa\b", r"\bdidakwa\b", r"\bdakwaan\b", r"\bpidana\b",
    r"\bpenjara\b", r"\bvonis\b", r"\bpenipuan\b", r"\bpenggelapan\b", r"\bmafia\b", r"\bkartel\b",
    # Bencana / Kecelakaan / Bahaya Lingkungan
    r"\bkebakaran\b", r"\bterbakar\b", r"\bhangus\b", r"\bledakan\b", r"\bmeledak\b",
    r"\bkarhutla\b", r"\bkarhulta\b", r"\brusak\b", r"\bbencana\b",
    r"\bkorban jiwa\b", r"\btewas\b", r"\bmeninggal dunia\b", r"\bluka-luka\b",
    r"\bkecelakaan\b", r"\bpencemaran\b", r"\blimbah beracun\b", r"\bracun\b",
    # Kriminal / Pelanggaran / Hukum
    r"\bcuri\b", r"\bpencurian\b", r"\bmerugikan\b", r"\bterancam\b", r"\bancaman\b",
    # Konflik / Protes / Keluhan / Polemik
    r"\bdemo\b", r"\bdemonstrasi\b", r"\bunjuk rasa\b", r"\bmogok\b", r"\bboikot\b",
    r"\bprotes\b", r"\bmemprotes\b", r"\bpenolakan\b", r"\bmenolak\b", r"\bmengecam\b",
    r"\bkecaman\b", r"\bpolemik\b", r"\bkonflik\b", r"\bsengketa\b", r"\bgugatan\b",
    r"\bgugat\b", r"\bdigugat\b", r"\bkeluhan\b", r"\bdikeluhkan\b", r"\bresah\b",
]

# Sinyal positif pada berita industri & ekonomi
POSITIVE_SIGNALS = [
    r"\bpertumbuhan\b", r"\btumbuh\b", r"\bmeningkat\b", r"\bkenaikan\b", r"\bekspansi\b",
    r"\binvestasi\b", r"\bresmikan\b", r"\bmeresmikan\b", r"\bperkuat\b", r"\bmemperkuat\b",
    r"\bsurplus\b", r"\bsukses\b", r"\bprestasi\b", r"\bnaik kelas\b", r"\bapresiasi\b",
    r"\boptimis\b", r"\boptimisme\b", r"\bdorong\b", r"\bmendorong\b", r"\bdaya saing\b",
    r"\bpenghargaan\b", r"\bkinerja positif\b", r"\blaba\b", r"\buntung\b", r"\bkeuntungan\b",
    r"\bpotensi besar\b", r"\bkolaborasi\b", r"\bdukungan\b", r"\bterobosan\b", r"\binovasi\b",
]

_NEG_REGEX = re.compile("|".join(NEGATIVE_SIGNALS), re.IGNORECASE)
_POS_REGEX = re.compile("|".join(POSITIVE_SIGNALS), re.IGNORECASE)


def classify_tone(text: str = "", title: str = "") -> str:
    """
    Mengklasifikasikan tone artikel secara rule-based (Positif, Netral, Negatif):
    - Jika terdapat sinyal negatif kuat di judul atau frekuensi negatif dominan -> 'Negatif'
    - Jika terdapat sinyal positif kuat di judul atau frekuensi positif dominan -> 'Positif'
    - Selain itu (berita informatif umum, kuotasi harga rutin, atau sinyal seimbang) -> 'Netral'
    """
    combined_title = (title or "").strip()
    combined_text = (text or "").strip()
    combined_all = f"{combined_title} {combined_text}"

    # Cek di judul terlebih dahulu
    title_neg = len(_NEG_REGEX.findall(combined_title)) if combined_title else 0
    title_pos = len(_POS_REGEX.findall(combined_title)) if combined_title else 0

    if title_neg > title_pos:
        return "Negatif"
    if title_pos > title_neg:
        return "Positif"

    # Cek frekuensi di teks keseluruhan
    total_neg = len(_NEG_REGEX.findall(combined_all))
    total_pos = len(_POS_REGEX.findall(combined_all))

    if total_neg >= 2 and total_neg > total_pos:
        return "Negatif"
    if total_pos >= 2 and total_pos > total_neg:
        return "Positif"

    return "Netral"


