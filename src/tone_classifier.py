"""
tone_classifier.py
Klasifikasi Tone/Sentimen Berita Media Monitoring Kemenperin (Ditjen Industri Agro):
- Rujukan utama: Dokumen Biro Humas Kemenperin
  docs/Indikator_Sentimen_Pemberitaan_dalam_Media_Monitoring.docx
  (Indikator Sentimen Pemberitaan dalam Media Monitoring: peran dan sikap pemberitaan
  terhadap Kemenperin, bukan kesan baik/buruk topik ekonomi semata).
- Kerangka penilaian dua langkah: hubungan (K1..K4) x arah (mendukung/tidak ada/menyerang).
- Penilai Utama: Gemini API + fallback rule-based berbasis config/alias_kemenperin.json
  serta pemakaian ulang deteksi Kemenperin (get_kemenperin_signal / find_spokespersons).
- Pembatasan keyakinan maksimal 'sedang' bila artikel/klaster hanya memiliki judul tanpa teks isi.
- Pencatatan log ke hasil_scrapping/log_tone.jsonl (tanpa menambah kolom baru di Excel).
"""

import hashlib
import os
import sys
import re
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

# Load environment variable
try:
    from src.config import load_env_file
    load_env_file()
except Exception:
    pass

from src.gemini_pool import CANDIDATE_MODELS, GeminiModelPool
from src.stable import canonical_url, get_decision_cache

TONE_PROMPT_VERSION = "v2026-11-18-d"
USE_COMBINED_ISU_TONE = os.environ.get("USE_COMBINED_ISU_TONE", "true").strip().lower() in ("1", "true", "yes", "on")

# ASUMSI SEMENTARA (menunggu konfirmasi resmi Biro Humas Kemenperin):
ASUMSI_K4_NETRAL = True  # K4 (tidak berkaitan dengan Kemenperin) diasumsikan Netral
ASUMSI_A1_KONDISI_INDUSTRI_NETRAL = True  # A1: kondisi industri memburuk tanpa serangan ke Kemenperin -> Netral
ASUMSI_A2_DESAKAN_UMUM_PEMERINTAH_NETRAL = True  # A2: desakan ke 'pemerintah' umum tanpa kritik Kemenperin -> Netral
ASUMSI_A3_KEBIJAKAN_INSTANSI_LAIN_NON_KEMENPERIN = True  # A3: kebijakan/kritik instansi lain tanpa libatkan Kemenperin -> tidak Negatif/Positif
ASUMSI_A4_KATA_NEGATIF_BUKAN_PEMICU = True  # A4: kata negatif di judul bukan pemicu otomatis tanpa arah ke Kemenperin
ASUMSI_A5_RAGU_PILIH_NETRAL = True  # A5: bila ragu antara Negatif/Netral atau Positif/Netral -> Netral
TONE_ISU_MENGIKUTI_PERISTIWA = True  # Pertanyaan Humas #3: anggota isu peristiwa K1 mengikuti tone isu K1 kecuali outlier

DEFAULT_KEMENPERIN_ALIAS_PATH = os.path.join("config", "alias_kemenperin.json")

_MODEL_POOL = GeminiModelPool("TONE CLASSIFIER")
gemini_quota_exhausted = False
TOTAL_API_CALLS = 0


def get_api_call_count() -> int:
    global TOTAL_API_CALLS
    return TOTAL_API_CALLS


def reset_api_call_count():
    global TOTAL_API_CALLS
    TOTAL_API_CALLS = 0


LOG_TONE_FILE = os.path.join("hasil_scrapping", "log_tone.jsonl")


TONE_RULES = """PERAN
Kamu adalah analis media monitoring untuk Biro Humas dan Ditjen Industri Agro, Kementerian Perindustrian (Kemenperin).
Dasar penilaian WAJIB mengikuti indikator Biro Humas Kemenperin: menilai PERAN dan SIKAP pemberitaan terhadap Kemenperin, BUKAN menilai baik/buruknya angka ekonomi industri semata.

=== KERANGKA PENILAIAN DUA LANGKAH ===
Langkah 1, tentukan "hubungan" berita dengan Kemenperin (pilih satu):
 K1: Kemenperin (institusi, Menperin, Wamenperin, Sekjen, Dirjen, juru bicara resmi) menjadi pelaku atau narasumber utama.
 K2: Kemenperin (institusi atau person atas jabatannya di Kemenperin) disebut hanya sebagai pelengkap atau bagian kecil pemberitaan.
 K3: Kemenperin tidak disebut secara langsung, tetapi isunya berkaitan dengan kebijakan, kepentingan, atau program kerja Kemenperin.
 K4: Tidak berkaitan dengan Kemenperin.

Langkah 2, tentukan "arah" sikap terhadap Kemenperin (pilih satu):
 "mendukung", "tidak ada", atau "menyerang".

=== INDIKATOR BIRO HUMAS & PEMETAAN TONE ===
POSITIF:
 P1. K1 + mendukung atau tidak ada serangan: berita memuat aktivitas, pendapat, pernyataan, kutipan, atau laporan yang dimunculkan institusi atau narasumber Kemenperin untuk kepentingan dan eksistensi Kemenperin.
 P2. K3 + mendukung: berita bersumber dari pihak lain dan berisi materi, aktivitas, pendapat, pernyataan, kutipan, atau laporan yang mendukung kebijakan atau eksistensi Kemenperin.

NETRAL:
 Ne1. K2 + tidak ada serangan: menyebut nama Kemenperin (institusi atau pejabat) hanya sebagai pelengkap atau bagian kecil dari pemberitaan.
 Ne2. K3 + tidak ada dukungan atau serangan jelas: isu berkaitan dengan kebijakan, kepentingan, atau program kerja Kemenperin tetapi tidak menyebut institusi atau narasumber Kemenperin secara langsung.
 K4 (asumsi sementara): tidak berkaitan dengan Kemenperin -> Netral.

NEGATIF:
 N1. K1 atau K2 + menyerang: menyebut Kemenperin atau narasumber Kemenperin tetapi penyebutan itu menyerang dan menyudutkan eksistensi Kemenperin.
 N2. K1 atau K2 + menyerang: isu korupsi dan aktivitas yang bertentangan dengan hukum atau nilai moral masyarakat sehingga menyerang kepentingan dan eksistensi lembaga maupun person Kemenperin (catat: sosialisasi antikorupsi resmi oleh Kemenperin BUKAN pelanggaran dan tetap Positif P1).
 N3. K1 + berseberangan: memuat aktivitas, pendapat, pernyataan, kutipan, atau laporan dari institusi atau narasumber Kemenperin yang berseberangan dengan kepentingan dan eksistensi Kemenperin.
 N4. K3 + menyerang: berita bersumber dari pihak lain dan berisi materi, aktivitas, pendapat, pernyataan, kutipan, atau laporan yang menyerang kebijakan atau eksistensi Kemenperin.

=== ATURAN WAJIB & PEMBATAS TAFSIR ===
A1. Kondisi industri yang memburuk (ekspor turun, PHK, harga anjlok, pabrik tutup) TIDAK otomatis Negatif. Negatif hanya bila ada serangan atau sorotan buruk yang diarahkan ke Kemenperin atau kebijakannya. Tanpa serangan ke Kemenperin, nilai Netral.
A2. Permintaan atau desakan asosiasi kepada "pemerintah" secara umum tanpa menyebut Kemenperin dan tanpa mengkritik kebijakannya adalah Netral (K3 atau K4).
A3. Kebijakan atau sorotan terhadap instansi lain (misalnya ESDM, Kementan, Kemenkeu, KKP) yang tidak melibatkan Kemenperin bukan alasan Negatif atau Positif bagi Kemenperin.
A4. Kata bernada negatif di judul bukan pemicu otomatis. Nilai arah pemberitaan terhadap Kemenperin.
A5. Bila ragu antara Negatif dan Netral, atau antara Positif dan Netral, pilih Netral.
- Kejujuran "dasar": isi "judul" jika keputusan dan alasan hanya memakai informasi di judul, isi "isi" jika memakai teks/cuplikan isi. Membedakan K1 (pelaku utama) dan K2 (pelengkap) idealnya memeriksa teks isi. Jika teks isi tidak tersedia, bersikap konservatif.
- Negasi (tidak, tak, bukan, belum, tanpa, nihil, bebas dari, batal) membalik makna frasa setelahnya.

=== CONTOH BENCHMARK INDIKATOR ===
Positif:
- "Menperin Luncurkan Pusat Inovasi Agro untuk Tingkatkan Daya Saing Industri" -> K1, mendukung, Positif (P1)
- "Kemenperin Siapkan Strategi Antisipasi Pelemahan Permintaan Tekstil" -> K1, mendukung, Positif (P1, langkah Kemenperin meski ada kata pelemahan A4)
- "Asosiasi Industri Apresiasi Kebijakan TKDN yang Terbukti Melindungi Pabrik Lokal" -> K3, mendukung, Positif (P2)
Netral:
- "Pemprov Buka Pameran UMKM, Perwakilan Kemenperin Turut Hadir Meninjau Stan" -> K2, tidak ada, Netral (Ne1, Kemenperin hanya pelengkap)
- "Harga Komoditas Anjlok, Pabrik Kurangi Jam Produksi Akibat Lesunya Pasar" -> K3, tidak ada, Netral (Ne2 + A1, tanpa serangan ke Kemenperin)
- "Asosiasi Minta Pemerintah Jaga Stabilitas Pasokan Bahan Baku Industri" -> K3, tidak ada, Netral (Ne2 + A2, desakan umum tanpa serang Kemenperin)
- "Nelayan Kritik Kebijakan Kementerian Kelautan soal Kuota Tangkap" -> K4, tidak ada, Netral (A3, instansi lain tanpa libatkan Kemenperin)
- "Kejuaraan Olahraga Pelajar Digelar di Kota Bandung" -> K4, tidak ada, Netral (tidak berkaitan Kemenperin)
Negatif:
- "Koalisi Pengusaha Kritik Keras Kebijakan Kemenperin yang Dinilai Hambat Industri" -> K1, menyerang, Negatif (N1)
- "Kejaksaan Selidiki Dugaan Korupsi dan Suap Izin di Lingkungan Kemenperin" -> K1, menyerang, Negatif (N2)
- "Pejabat Kemenperin Akui Kegagalan Program Pembinaan dan Menyesalkan Lemahnya Pengawasan" -> K1, menyerang, Negatif (N3)
- "Pelaku Usaha Gugat Aturan TKDN dan Regulasi Industri karena Dianggap Merugikan Pabrik" -> K3, menyerang, Negatif (N4)"""

TONE_ARTICLE_FORMAT = """FORMAT OUTPUT
Isi "hubungan", "arah", dan "alasan" LEBIH DAHULU, baru "dasar" dan "tone", agar tone mengikuti indikator Humas.
Balas HANYA dengan JSON valid tanpa markdown/backticks, format:
{
  "hasil": [
    {
      "id": <id>,
      "hubungan": "K1" | "K2" | "K3" | "K4",
      "arah": "mendukung" | "tidak ada" | "menyerang",
      "alasan": "<satu kalimat: jelaskan hubungan K1-K4, arah terhadap Kemenperin, dan indikator Humasnya>",
      "dasar": "judul" | "isi",
      "tone": "Positif" | "Netral" | "Negatif"
    }
  ]
}"""

TONE_SYSTEM_PROMPT = f"{TONE_RULES}\n\n{TONE_ARTICLE_FORMAT}"

GROUP_TONE_SUFFIX = """Kamu menerima beberapa ISU. Tiap isu berisi kumpulan berita yang meliput hal yang sama, dengan "sumber_isu" berisi "rilis" (nama isu adalah judul rilis resmi Kemenperin, sehingga peristiwanya adalah K1 rilis Kemenperin) atau "klaster". Beri SATU tone untuk seluruh isu memakai indikator Humas dan kerangka dua langkah di atas. Nilai dari peran Kemenperin dalam PERISTIWA isu itu, bukan dari tiap judul terpisah. Jika peristiwanya merupakan kegiatan, rilis resmi, atau pernyataan Kemenperin (K1), seluruh anggota isu mengikuti tone peristiwa (K1) walaupun sebagian judul tidak menyebut Kemenperin. Tandai pada "outlier_ids" berita yang jelas bukan bagian peristiwa ini atau yang arah dan pelakunya berlawanan dengan mayoritas. Jangan menandai berita hanya karena sudut judulnya sedikit berbeda.
Isi "hubungan", "arah", dan "alasan" LEBIH DAHULU, baru "tone". Balas HANYA JSON valid tanpa markdown:
{"hasil":[{"kelompok_id":<id>,"hubungan":"K1"|"K2"|"K3"|"K4","arah":"mendukung"|"tidak ada"|"menyerang","alasan":"<satu kalimat>","outlier_ids":[<id>],"keyakinan":"tinggi"|"sedang"|"rendah","tone":"Positif"|"Netral"|"Negatif"}]}"""

GROUP_TONE_PROMPT = f"{TONE_RULES}\n\n{GROUP_TONE_SUFFIX}"

GABUNGAN_ISU_TONE_SUFFIX = """Kamu menerima beberapa kelompok berita, tiap kelompok dianggap membahas satu isu yang sama. Untuk tiap kelompok kerjakan tiga hal berurutan. Pertama, tulis satu nama isu berupa satu kalimat bergaya judul berita yang memuat pelaku utama dan tindakan utamanya, hanya dari informasi di judul dan cuplikan, tanpa menambah fakta. Kedua, tandai pada "outlier_ids" berita yang jelas bukan bagian isu kelompok itu atau yang arah dan pelakunya berlawanan dengan mayoritas, tetapi jangan menandai berita hanya karena sudut judulnya sedikit berbeda. Ketiga, beri SATU tone untuk seluruh kelompok memakai indikator Humas dan kerangka dua langkah di atas, dinilai dari peran dan sikap terhadap Kemenperin dalam PERISTIWA utama isu, bukan dari satu judul yang kebetulan paling ekstrem. Jika peristiwanya kegiatan atau pernyataan Kemenperin (K1), seluruh anggota kelompok mengikuti tone K1 meski sebagian judul tidak menyebut Kemenperin.
Isi "isu", "hubungan", "arah", dan "alasan" LEBIH DAHULU, baru "tone". Balas HANYA JSON valid tanpa markdown:
{"hasil":[{"kelompok_id":<id>,"isu":"...","hubungan":"K1"|"K2"|"K3"|"K4","arah":"mendukung"|"tidak ada"|"menyerang","alasan":"<satu kalimat>","outlier_ids":[<id>],"keyakinan":"tinggi"|"sedang"|"rendah","tone":"Positif"|"Netral"|"Negatif"}]}"""

GABUNGAN_ISU_TONE_PROMPT = f"{TONE_RULES}\n\n{GABUNGAN_ISU_TONE_SUFFIX}"


def _get_gemini_model(force_next: bool = False):
    """Kompatibilitas wrapper yang mendelegasikan rotasi model ke shared GeminiModelPool."""
    global gemini_quota_exhausted
    model, _name = _MODEL_POOL.get_model(force_next=force_next, mark_exhausted=force_next)
    gemini_quota_exhausted = _MODEL_POOL.quota_exhausted
    return model


# =========================================================================
# LEKSIKON KEMENPERIN & FALLBACK RULE-BASED DUA LANGKAH (BIRO HUMAS)
# =========================================================================

NEGATION_WORDS = ["tidak", "tak", "bukan", "belum", "tanpa", "nihil", "bebas dari", "batal"]

CONTRAST_WORDS = ["tapi", "tetapi", "namun", "meski", "meskipun", "walau", "walaupun", "sayangnya"]

# Sinyal lama yang dipertahankan sebagai detektor latar kondisi/kata negatif (bukan pemicu tone sendirian)
RESPONSE_CUES = [
    "siapkan", "menyiapkan", "strategi", "antisipasi", "mengantisipasi", "hadapi", "menghadapi",
    "upaya", "langkah", "solusi", "minta", "meminta", "usul", "usulkan", "imbau", "tunda", "menunda",
    "kaji", "mengkaji", "siasati", "atasi", "mengatasi", "cegah", "mencegah", "perkuat", "memperkuat",
    "tanggapi", "menanggapi", "rumuskan", "lindungi", "melindungi", "jaga", "menjaga",
]

ACHIEVEMENT_RE = re.compile(
    r"\b(ekspor|investasi|surplus|produksi|penjualan|realisasi)\b.*\b(capai|mencapai|tembus|catat|mencatat|raih|meraih)\b"
)

HARD_HARM_PHRASES = [
    "pemutusan hubungan kerja", "tutup pabrik", "menutup pabrik", "gulung tikar",
    "bangkrut", "pailit", "terpuruk", "harga anjlok", "terjun bebas",
    "rumahkan karyawan", "merumahkan karyawan", "ekspor turun", "kurangi produksi", "pangkas produksi",
]

NEGATIVE_WORD_CUES = [
    "turun", "melemah", "pelemahan", "anjlok", "tertekan", "lesu", "ilegal",
    "larangan", "pelarangan", "marak", "phk", "rugi", "kerugian", "bangkrut", "pailit",
]

# Isyarat serangan dan pelanggaran hukum/moral (hanya dihitung bila ada penyebutan/kaitan ke Kemenperin)
ATTACK_CUES = [
    "kritik", "mengkritik", "dikritik", "kritikan", "kecam", "mengecam", "dikecam", "kecaman",
    "sorot", "soroti", "disorot", "gugat", "digugat", "menggugat", "gugatan",
    "salahkan", "menyalahkan", "disalahkan", "dinilai gagal", "kegagalan", "gagal mengawasi",
    "tidak efektif", "tak efektif", "tak lagi efektif", "kurang efektif", "lamban", "kelalaian", "lalai",
    "kecolongan", "maladministrasi", "mematikan usaha", "menghambat industri", "menghambat investasi",
    "membebani pabrik", "membebani industri", "merugikan pabrik", "merugikan industri",
    "tolak kebijakan", "menolak aturan", "menolak regulasi", "protes kebijakan", "desak cabut",
]

CORRUPTION_HARM_CUES = [
    "korupsi", "suap", "menyuap", "disuap", "gratifikasi", "pungli", "pungutan liar",
    "pemerasan", "dugaan penyimpangan", "penyimpangan anggaran", "penyelewengan",
    "tersangka", "operasi tangkap tangan", "penggeledahan", "geledah", "pencucian uang",
    "pelanggaran hukum", "tindak pidana", "asusila", "pelanggaran etik",
]

SELF_OPPOSE_CUES = [
    "akui gagal", "mengakui gagal", "akui kegagalan", "mengakui kegagalan",
    "akui kelalaian", "mengakui kelalaian", "akui lemah", "menyesalkan lemahnya",
    "berseberangan dengan kepentingan", "pangkas pembinaan industri", "hentikan hilirisasi",
    "tidak efektif", "tak efektif",
]

SUPPORT_CUES = [
    "apresiasi", "mengapresiasi", "diapresiasi", "dukung penuh", "dukungan penuh",
    "memuji", "menyambut baik", "sambut baik", "terbukti melindungi",
    "terbukti efektif", "berhasil melindungi", "menguntungkan industri",
    "langkah tepat", "berpihak pada industri", "patut didukung",
]

ANTI_CORRUPTION_SAFE_RE = re.compile(
    r"\b(?:anti[-\s]?korupsi|bebas\s+korupsi|pencegahan\s+korupsi|cegah\s+korupsi|"
    r"pencegahan\s+gratifikasi|zona\s+integritas|wbk|wbbm)\b",
    re.IGNORECASE,
)

SUBORDINATE_KEMENPERIN_RE = re.compile(
    r"\b(?:turut\s+hadir|juga\s+hadir|juga\s+dihadiri|perwakilan\s+kemenperin|"
    r"selain\s+[^\.]{0,50}kemenperin|salah\s+satu(?:nya)?[^\.]{0,30}kemenperin|"
    r"sebagian\s+besar\s+laporan|nama\s+kemenperin\s+(?:ikut\s+|turut\s+)?di)\b",
    re.IGNORECASE,
)

GENERAL_APPEAL_RE = re.compile(
    r"\b(?:minta|meminta|mohon|memohon|harap|berharap|imbau|mengimbau|usul|mengusulkan)\s+[^\.]{0,35}\bpemerintah\b",
    re.IGNORECASE,
)

_KEMENPERIN_LEXICON_CACHE: dict[str, tuple[float, dict]] = {}


def _load_kemenperin_lexicon(path: str | os.PathLike = DEFAULT_KEMENPERIN_ALIAS_PATH) -> dict:
    """Memuat leksikon penyebutan institusi/jabatan/pejabat Kemenperin dari config/alias_kemenperin.json."""
    p = Path(path)
    p_key = str(p)
    default_lex = {
        "institusi_aliases": ["kemenperin", "kementerian perindustrian", "ditjen industri agro", "ditjen agro"],
        "jabatan_aliases": ["menperin", "menteri perindustrian", "wamenperin", "wakil menteri perindustrian",
                            "sekjen kemenperin", "dirjen industri agro", "juru bicara kemenperin"],
        "pejabat_aliases": [],
        "policy_program_keywords": ["tkdn", "hilirisasi", "sni", "industri agro", "pabrik", "manufaktur"],
        "kemenperin_policy_specific_terms": ["tkdn", "hilirisasi", "sni", "kebijakan industri", "aturan industri", "regulasi industri"],
        "other_agency_aliases": ["esdm", "kementan", "kemenkeu", "kkp", "kemendag"],
    }
    if not p.exists():
        return default_lex
    try:
        mtime = p.stat().st_mtime
        cached = _KEMENPERIN_LEXICON_CACHE.get(p_key)
        if cached and cached[0] == mtime:
            return cached[1]
        data = json.loads(p.read_text(encoding="utf-8"))
        for k, v in default_lex.items():
            if not isinstance(data.get(k), list):
                data[k] = v
        _KEMENPERIN_LEXICON_CACHE[p_key] = (mtime, data)
        return data
    except Exception:
        return default_lex


def _has_negation_before(text_lower: str, match_start: int, window_words: int = 3) -> bool:
    """Mengecek apakah kata/frasa didahului negasi dalam jendela 3 kata."""
    prefix = text_lower[:match_start].strip()
    words = prefix.split()
    if not words:
        return False
    preceding_window = " ".join(words[-window_words:])
    for neg in NEGATION_WORDS:
        if re.search(rf"\b{re.escape(neg)}\b", preceding_window):
            return True
    return False


def _find_unnegated_phrases(text: str, phrases: list[str]) -> list[str]:
    """Mencari frasa yang muncul tanpa negasi di depannya."""
    if not text:
        return []
    t_low = text.lower()
    found = []
    for ph in phrases:
        pattern = re.compile(rf"\b{re.escape(ph)}\b", re.IGNORECASE)
        for match in pattern.finditer(t_low):
            if not _has_negation_before(t_low, match.start(), window_words=3):
                found.append(ph)
                break
    return found


def _find_any_phrases(text: str, phrases: list[str]) -> list[str]:
    """Mencari kecocokan word-boundary sederhana tanpa memeriksa negasi."""
    if not text:
        return []
    t_low = text.lower()
    return [ph for ph in phrases if ph and re.search(rf"\b{re.escape(ph.lower())}\b", t_low)]


def _cap_confidence(keyakinan: object, has_body: bool) -> str:
    """Membatasi keyakinan maksimal 'sedang' bila hanya tersedia judul tanpa teks isi."""
    k = str(keyakinan or "sedang").strip().lower()
    if k not in ("tinggi", "sedang", "rendah"):
        k = "sedang"
    if not has_body and k == "tinggi":
        return "sedang"
    return k


def _detect_applied_assumptions(
    hubungan: str,
    arah: str,
    tone: str,
    keyakinan: str,
    title: str,
    text: str = "",
    alasan: str = "",
    is_group_event: bool = False,
    has_non_k1_member: bool = False,
) -> list[str]:
    """Menandai konstanta ASUMSI SEMENTARA yang terpakai pada suatu keputusan agar mudah diaudit Biro Humas."""
    applied: list[str] = []
    combined = f"{title or ''} {text or ''}".strip()
    c_low = combined.lower()
    lex = _load_kemenperin_lexicon()
    k_terms = list(dict.fromkeys(
        lex["institusi_aliases"] + lex["jabatan_aliases"] + lex["pejabat_aliases"]
    ))
    has_kem_in_title = bool(_find_any_phrases(title, k_terms))

    if ASUMSI_K4_NETRAL and hubungan == "K4" and tone == "Netral":
        applied.append("ASUMSI_K4_NETRAL")

    has_harm_or_down = bool(
        _find_unnegated_phrases(combined, HARD_HARM_PHRASES + ["ekspor turun", "anjlok", "melemah", "tertekan"])
        or re.search(r"\b(?:ekspor|produksi|harga|permintaan)[^.]{0,35}\b(?:turun|anjlok|melemah|tertekan)\b", c_low)
    )
    if ASUMSI_A1_KONDISI_INDUSTRI_NETRAL and arah != "menyerang" and tone != "Negatif" and has_harm_or_down:
        applied.append("ASUMSI_A1_KONDISI_INDUSTRI_NETRAL")

    if (
        ASUMSI_A2_DESAKAN_UMUM_PEMERINTAH_NETRAL
        and hubungan in ("K3", "K4")
        and not has_kem_in_title
        and not _find_any_phrases(combined, k_terms)
        and GENERAL_APPEAL_RE.search(c_low)
        and tone == "Netral"
    ):
        applied.append("ASUMSI_A2_DESAKAN_UMUM_PEMERINTAH_NETRAL")

    other_hits = _find_any_phrases(combined, lex["other_agency_aliases"])
    if ASUMSI_A3_KEBIJAKAN_INSTANSI_LAIN_NON_KEMENPERIN and other_hits and hubungan != "K1":
        applied.append("ASUMSI_A3_KEBIJAKAN_INSTANSI_LAIN_NON_KEMENPERIN")

    has_neg_word = bool(_find_any_phrases(title, NEGATIVE_WORD_CUES))
    if ASUMSI_A4_KATA_NEGATIF_BUKAN_PEMICU and has_neg_word and tone != "Negatif":
        applied.append("ASUMSI_A4_KATA_NEGATIF_BUKAN_PEMICU")

    if ASUMSI_A5_RAGU_PILIH_NETRAL and tone == "Netral" and (keyakinan == "rendah" or "ragu" in (alasan or "").lower()):
        applied.append("ASUMSI_A5_RAGU_PILIH_NETRAL")

    if TONE_ISU_MENGIKUTI_PERISTIWA and is_group_event and has_non_k1_member:
        applied.append("TONE_ISU_MENGIKUTI_PERISTIWA")

    return list(dict.fromkeys(applied))


def _classify_tone_fallback_detail(
    title: str,
    text: str = "",
    keyword: str = "",
    sumber_data: str = "",
) -> dict[str, Any]:
    """
    Fallback rule-based dua langkah sesuai Indikator Biro Humas Kemenperin:
    - Langkah 1: deteksi hubungan (K1..K4) memakai config/alias_kemenperin.json + entity/relevance repo.
    - Langkah 2: deteksi arah (mendukung/tidak ada/menyerang) hanya bila ada kaitan Kemenperin.
    - Batas keyakinan maksimal 'sedang' bila teks isi kosong.
    """
    t_clean = (title or "").strip()
    b_clean = (text or "").strip()
    combined = f"{t_clean} {b_clean}".strip()
    has_body = bool(b_clean)

    # Abaikan frasa eksplisit peniadaan penyebutan ('tanpa menyinggung Kemenperin') saat deteksi K1/K2
    no_kem_re = re.compile(
        r"\b(?:tanpa\s+(?:menyinggung|melibatkan|menyebut|campur\s+tangan)|"
        r"tidak\s+(?:menyinggung|melibatkan|menyebut)|"
        r"bukan\s+(?:kewenangan|urusan|terkait))\s+(?:kementerian\s+perindustrian|kemenperin)\b",
        re.IGNORECASE,
    )
    t_for_kem = no_kem_re.sub(" ", t_clean)
    b_for_kem = no_kem_re.sub(" ", b_clean)

    lex = _load_kemenperin_lexicon()
    all_kem_terms = list(dict.fromkeys(
        lex["institusi_aliases"] + lex["jabatan_aliases"] + lex["pejabat_aliases"]
    ))

    # Gabungkan deteksi leksikon dengan deteksi pejabat resmi repo (tanpa membuat deteksi kedua yang bertentangan)
    sp_title, sp_body = "", ""
    sig_rel = False
    agro_rel = False
    try:
        from src.entity_mapper import find_spokespersons
        from src.relevance_filter import get_kemenperin_signal, is_agro_relevant_content, EXPLICIT_KEMENPERIN_SIGNALS
        sp_title, _, _ = find_spokespersons(t_for_kem)
        sp_body, _, _ = find_spokespersons(b_for_kem) if b_for_kem.strip() else ("", "", "")
        sig_rel, _, _ = get_kemenperin_signal(t_for_kem, b_for_kem, keyword=keyword, sumber_data=sumber_data)
        agro_rel = is_agro_relevant_content(t_clean, b_clean)
        all_kem_terms = list(dict.fromkeys(all_kem_terms + list(EXPLICIT_KEMENPERIN_SIGNALS)))
    except Exception:
        pass

    k_title_hits = _find_any_phrases(t_for_kem, all_kem_terms)
    k_body_hits = _find_any_phrases(b_for_kem, all_kem_terms)
    k_mentioned = bool(k_title_hits or k_body_hits or sp_title or sp_body or sig_rel)

    other_hits = _find_any_phrases(combined, lex["other_agency_aliases"])
    kem_policy_hits = _find_any_phrases(combined, lex["kemenperin_policy_specific_terms"])
    general_policy_hits = _find_any_phrases(combined, lex["policy_program_keywords"])

    # --- LANGKAH 1: TENTUKAN HUBUNGAN (K1..K4) ---
    if k_mentioned:
        # Bedakan pelaku/narasumber utama (K1) vs pelengkap (K2)
        is_subordinate = bool(SUBORDINATE_KEMENPERIN_RE.search(combined))
        only_late_body_mention = False
        if not k_title_hits and not sp_title and b_clean:
            sents = [s.strip() for s in re.split(r"[.!?]+", b_clean) if s.strip()]
            lead_chunk = " ".join(sents[:2]) if len(sents) >= 3 else ""
            if len(sents) >= 3 and not _find_any_phrases(lead_chunk, all_kem_terms):
                only_late_body_mention = True
        hubungan = "K2" if (is_subordinate or only_late_body_mention) else "K1"
    elif other_hits and not kem_policy_hits:
        # Kebijakan/pemberitaan instansi lain tanpa melibatkan Kemenperin maupun kebijakan spesifik Kemenperin (A3)
        hubungan = "K4"
    elif kem_policy_hits or general_policy_hits or agro_rel or (keyword or "").strip():
        hubungan = "K3"
    else:
        hubungan = "K4"

    # --- LANGKAH 2: TENTUKAN ARAH TERHADAP KEMENPERIN ---
    safe_combined = ANTI_CORRUPTION_SAFE_RE.sub(" komitmen bersih ", combined)
    corrupt_hits = _find_unnegated_phrases(safe_combined, CORRUPTION_HARM_CUES)
    attack_hits = _find_unnegated_phrases(combined, ATTACK_CUES)
    self_oppose_hits = _find_unnegated_phrases(combined, SELF_OPPOSE_CUES)
    support_hits = _find_unnegated_phrases(combined, SUPPORT_CUES)

    # Filter: jika Kemenperin mengkritik praktik ilegal pihak lain (bukan menyudutkan Kemenperin)
    kem_attacks_external = bool(re.search(
        r"\b(?:kemenperin|menperin|wamenperin|dirjen|sekjen|jubir|juru\s+bicara)[^\.]{0,35}"
        r"\b(?:kritik|mengkritik|sorot|menyoroti|kecam|mengecam)\b[^\.]{0,45}"
        r"\b(?:ilegal|penyelundup|oknum|impor\s+ilegal|kartel|penimbun|pelanggar)",
        combined,
        re.IGNORECASE,
    ))
    passive_or_targeted_attack = bool(re.search(
        r"\b(?:dikritik|dikecam|disorot|digugat|disalahkan|kelalaian|lamban|tidak\s+efektif|tak\s+efektif)\b"
        r"|(?:kritik|mengkritik|gugat|menggugat|salahkan|menyalahkan|kecam|mengecam)[^\.]{0,55}"
        r"\b(?:kemenperin|menperin|kebijakan|aturan|regulasi)\b",
        combined,
        re.IGNORECASE,
    ))

    dasar = "isi" if (has_body and not k_title_hits) else "judul"
    keyakinan = "sedang" if not has_body else "tinggi"

    if hubungan == "K4":
        arah = "tidak ada"
        tone = "Netral" if ASUMSI_K4_NETRAL else "Netral"
        alasan = "Tidak terdapat penyebutan Kemenperin atau keterkaitan kebijakan Kemenperin (K4, asumsi sementara Netral)."
        keyakinan = _cap_confidence("sedang" if other_hits else keyakinan, has_body)
    elif hubungan in ("K1", "K2"):
        if corrupt_hits:
            arah = "menyerang"
            tone = "Negatif"
            dasar = "isi" if has_body and not _find_unnegated_phrases(ANTI_CORRUPTION_SAFE_RE.sub(" ", t_clean), CORRUPTION_HARM_CUES) else "judul"
            alasan = f"Isu pelanggaran hukum/korupsi melibatkan Kemenperin ({corrupt_hits[0]}, indikator N2)."
        elif hubungan == "K1" and self_oppose_hits:
            arah = "menyerang"
            tone = "Negatif"
            dasar = "isi" if has_body and not _find_unnegated_phrases(t_clean, SELF_OPPOSE_CUES) else "judul"
            alasan = f"Pernyataan pejabat/institusi Kemenperin berseberangan atau mengakui kegagalan ({self_oppose_hits[0]}, indikator N3)."
        elif attack_hits and (passive_or_targeted_attack or hubungan == "K2") and not kem_attacks_external:
            arah = "menyerang"
            tone = "Negatif"
            dasar = "isi" if has_body and not _find_unnegated_phrases(t_clean, ATTACK_CUES) else "judul"
            alasan = f"Pemberitaan mengkritik/menyudutkan Kemenperin atau kebijakannya ({attack_hits[0]}, indikator N1)."
        elif hubungan == "K1":
            arah = "mendukung"
            tone = "Positif"
            dasar = "isi" if has_body and not k_title_hits else "judul"
            alasan = "Kemenperin atau pejabatnya menjadi pelaku/narasumber utama tanpa serangan (indikator P1)."
        else:
            arah = "tidak ada"
            tone = "Netral"
            dasar = "isi" if has_body and not k_title_hits else "judul"
            alasan = "Kemenperin disebut hanya sebagai pelengkap tanpa serangan atau isu pelanggaran (indikator Ne1)."
    else:
        # K3: Tidak menyebut Kemenperin secara langsung, tetapi terkait kebijakan/kepentingan industri agro
        is_general_appeal = bool(GENERAL_APPEAL_RE.search(combined)) and not attack_hits
        if other_hits and not kem_policy_hits:
            arah = "tidak ada"
            tone = "Netral"
            alasan = "Isu berfokus pada kebijakan instansi lain tanpa melibatkan Kemenperin (A3, Netral)."
        elif attack_hits and kem_policy_hits and not is_general_appeal:
            arah = "menyerang"
            tone = "Negatif"
            dasar = "isi" if has_body and not _find_unnegated_phrases(t_clean, ATTACK_CUES) else "judul"
            alasan = f"Pihak lain menyerang kebijakan terkait Kemenperin ({attack_hits[0]} pada {kem_policy_hits[0]}, indikator N4)."
        elif support_hits and kem_policy_hits and not attack_hits:
            arah = "mendukung"
            tone = "Positif"
            dasar = "isi" if has_body and not _find_unnegated_phrases(t_clean, SUPPORT_CUES) else "judul"
            alasan = f"Pihak lain mendukung kebijakan terkait Kemenperin ({support_hits[0]} pada {kem_policy_hits[0]}, indikator P2)."
        else:
            arah = "tidak ada"
            tone = "Netral"
            if is_general_appeal:
                alasan = "Permintaan umum kepada pemerintah tanpa menyebut/menyerang Kemenperin (indikator Ne2 + A2)."
            elif _find_unnegated_phrases(combined, HARD_HARM_PHRASES):
                alasan = "Kondisi industri melemah tanpa serangan atau sorotan buruk ke Kemenperin (indikator Ne2 + A1)."
            else:
                alasan = "Topik terkait sektor/program kerja Kemenperin tanpa dukungan atau serangan jelas (indikator Ne2)."

    final_keyak = _cap_confidence(keyakinan, has_body)
    asumsi = _detect_applied_assumptions(
        hubungan=hubungan,
        arah=arah,
        tone=tone,
        keyakinan=final_keyak,
        title=t_clean,
        text=b_clean,
        alasan=alasan,
    )
    return {
        "tone": tone,
        "dasar": dasar,
        "alasan": alasan,
        "hubungan": hubungan,
        "arah": arah,
        "keyakinan": final_keyak,
        "asumsi_sementara": asumsi,
    }


def classify_tone_fallback(title: str, text: str = "") -> tuple[str, str, str]:
    """
    Wrapper kompatibel 3-tuple (tone, dasar, alasan) di atas fallback rule-based dua langkah Biro Humas.
    """
    det = _classify_tone_fallback_detail(title=title, text=text)
    return det["tone"], det["dasar"], det["alasan"]


# =========================================================================
# PENILAI UTAMA GEMINI API DENGAN BATCH 5 ARTIKEL
# =========================================================================

def _log_tone_decision(
    title: str,
    tone: str,
    dasar: str,
    alasan: str,
    metode: str,
    isu_id: str = "",
    sumber_isu: str = "",
    keyakinan: str = "",
    hubungan: str = "",
    arah: str = "",
    asumsi_sementara: list[str] | None = None,
):
    """Mencatat keputusan tone ke hasil_scrapping/log_tone.jsonl."""
    os.makedirs(os.path.dirname(LOG_TONE_FILE), exist_ok=True)
    entry: dict[str, Any] = {
        "title": title,
        "tone": tone,
        "hubungan": hubungan,
        "arah": arah,
        "dasar": dasar,
        "alasan": alasan,
        "metode": metode,
        "isu_id": isu_id,
        "sumber_isu": sumber_isu,
        "keyakinan": keyakinan,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    if asumsi_sementara:
        entry["asumsi_sementara"] = asumsi_sementara
    with open(LOG_TONE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def classify_tone_batch(articles: list[dict], use_ai: bool = True, ensure_consistency: bool = True) -> list[dict]:
    """
    Mengklasifikasikan tone sekumpulan artikel:
    - Input: list of dict {'id': ..., 'title': ..., 'text': ...}
    - Jika ensure_consistency=True: mengelompokkan judul mirip (rapidfuzz >= 90) agar bertone SAMA.
    - Batch kecil: 5 artikel per pemanggilan Gemini API.
    - Output: list of dict {'id': ..., 'tone': ..., 'dasar': ..., 'alasan': ..., 'fokus': ..., 'metode': 'AI'|'fallback'}
    """
    if not articles:
        return []

    if ensure_consistency:
        return classify_tone_consistent(articles, use_ai=use_ai, threshold=90.0)

    results = []
    batch_size = 5

    for i in range(0, len(articles), batch_size):
        chunk = articles[i:i + batch_size]
        chunk_results = _process_one_chunk(chunk, use_ai=use_ai)
        results.extend(chunk_results)

        # Jeda 2-3 detik antar batch jika memakai AI
        if use_ai and not gemini_quota_exhausted and i + batch_size < len(articles):
            time.sleep(2.5)

    return results


def classify_tone_consistent(articles: list[dict], use_ai: bool = True, threshold: float = 90.0) -> list[dict]:
    """
    Mengelompokkan judul identik atau mirip (rapidfuzz >= 90) menjadi satu grup:
    - Nilai SATU KALI per grup memakai artikel dengan teks paling lengkap (len(text) terpanjang).
    - Terapkan hasil perwakilan ke seluruh baris di grup itu.
    - Baris tetap dipertahankan semua (tanpa deduplikasi baris untuk media monitoring).
    - Log seluruh baris ke hasil_scrapping/log_tone.jsonl.
    """
    if not articles:
        return []

    from rapidfuzz import fuzz

    # 1. Kelompokkan artikel berdasarkan kemiripan judul
    groups = []  # list of list of articles
    for art in articles:
        t_raw = str(art.get("title", "")).strip()
        t_clean = re.sub(r"\s*[-–—|]\s*[^–—|-]+$", "", t_raw).strip().lower()
        if not t_clean:
            t_clean = t_raw.lower()

        matched_group = None
        for grp in groups:
            rep_raw = str(grp[0].get("title", "")).strip()
            rep_clean = re.sub(r"\s*[-–—|]\s*[^–—|-]+$", "", rep_raw).strip().lower()
            if not rep_clean:
                rep_clean = rep_raw.lower()

            score_ratio = fuzz.ratio(t_clean, rep_clean)
            score_token = fuzz.token_set_ratio(t_clean, rep_clean)

            if score_ratio >= threshold or score_token >= threshold:
                matched_group = grp
                break

        if matched_group is not None:
            matched_group.append(art)
        else:
            groups.append([art])

    # 2. Pilih artikel dengan teks paling lengkap per grup
    rep_articles = []
    for g_idx, grp in enumerate(groups, start=1):
        best_art = max(grp, key=lambda a: len(str(a.get("text", "")).strip()))
        rep_payload = dict(best_art)
        rep_payload["id"] = g_idx
        rep_articles.append(rep_payload)

    print(f"[TONE CONSISTENCY] Ditemukan {len(groups)} grup judul unik dari {len(articles)} baris artikel.", flush=True)

    # 3. Jalankan penilaian tone batch pada perwakilan grup
    rep_results = classify_tone_batch(rep_articles, use_ai=use_ai, ensure_consistency=False)
    rep_map = {r["id"]: r for r in rep_results}

    # 4. Terapkan hasil ke semua artikel dalam grup dan catat ke log
    orig_results_map = {}
    for g_idx, grp in enumerate(groups, start=1):
        g_res = rep_map.get(g_idx) or {
            "tone": "Netral",
            "hubungan": "K3",
            "arah": "tidak ada",
            "dasar": "judul",
            "alasan": "Informasi umum tanpa masalah atau prestasi terhadap Kemenperin",
            "keyakinan": "sedang",
            "asumsi_sementara": [],
            "metode": "fallback"
        }
        for art in grp:
            art_id = art.get("id")
            art_title = str(art.get("title", "")).strip()
            has_art_body = bool(str(art.get("text") or art.get("isi") or "").strip())
            art_keyak = _cap_confidence(g_res.get("keyakinan") or "sedang", has_art_body)
            art_res = {
                "id": art_id,
                "title": art_title,
                "tone": g_res["tone"],
                "hubungan": g_res.get("hubungan", ""),
                "arah": g_res.get("arah", ""),
                "dasar": g_res["dasar"],
                "alasan": g_res["alasan"],
                "keyakinan": art_keyak,
                "asumsi_sementara": list(g_res.get("asumsi_sementara") or []),
                "metode": g_res["metode"],
                "group_id": g_idx,
                "group_size": len(grp)
            }
            orig_results_map[art_id] = art_res

            # Catat artikel turunan grup ke log_tone.jsonl jika belum dicatat oleh chunk perwakilan
            if art is not grp[0]:
                _log_tone_decision(
                    title=art_title,
                    tone=g_res["tone"],
                    dasar=g_res["dasar"],
                    alasan=g_res["alasan"],
                    metode=g_res["metode"],
                    isu_id=str(art.get("isu_id") or ""),
                    sumber_isu=str(art.get("sumber_isu") or ""),
                    keyakinan=art_keyak,
                    hubungan=g_res.get("hubungan", ""),
                    arah=g_res.get("arah", ""),
                    asumsi_sementara=list(g_res.get("asumsi_sementara") or []),
                )

    return [orig_results_map.get(a.get("id"), {}) for a in articles]


def _normalize_hubungan(val, default: str = "K3") -> str:
    h = str(val or "").strip().upper()
    return h if h in ("K1", "K2", "K3", "K4") else default


def _normalize_arah(val, default: str = "tidak ada") -> str:
    a = str(val or "").strip().lower()
    if a in ("mendukung", "tidak ada", "menyerang"):
        return a
    if a in ("berseberangan", "menyerang/kritik", "kritik"):
        return "menyerang"
    return default


def _extract_json_objects_fallback(resp_text: str, fields: tuple[str, ...]) -> tuple[list[dict], bool]:
    """Ekstraktor JSON toleran markdown dengan parser penyelamat independen urutan field."""
    clean_json = re.sub(r"^```(?:json)?\s*", "", resp_text, flags=re.MULTILINE)
    clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE).strip()
    m = re.search(r"\{[\s\S]*\}", clean_json)
    if m:
        clean_json = m.group(0)

    try:
        data = json.loads(clean_json, strict=False)
        res = data.get("hasil", [])
        if isinstance(res, list) and res:
            return [x for x in res if isinstance(x, dict)], True
    except Exception:
        pass

    parsed_list: list[dict] = []
    for obj in re.findall(r"\{[^{}]*\}", clean_json, re.DOTALL):
        def _field(name, obj=obj):
            mm = re.search(
                rf'"{name}"\s*:\s*("(?:[^"\\]|\\.)*"|\[[^\]]*\]|[^,}}\s]+)',
                obj,
                re.DOTALL,
            )
            if not mm:
                return None
            try:
                return json.loads(mm.group(1))
            except Exception:
                return mm.group(1).strip().strip('"')

        rec = {f: _field(f) for f in fields}
        parsed_list.append(rec)
    return parsed_list, False


def _process_one_chunk(chunk: list[dict], use_ai: bool = True) -> list[dict]:
    """Memproses 1 batch (maksimal 5 artikel) dengan DecisionCache, temperature=0, dan fallback jika gagal."""
    global gemini_quota_exhausted, TOTAL_API_CALLS

    dcache = get_decision_cache()
    active_model = _MODEL_POOL.peek_active_model_name()
    resolved_by_id = {}
    uncached_chunk = []

    for a in chunk:
        a_url = str(a.get("resolved_url") or a.get("link") or a.get("Link Website") or "").strip()
        cached = dcache.get(a_url, "tone", TONE_PROMPT_VERSION, active_model) if a_url else None
        if cached is not None:
            entry = dict(cached)
            entry["id"] = a["id"]
            resolved_by_id[a["id"]] = entry
        else:
            uncached_chunk.append(a)

    # Siapkan payload hanya untuk yang belum tersimpan di DecisionCache
    formatted_items = []
    for a in uncached_chunk:
        item_text = str(a.get("text") or a.get("isi") or "").strip()[:3000]
        formatted_items.append({
            "id": a["id"],
            "title": str(a.get("title") or a.get("Title") or "").strip(),
            "text": item_text
        })

    if formatted_items and use_ai and not gemini_quota_exhausted:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            payload_str = json.dumps(formatted_items, ensure_ascii=False, indent=2)
            user_msg = f"Berikut daftar artikel untuk dinilai tonenya (total: {len(formatted_items)}):\n{payload_str}"
            full_prompt = f"{TONE_SYSTEM_PROMPT}\n\n{user_msg}"

            TOTAL_API_CALLS += 1
            resp_text, used_model, _err = _MODEL_POOL.generate_deterministic(
                full_prompt,
                timeout=60,
                max_attempts=6,
            )
            gemini_quota_exhausted = _MODEL_POOL.quota_exhausted

            if resp_text:
                hasil_list, _ = _extract_json_objects_fallback(
                    resp_text,
                    ("id", "hubungan", "arah", "alasan", "dasar", "keyakinan", "tone"),
                )
                by_uncached_id = {u["id"]: u for u in uncached_chunk}
                for h in hasil_list:
                    h_id = h.get("id")
                    t_raw = str(h.get("tone") or "").strip().capitalize()
                    if h_id is None or t_raw not in ("Positif", "Netral", "Negatif"):
                        # Hasil Gemini tidak valid -> biarkan ID tidak terisi agar jatuh ke fallback
                        continue
                    d_val = str(h.get("dasar") or "judul").strip().lower()
                    if d_val not in ("judul", "isi"):
                        d_val = "judul"
                    alasan_val = str(h.get("alasan") or "").strip()

                    src_art = by_uncached_id.get(h_id) or by_uncached_id.get(str(h_id))
                    if not src_art:
                        try:
                            src_art = by_uncached_id.get(int(h_id))
                        except (ValueError, TypeError):
                            src_art = None
                    src_title = str((src_art or {}).get("title") or (src_art or {}).get("Title") or "")
                    src_text = str((src_art or {}).get("text") or (src_art or {}).get("isi") or "")
                    has_src_body = bool(src_text.strip())

                    hub_val = _normalize_hubungan(h.get("hubungan"), default="K3")
                    arah_val = _normalize_arah(h.get("arah"), default="tidak ada")
                    keyak_val = _cap_confidence(h.get("keyakinan") or ("tinggi" if has_src_body else "sedang"), has_src_body)
                    asumsi_val = _detect_applied_assumptions(
                        hubungan=hub_val,
                        arah=arah_val,
                        tone=t_raw,
                        keyakinan=keyak_val,
                        title=src_title,
                        text=src_text,
                        alasan=alasan_val,
                    )

                    res_obj = {
                        "id": h_id,
                        "hubungan": hub_val,
                        "arah": arah_val,
                        "alasan": alasan_val,
                        "dasar": d_val,
                        "keyakinan": keyak_val,
                        "asumsi_sementara": asumsi_val,
                        "tone": t_raw,
                        "metode": "AI",
                    }
                    resolved_by_id[h_id] = res_obj
                    try:
                        resolved_by_id[int(h_id)] = res_obj
                    except (ValueError, TypeError):
                        pass
                    resolved_by_id[str(h_id)] = res_obj

                    if src_art:
                        s_url = str(src_art.get("resolved_url") or src_art.get("link") or src_art.get("Link Website") or "").strip()
                        if s_url:
                            dcache.set(s_url, "tone", TONE_PROMPT_VERSION, used_model or active_model, res_obj)
                dcache.save()

    # Cek ID yang hilang atau jika AI tidak dipakai / gagal
    final_chunk_results = []
    for a in chunk:
        a_id = a["id"]
        t_str = str(a.get("title") or a.get("Title") or "").strip()
        txt_str = str(a.get("text") or a.get("isi") or "").strip()
        has_body = bool(txt_str)

        if a_id in resolved_by_id:
            res = dict(resolved_by_id[a_id])
            res["keyakinan"] = _cap_confidence(res.get("keyakinan") or ("tinggi" if has_body else "sedang"), has_body)
        else:
            det = _classify_tone_fallback_detail(
                t_str,
                txt_str,
                keyword=str(a.get("keyword") or a.get("Keywords") or ""),
                sumber_data=str(a.get("sumber_data") or a.get("Sumber Data") or ""),
            )
            res = {
                "id": a_id,
                "hubungan": det["hubungan"],
                "arah": det["arah"],
                "alasan": det["alasan"],
                "dasar": det["dasar"],
                "keyakinan": det["keyakinan"],
                "asumsi_sementara": det["asumsi_sementara"],
                "tone": det["tone"],
                "metode": "fallback",
            }

        # Enforce dasar honesty: jika dasar == 'judul', alasan hanya boleh memakai informasi di judul
        if res.get("dasar") == "judul" and txt_str:
            t_words = set(re.findall(r"\w+", t_str.lower()))
            alasan_text = str(res.get("alasan") or "").lower()
            reason_words = re.findall(r"\w+", alasan_text)
            body_terms = ["b50", "el", "nino", "elnino"]
            if any(bt in reason_words and bt not in t_words for bt in body_terms):
                res["dasar"] = "isi"

        _log_tone_decision(
            t_str,
            str(res.get("tone") or "Netral"),
            str(res.get("dasar") or "judul"),
            str(res.get("alasan") or ""),
            str(res.get("metode") or "fallback"),
            isu_id=str(a.get("isu_id") or ""),
            sumber_isu=str(a.get("sumber_isu") or ""),
            keyakinan=str(res.get("keyakinan") or "sedang"),
            hubungan=str(res.get("hubungan") or ""),
            arah=str(res.get("arah") or ""),
            asumsi_sementara=list(res.get("asumsi_sementara") or []),
        )
        final_chunk_results.append(res)

    return final_chunk_results


def classify_tone(text: str = "", title: str = "") -> str:
    """
    Fungsi drop-in backward-compatible untuk pipeline scraping real-time:
    Mengevaluasi tone satu artikel dengan fallback konservatif.
    """
    tone, _, _ = classify_tone_fallback(title, text)
    return tone


# =========================================================================
# FASE 2: PENILAIAN TONE SATU KALI PER ISU & KONSISTENSI ANTAR HARI
# =========================================================================

def _select_diverse_members(members: list[dict], max_n: int = 8) -> tuple[list[dict], list[str]]:
    """
    Memilih maksimal max_n judul paling beragam secara deterministik (farthest-first traversal)
    serta maksimal 2 cuplikan teks pembuka 400 karakter bila tersedia.
    """
    from rapidfuzz import fuzz

    if not members:
        return [], []

    # Urutkan secara deterministik lebih dulu
    ordered = sorted(
        members,
        key=lambda m: (
            str(m.get("title") or m.get("Title") or "").strip().lower(),
            str(m.get("id") or ""),
        ),
    )

    selected: list[dict] = []
    seen_titles: set[str] = set()
    candidates: list[dict] = []
    for m in ordered:
        t = str(m.get("title") or m.get("Title") or "").strip()
        tl = t.lower()
        if t and tl not in seen_titles:
            seen_titles.add(tl)
            candidates.append(m)

    if not candidates:
        candidates = list(ordered[:max_n])

    selected.append(candidates[0])
    remaining = candidates[1:]
    while remaining and len(selected) < max_n:
        best_idx = 0
        best_min_dist = -1.0
        for idx, cand in enumerate(remaining):
            ct = str(cand.get("title") or cand.get("Title") or "").strip().lower()
            max_sim = max(
                fuzz.ratio(ct, str(s.get("title") or s.get("Title") or "").strip().lower())
                for s in selected
            )
            dist = 100.0 - max_sim
            if dist > best_min_dist:
                best_min_dist = dist
                best_idx = idx
        selected.append(remaining.pop(best_idx))

    snippets: list[str] = []
    seen_snips: set[str] = set()
    by_text_len = sorted(
        ordered,
        key=lambda m: (-len(str(m.get("text") or m.get("isi") or "").strip()), str(m.get("id") or "")),
    )
    for m in by_text_len:
        txt = str(m.get("text") or m.get("isi") or "").strip()[:400]
        if txt and txt not in seen_snips:
            seen_snips.add(txt)
            snippets.append(txt)
            if len(snippets) >= 2:
                break

    return selected, snippets


def _issue_cache_key_url(members: list[dict], reg_entry: dict | None = None) -> str:
    """Kunci cache isu berbasis hash daftar canonical_url terurut anggota isu."""
    urls: list[str] = []
    for m in members:
        raw_u = str(m.get("resolved_url") or m.get("link") or m.get("Link Website") or "").strip()
        cu = canonical_url(raw_u) if raw_u else ""
        if cu:
            urls.append(cu)
        else:
            t = str(m.get("title") or m.get("Title") or "").strip().lower()
            if t:
                urls.append(f"title:{t}")
    if reg_entry:
        for ma in (reg_entry.get("matched_articles") or []):
            cu = str(ma.get("canonical_url") or "").strip()
            if not cu and ma.get("link"):
                cu = canonical_url(str(ma.get("link")))
            if cu:
                urls.append(cu)
    sorted_unique = sorted(set(urls))
    digest = hashlib.sha256("\n".join(sorted_unique).encode("utf-8")).hexdigest()
    return f"https://isu-cache.local/{digest}"


def _member_signature(m: dict) -> str:
    """Kunci identitas deterministik anggota isu berbasis canonical URL atau judul lowercase."""
    return (
        canonical_url(str(m.get("resolved_url") or m.get("link") or m.get("Link Website") or ""))
        or str(m.get("title") or m.get("Title") or "").strip().lower()
    )


def _isu_text_helpers():
    """Mengambil helper teks dan penamaan isu dari src.isu_grouping tanpa circular import."""
    try:
        from src.isu_grouping import _label_clusters_with_llm, clean_display_title, normalize_isu_text
        return clean_display_title, normalize_isu_text, _label_clusters_with_llm
    except Exception:
        return (lambda s: str(s or "").strip()), (lambda s, *_: str(s or "").strip().lower()), None


def _parse_group_tone_json(resp_text: str) -> list[dict]:
    """Mem-parsing output JSON GROUP_TONE_PROMPT / GABUNGAN_ISU_TONE_PROMPT independen urutan field."""
    raw_items, was_json = _extract_json_objects_fallback(
        resp_text,
        ("kelompok_id", "isu", "hubungan", "arah", "alasan", "outlier_ids", "keyakinan", "tone"),
    )
    if was_json:
        return raw_items

    parsed_list: list[dict] = []
    for rec in raw_items:
        if rec.get("kelompok_id") is None or rec.get("tone") is None:
            continue
        raw_isu = rec.get("isu")
        raw_oids = rec.get("outlier_ids")
        if not isinstance(raw_oids, list):
            raw_oids = []
        parsed_list.append({
            "kelompok_id": rec.get("kelompok_id"),
            "isu": str(raw_isu).strip() if raw_isu is not None else "",
            "hubungan": str(rec.get("hubungan") or "").strip(),
            "arah": str(rec.get("arah") or "").strip(),
            "alasan": str(rec.get("alasan") or "").strip(),
            "outlier_ids": raw_oids,
            "keyakinan": str(rec.get("keyakinan") or "sedang").strip().lower(),
            "tone": rec.get("tone"),
        })
    return parsed_list


def _run_issue_group_batches(
    groups: list[dict],
    combined: bool,
    dcache,
    active_model: str,
    use_ai: bool,
) -> None:
    """Menilai batch isu multi-berita (maks 4/call) dengan GABUNGAN_ISU_TONE_PROMPT atau GROUP_TONE_PROMPT."""
    global gemini_quota_exhausted, TOTAL_API_CALLS

    if not groups:
        return

    stage = "combined_isu_tone" if combined else "group_tone"
    clean_fn, _, _ = _isu_text_helpers()
    uncached: list[dict] = []
    for g in groups:
        cached = dcache.get(g["cache_url"], stage, TONE_PROMPT_VERSION, active_model) if use_ai else None
        if cached is not None and (not combined or str(cached.get("isu") or "").strip()):
            g["decision"] = dict(cached)
        else:
            uncached.append(g)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not uncached or not use_ai or not api_key or gemini_quota_exhausted:
        return

    prompt_hdr = GABUNGAN_ISU_TONE_PROMPT if combined else GROUP_TONE_PROMPT
    batch_size = 4
    for idx_start in range(0, len(uncached), batch_size):
        batch_g = uncached[idx_start : idx_start + batch_size]
        payload_groups = []
        for k_offset, g in enumerate(batch_g, start=1):
            g["temp_kelompok_id"] = k_offset
            p_item: dict = {"kelompok_id": k_offset}
            if not combined:
                p_item["isu"] = g["isu"]
                p_item["sumber_isu"] = g["sumber_isu"]
            p_item["cuplikan_teks"] = g["snippets"]
            p_item["berita"] = [
                {
                    "id": m["id"],
                    "judul": str(m.get("title") or m.get("Title") or "").strip(),
                }
                for m in g["diverse_members"]
            ]
            payload_groups.append(p_item)

        prompt_str = (
            f"{prompt_hdr}\n\n"
            f"Berikut daftar isu (total: {len(payload_groups)}):\n"
            f"{json.dumps(payload_groups, ensure_ascii=False, indent=2)}"
        )
        TOTAL_API_CALLS += 1
        resp_text, used_model, _err = _MODEL_POOL.generate_deterministic(
            prompt_str,
            timeout=60,
            max_attempts=6,
        )
        gemini_quota_exhausted = _MODEL_POOL.quota_exhausted
        if resp_text:
            hasil_items = _parse_group_tone_json(resp_text)
            by_kid: dict[str, dict] = {
                str(h.get("kelompok_id")): h
                for h in hasil_items
                if isinstance(h, dict) and h.get("kelompok_id") is not None
            }
            for g in batch_g:
                h = by_kid.get(str(g["temp_kelompok_id"]))
                if not h:
                    continue
                raw_tone = str(h.get("tone") or "").strip()
                if not raw_tone:
                    continue
                isu_val = clean_fn(str(h.get("isu") or "").strip()) if combined else ""
                if combined and not isu_val:
                    continue
                t_val = raw_tone.capitalize()
                if t_val not in ("Positif", "Netral", "Negatif"):
                    t_val = "Netral"
                has_body = bool(g["snippets"])
                keyak = _cap_confidence(h.get("keyakinan") or ("tinggi" if has_body else "sedang"), has_body)
                hub_val = _normalize_hubungan(h.get("hubungan"), default="K1" if g["sumber_isu"] == "rilis" else "K3")
                arah_val = _normalize_arah(h.get("arah"), default="tidak ada")
                raw_oids_in = h.get("outlier_ids")
                if not isinstance(raw_oids_in, list):
                    raw_oids_in = []
                id_to_sig = {str(m["id"]): _member_signature(m) for m in g["members"]}
                valid_oids = [str(oid) for oid in raw_oids_in if oid is not None and str(oid) in id_to_sig]
                outlier_sigs = [id_to_sig[oid] for oid in valid_oids]
                dec: dict[str, Any] = {
                    "tone": t_val,
                    "hubungan": hub_val,
                    "arah": arah_val,
                    "alasan": str(h.get("alasan") or "").strip(),
                    "outlier_ids": valid_oids,
                    "outlier_sigs": outlier_sigs,
                    "keyakinan": keyak,
                    "metode": "AI-isu",
                    "from_combined": combined,
                }
                if combined:
                    dec["isu"] = isu_val
                g["decision"] = dec
                dcache.set(g["cache_url"], stage, TONE_PROMPT_VERSION, used_model or active_model, dec)
        if not gemini_quota_exhausted and idx_start + batch_size < len(uncached):
            time.sleep(2.5)
    dcache.save()


def _majority_fallback_detail(members: list[dict], sumber_isu: str = "klaster") -> dict[str, Any]:
    """
    Menilai anggota dengan fallback rule-based dua langkah lalu menggabungkan ke level peristiwa isu.
    Jika TONE_ISU_MENGIKUTI_PERISTIWA aktif dan peristiwa mengandung peran K1 tanpa serangan,
    seluruh anggota mengikuti tone peristiwa K1 (Positif). Kondisi seri jatuh ke Netral.
    """
    if not members:
        return {
            "tone": "Netral",
            "hubungan": "K4",
            "arah": "tidak ada",
            "keyakinan": "rendah",
            "alasan": "Mayoritas fallback: tidak ada anggota valid",
            "asumsi_sementara": ["ASUMSI_A5_RAGU_PILIH_NETRAL"],
        }

    details = [
        _classify_tone_fallback_detail(
            str(m.get("title") or m.get("Title") or "").strip(),
            str(m.get("text") or m.get("isi") or "").strip(),
            keyword=str(m.get("keyword") or m.get("Keywords") or ""),
            sumber_data=str(m.get("sumber_data") or m.get("Sumber Data") or ""),
        )
        for m in members
    ]
    has_any_body = any(bool(str(m.get("text") or m.get("isi") or "").strip()) for m in members)
    has_k1 = (sumber_isu == "rilis") or any(d["hubungan"] == "K1" for d in details)
    has_non_k1 = any(d["hubungan"] != "K1" for d in details)
    has_attack = any(d["arah"] == "menyerang" for d in details)

    # Aturan peristiwa K1: bila isu berasal dari aktivitas/rilis/pernyataan Kemenperin tanpa serangan
    if TONE_ISU_MENGIKUTI_PERISTIWA and has_k1 and not has_attack:
        keyak = _cap_confidence("sedang" if has_non_k1 else "tinggi", has_any_body)
        asumsi = list({a for d in details for a in d.get("asumsi_sementara", [])})
        if has_non_k1:
            asumsi.append("TONE_ISU_MENGIKUTI_PERISTIWA")
        return {
            "tone": "Positif",
            "hubungan": "K1",
            "arah": "mendukung",
            "keyakinan": keyak,
            "alasan": "Peristiwa isu berpusat pada aktivitas/pernyataan Kemenperin tanpa serangan (indikator P1 peristiwa).",
            "asumsi_sementara": list(dict.fromkeys(asumsi)),
        }

    votes: Counter[str] = Counter(d["tone"] for d in details)
    max_count = max(votes.values())
    winners = [tone for tone, cnt in votes.items() if cnt == max_count]
    summary_str = ", ".join(f"{k}={v}" for k, v in sorted(votes.items()))
    merged_asumsi = list(dict.fromkeys(a for d in details for a in d.get("asumsi_sementara", [])))
    if len(winners) > 1:
        if "ASUMSI_A5_RAGU_PILIH_NETRAL" not in merged_asumsi:
            merged_asumsi.append("ASUMSI_A5_RAGU_PILIH_NETRAL")
        return {
            "tone": "Netral",
            "hubungan": "K1" if has_k1 else ("K3" if any(d["hubungan"] == "K3" for d in details) else details[0]["hubungan"]),
            "arah": "tidak ada",
            "keyakinan": "rendah",
            "alasan": f"Suara seri fallback antar anggota ({summary_str}), jatuh ke Netral",
            "asumsi_sementara": merged_asumsi,
        }

    winner = winners[0]
    win_details = [d for d in details if d["tone"] == winner]
    dom_hub = "K1" if (TONE_ISU_MENGIKUTI_PERISTIWA and has_k1) else Counter(d["hubungan"] for d in win_details).most_common(1)[0][0]
    dom_arah = Counter(d["arah"] for d in win_details).most_common(1)[0][0]
    keyakinan = _cap_confidence("tinggi" if len(votes) == 1 else "sedang", has_any_body)
    if TONE_ISU_MENGIKUTI_PERISTIWA and has_k1 and has_non_k1 and "TONE_ISU_MENGIKUTI_PERISTIWA" not in merged_asumsi:
        merged_asumsi.append("TONE_ISU_MENGIKUTI_PERISTIWA")
    return {
        "tone": winner,
        "hubungan": dom_hub,
        "arah": dom_arah,
        "keyakinan": keyakinan,
        "alasan": f"Suara terbanyak fallback peristiwa isu ({summary_str})",
        "asumsi_sementara": merged_asumsi,
    }


def _majority_fallback_vote(members: list[dict], sumber_isu: str = "klaster") -> tuple[str, str, str]:
    """
    Menilai tiap anggota dengan fallback rule-based lalu mengambil suara peristiwa terbanyak.
    Seri (draw) jatuh ke Netral. Mengembalikan (tone_final, keyakinan, alasan).
    """
    d = _majority_fallback_detail(members, sumber_isu=sumber_isu)
    return d["tone"], d["keyakinan"], d["alasan"]


def build_mixed_tone_report(
    articles: list[dict],
    old_tones_map: dict,
    final_results_map: dict,
) -> list[dict]:
    """
    Menyusun laporan isu yang anggotanya memperoleh lebih dari satu tone pada alur per artikel lama
    ('berita kembar beda tone') untuk ditinjau manusia.
    """
    groups: dict[str, list[dict]] = {}
    for a in articles:
        iid = str(a.get("isu_id") or "")
        if not iid:
            continue
        groups.setdefault(iid, []).append(a)

    mixed_issues: list[dict] = []
    for iid, members in groups.items():
        if len(members) < 2:
            continue
        old_tones = [str(old_tones_map.get(a.get("id")) or "Netral") for a in members]
        if len(set(old_tones)) <= 1:
            continue
        final_tones = [str((final_results_map.get(a.get("id")) or {}).get("tone") or "Netral") for a in members]
        isu_name = str(members[0].get("isu") or members[0].get("Isu") or "")
        sumber_isu = str(members[0].get("sumber_isu") or "klaster")
        mixed_issues.append({
            "isu_id": iid,
            "isu": isu_name,
            "sumber_isu": sumber_isu,
            "tone_isu_final": final_tones[0] if len(set(final_tones)) == 1 else str(Counter(final_tones).most_common(1)[0][0]),
            "tone_lama_dist": dict(Counter(old_tones)),
            "anggota": [
                {
                    "id": m.get("id"),
                    "title": str(m.get("title") or m.get("Title") or "").strip(),
                    "media_name": str(m.get("media_name") or m.get("Media Name") or ""),
                    "tone_lama": str(old_tones_map.get(m.get("id")) or "Netral"),
                    "tone_baru": str((final_results_map.get(m.get("id")) or {}).get("tone") or "Netral"),
                }
                for m in members
            ],
        })
    return mixed_issues


def print_mixed_tone_report(mixed_issues: list[dict]) -> None:
    print("\n" + "=" * 75, flush=True)
    print(f"=== LAPORAN BERITA KEMBAR BEDA TONE (TINJAUAN MANUSIA): {len(mixed_issues)} isu ===", flush=True)
    if not mixed_issues:
        print("Tidak ada isu dengan tone campur pada alur per artikel lama.", flush=True)
    for idx, mi in enumerate(mixed_issues, start=1):
        print(f"\n[{idx}] ISU ({mi['sumber_isu']}): {mi['isu']}", flush=True)
        print(f"    Distribusi tone alur lama : {mi['tone_lama_dist']} -> Tone Isu Bersatu: {mi['tone_isu_final']}", flush=True)
        for ang in mi["anggota"]:
            print(f"      - [{ang['tone_lama']} -> {ang['tone_baru']}] ({ang['media_name']}) {ang['title']}", flush=True)
    print("=" * 75 + "\n", flush=True)


def classify_tone_by_issue(
    articles: list[dict],
    registry=None,
    use_ai: bool = True,
    reeval_member_delta: int = 3,
    print_mixed_report: bool = True,
    combined_isu_tone: bool | None = None,
) -> list[dict]:
    """
    Fase 2: Evaluasi tone satu kali per isu:
    - Isu berukuran 1 memakai alur per artikel lama.
    - Isu yang sudah punya tone di registri & tambahan anggota < reeval_member_delta mewarisi tone tanpa API.
    - Klaster multi-berita 'klaster' (bila combined_isu_tone aktif) memakai GABUNGAN_ISU_TONE_PROMPT (penamaan + outlier + tone dalam 1 panggilan).
    - Isu 'rilis' & fallback klaster gagal parse memakai GROUP_TONE_PROMPT (maks 8 judul beragam + 2 cuplikan 400 char, batch maks 4).
    - Berita dalam outlier_ids dipecah ke klaster tunggal & dinilai ulang lewat alur per artikel lama.
    - Fallback jika Gemini tidak tersedia / kuota habis: suara terbanyak fallback, seri jatuh ke Netral (metode 'fallback-mayoritas').
    - Menyimpan tone, evaluated_at, member_count_at_eval di registri aktif.
    """
    global gemini_quota_exhausted, TOTAL_API_CALLS

    if not articles:
        return []

    # Pastikan tiap artikel memiliki id unik untuk pemetaan
    work_arts: list[dict] = []
    old_tones_map: dict = {}
    for idx, art in enumerate(articles, start=1):
        a = dict(art)
        if a.get("id") is None:
            a["id"] = idx
        t_str = str(a.get("title") or a.get("Title") or "").strip()
        txt_str = str(a.get("text") or a.get("isi") or "").strip()
        if not a.get("isu_id"):
            h_single = hashlib.sha1(t_str.lower().encode("utf-8")).hexdigest()[:10]
            a["isu_id"] = f"klaster_{h_single}"
            a["isu"] = a.get("isu") or a.get("Isu") or t_str
            a["sumber_isu"] = a.get("sumber_isu") or "klaster"

        existing_tone = str(a.get("Tone") or a.get("tone") or "").strip().capitalize()
        if existing_tone in ("Positif", "Netral", "Negatif"):
            old_tones_map[a["id"]] = existing_tone
        else:
            old_tones_map[a["id"]] = classify_tone_fallback(t_str, txt_str)[0]
        work_arts.append(a)

    # Kelompokkan berdasarkan isu_id secara berurutan/deterministik
    issues_map: dict[str, list[dict]] = {}
    for a in work_arts:
        issues_map.setdefault(str(a["isu_id"]), []).append(a)

    dcache = get_decision_cache()
    active_model = _MODEL_POOL.peek_active_model_name()
    reg_issues = registry.issues if registry is not None and hasattr(registry, "issues") else {}

    final_by_id: dict = {}
    singleton_articles: list[dict] = []
    singleton_isu_ids: list[str] = []
    group_eval_queue: list[dict] = []

    for isu_id in sorted(issues_map.keys()):
        members = issues_map[isu_id]
        reg_entry = reg_issues.get(isu_id)
        isu_name = str((reg_entry or {}).get("isu") or members[0].get("isu") or members[0].get("Isu") or "")
        sumber_isu = str((reg_entry or {}).get("sumber_isu") or members[0].get("sumber_isu") or "klaster")

        # 1. Cek konsistensi antar hari: apakah isu sudah pernah dinilai dan tambahan anggota < reeval_member_delta?
        if reg_entry and reg_entry.get("evaluated_at") and str(reg_entry.get("tone") or "").capitalize() in ("Positif", "Netral", "Negatif"):
            curr_members_total = max(int(reg_entry.get("member_count", 0) or 0), len(members))
            eval_members = int(reg_entry.get("member_count_at_eval", 0) or 0)
            delta = curr_members_total - eval_members
            if delta < int(reeval_member_delta):
                inh_tone = str(reg_entry["tone"]).capitalize()
                inh_alasan = str(reg_entry.get("tone_alasan") or "Mewarisi tone isu aktif dari run sebelumnya")
                inh_hub = str(reg_entry.get("tone_hubungan") or ("K1" if sumber_isu == "rilis" else "K3"))
                inh_arah = str(reg_entry.get("tone_arah") or "tidak ada")
                inh_raw_key = str(reg_entry.get("tone_keyakinan") or "tinggi")
                for m in members:
                    t_m = str(m.get("title") or m.get("Title") or "").strip()
                    b_m = str(m.get("text") or m.get("isi") or "").strip()
                    inh_key = _cap_confidence(inh_raw_key, bool(b_m))
                    asumsi_m = _detect_applied_assumptions(
                        hubungan=inh_hub, arah=inh_arah, tone=inh_tone, keyakinan=inh_key,
                        title=t_m, text=b_m, alasan=inh_alasan,
                        is_group_event=True, has_non_k1_member=(inh_hub == "K1"),
                    )
                    res_m = {
                        "id": m["id"],
                        "title": t_m,
                        "tone": inh_tone,
                        "hubungan": inh_hub,
                        "arah": inh_arah,
                        "dasar": "isu",
                        "alasan": inh_alasan,
                        "keyakinan": inh_key,
                        "asumsi_sementara": asumsi_m,
                        "isu_id": isu_id,
                        "isu": isu_name,
                        "sumber_isu": sumber_isu,
                        "metode": "inherited-isu",
                    }
                    final_by_id[m["id"]] = res_m
                    _log_tone_decision(
                        t_m, inh_tone, "isu", inh_alasan, "inherited-isu",
                        isu_id=isu_id, sumber_isu=sumber_isu, keyakinan=inh_key,
                        hubungan=inh_hub, arah=inh_arah, asumsi_sementara=asumsi_m,
                    )
                continue

        # 2. Isu berukuran 1 dan belum diwarisi -> memakai alur per artikel lama
        if len(members) == 1 and (not reg_entry or int(reg_entry.get("member_count", 1) or 1) <= 1):
            singleton_articles.append(members[0])
            singleton_isu_ids.append(isu_id)
            continue

        # 3. Isu berukuran >= 2 (atau klaster aktif yang butuh re-evaluasi)
        # Gabungkan judul lama dari sample_titles jika ini re-evaluasi
        augmented_members = list(members)
        if reg_entry and len(members) < 8:
            seen_t = {str(m.get("title") or m.get("Title") or "").strip().lower() for m in augmented_members}
            for st in (reg_entry.get("sample_titles") or []):
                stl = str(st).strip()
                if stl and stl.lower() not in seen_t:
                    seen_t.add(stl.lower())
                    augmented_members.append({"id": f"hist_{len(augmented_members)}", "title": stl, "text": ""})

        diverse_members, snippets = _select_diverse_members(augmented_members, max_n=8)
        if not snippets and reg_entry:
            snippets = [str(s)[:400] for s in (reg_entry.get("sample_snippets") or [])[:2] if s]

        cache_url = _issue_cache_key_url(members, reg_entry)

        group_eval_queue.append({
            "isu_id": isu_id,
            "isu": isu_name,
            "sumber_isu": sumber_isu,
            "members": members,
            "diverse_members": diverse_members,
            "snippets": snippets,
            "cache_url": cache_url,
            "reg_entry": reg_entry,
        })

    # Proses isu berukuran 1 lewat alur per artikel lama
    if singleton_articles:
        s_results = classify_tone_batch(singleton_articles, use_ai=use_ai, ensure_consistency=False)
        for s_art, s_isu_id, s_res in zip(singleton_articles, singleton_isu_ids, s_results):
            s_tone = str(s_res.get("tone") or "Netral")
            s_alasan = str(s_res.get("alasan") or "")
            s_out = dict(s_res)
            s_out["isu_id"] = s_isu_id
            s_out["isu"] = str(s_art.get("isu") or s_art.get("Isu") or s_art.get("title") or s_art.get("Title") or "").strip()
            s_out["sumber_isu"] = str(s_art.get("sumber_isu") or "klaster")
            s_out["keyakinan"] = s_res.get("keyakinan") or "sedang"
            final_by_id[s_art["id"]] = s_out
            if s_isu_id in reg_issues:
                reg_issues[s_isu_id]["tone"] = s_tone
                reg_issues[s_isu_id]["tone_alasan"] = s_alasan
                reg_issues[s_isu_id]["tone_hubungan"] = s_out.get("hubungan", "")
                reg_issues[s_isu_id]["tone_arah"] = s_out.get("arah", "")
                reg_issues[s_isu_id]["tone_keyakinan"] = s_out["keyakinan"]
                reg_issues[s_isu_id]["evaluated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                reg_issues[s_isu_id]["member_count_at_eval"] = max(1, int(reg_issues[s_isu_id].get("member_count", 1) or 1))

    # Routing multi-berita: GABUNGAN_ISU_TONE_PROMPT hanya untuk 'klaster' multi-berita; 'rilis' ke GROUP_TONE_PROMPT
    use_combined = USE_COMBINED_ISU_TONE if combined_isu_tone is None else bool(combined_isu_tone)
    combined_queue = [
        g for g in group_eval_queue
        if use_combined and g["sumber_isu"] == "klaster" and len(g["members"]) >= 2
    ]
    combined_ids = {id(g) for g in combined_queue}
    legacy_group_queue = [g for g in group_eval_queue if id(g) not in combined_ids]

    clean_fn, norm_fn, label_llm_fn = _isu_text_helpers()

    _run_issue_group_batches(combined_queue, combined=True, dcache=dcache, active_model=active_model, use_ai=use_ai)

    # Bila ada klaster gagal parse atau field 'isu' kosong, hanya klaster itu yang fallback ke jalur lama
    failed_combined = [g for g in combined_queue if not g.get("decision")]
    if failed_combined:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if use_ai and api_key and not gemini_quota_exhausted and label_llm_fn is not None:
            fb_inputs = [
                {
                    "cluster_idx": fb_idx,
                    "members": [dict(m, _internal_id=str(m["id"])) for m in g["members"]],
                }
                for fb_idx, g in enumerate(failed_combined, start=1)
            ]
            lbl_map = label_llm_fn(fb_inputs, use_ai=True)
            for fb_idx, g in enumerate(failed_combined, start=1):
                lbl = lbl_map.get(fb_idx, {})
                if lbl.get("isu"):
                    g["isu"] = str(lbl["isu"]).strip()
                if lbl.get("outlier_ids"):
                    id_to_sig = {str(m["id"]): _member_signature(m) for m in g["members"]}
                    g["pre_outlier_ids"] = [str(oid) for oid in lbl["outlier_ids"] if str(oid) in id_to_sig]
                    g["pre_outlier_sigs"] = [id_to_sig[oid] for oid in g["pre_outlier_ids"]]
        legacy_group_queue.extend(failed_combined)

    _run_issue_group_batches(legacy_group_queue, combined=False, dcache=dcache, active_model=active_model, use_ai=use_ai)

    # Terapkan keputusan ke seluruh anggota grup & tangani outlier serta fallback mayoritas
    all_outlier_articles: list[dict] = []
    outlier_meta_map: dict = {}

    lex_group = _load_kemenperin_lexicon()
    kem_group_terms = list(dict.fromkeys(
        lex_group["institusi_aliases"] + lex_group["jabatan_aliases"] + lex_group["pejabat_aliases"]
    ))

    for g in group_eval_queue:
        dec: dict[str, Any] | None = g.get("decision")
        if not dec:
            fb_det = _majority_fallback_detail(g["members"], sumber_isu=g["sumber_isu"])
            dec = {
                "tone": fb_det["tone"],
                "hubungan": fb_det["hubungan"],
                "arah": fb_det["arah"],
                "alasan": fb_det["alasan"],
                "asumsi_sementara": fb_det["asumsi_sementara"],
                "outlier_ids": g.get("pre_outlier_ids") or [],
                "outlier_sigs": g.get("pre_outlier_sigs") or [],
                "keyakinan": fb_det["keyakinan"],
                "metode": "fallback-mayoritas",
            }

        has_group_body = bool(g["snippets"])
        dec_tone = str(dec.get("tone") or "Netral")
        dec_alasan = str(dec.get("alasan") or "")
        dec_metode = str(dec.get("metode") or "fallback-mayoritas")
        dec_keyak = _cap_confidence(dec.get("keyakinan") or ("tinggi" if has_group_body else "sedang"), has_group_body)
        dec_hub = _normalize_hubungan(dec.get("hubungan"), default="K1" if g["sumber_isu"] == "rilis" else "K3")
        dec_arah = _normalize_arah(dec.get("arah"), default="tidak ada")

        outlier_sigs = set(dec.get("outlier_sigs") or [])
        outlier_ids = {str(x) for x in (dec.get("outlier_ids") or [])}
        isu_id = g["isu_id"]
        isu_name = str(dec.get("isu") or g["isu"] or "").strip()
        sumber_isu = g["sumber_isu"]

        kept_members = []
        group_outliers = []
        for m in g["members"]:
            mid_str = str(m["id"])
            m_sig = _member_signature(m)
            is_outlier = (m_sig in outlier_sigs) if "outlier_sigs" in dec else (mid_str in outlier_ids)
            if is_outlier:
                group_outliers.append(m)
            else:
                kept_members.append(m)

        # Update registri isu aktif
        if isu_id in reg_issues and (kept_members or not group_outliers):
            reg_entry = reg_issues[isu_id]
            reg_entry["tone"] = dec_tone
            reg_entry["tone_alasan"] = dec_alasan
            reg_entry["tone_hubungan"] = dec_hub
            reg_entry["tone_arah"] = dec_arah
            reg_entry["tone_keyakinan"] = dec_keyak
            reg_entry["tone_metode"] = dec_metode
            reg_entry["evaluated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if isu_name and sumber_isu != "rilis":
                reg_entry["isu"] = isu_name
                reg_entry["_norm_title"] = norm_fn(isu_name)
            if group_outliers and reg_entry.get("matched_articles"):
                reg_entry["matched_articles"] = [
                    ma for ma in reg_entry["matched_articles"]
                    if (
                        canonical_url(str(ma.get("canonical_url") or ma.get("link") or ""))
                        or str(ma.get("title") or "").strip().lower()
                    ) not in outlier_sigs
                ]
            if group_outliers:
                n_kept = max(len(kept_members), len(reg_entry.get("matched_articles") or []))
                reg_entry["member_count"] = max(n_kept, 1)
                reg_entry["member_count_at_eval"] = reg_entry["member_count"]
            else:
                reg_entry["member_count_at_eval"] = max(len(g["members"]), int(reg_entry.get("member_count", 0) or 0))

        for m in kept_members:
            t_m = str(m.get("title") or m.get("Title") or "").strip()
            b_m = str(m.get("text") or m.get("isi") or "").strip()
            member_has_kem = bool(_find_any_phrases(f"{t_m} {b_m}", kem_group_terms))
            has_non_k1 = (dec_hub == "K1") and not member_has_kem
            m_asumsi = _detect_applied_assumptions(
                hubungan=dec_hub,
                arah=dec_arah,
                tone=dec_tone,
                keyakinan=dec_keyak,
                title=t_m,
                text=b_m,
                alasan=dec_alasan,
                is_group_event=(len(kept_members) >= 2),
                has_non_k1_member=has_non_k1,
            )
            m["isu_id"] = isu_id
            m["isu"] = isu_name
            m["Isu"] = isu_name
            m["sumber_isu"] = sumber_isu
            res_m = {
                "id": m["id"],
                "title": t_m,
                "tone": dec_tone,
                "hubungan": dec_hub,
                "arah": dec_arah,
                "dasar": "isu",
                "alasan": dec_alasan,
                "keyakinan": dec_keyak,
                "asumsi_sementara": m_asumsi,
                "isu_id": isu_id,
                "isu": isu_name,
                "sumber_isu": sumber_isu,
                "metode": dec_metode,
            }
            final_by_id[m["id"]] = res_m
            _log_tone_decision(
                t_m, dec_tone, "isu", dec_alasan, dec_metode,
                isu_id=isu_id, sumber_isu=sumber_isu, keyakinan=dec_keyak,
                hubungan=dec_hub, arah=dec_arah, asumsi_sementara=m_asumsi,
            )

        for m in group_outliers:
            raw_o_title = str(m.get("title") or m.get("Title") or "").strip()
            clean_o_isu = clean_fn(raw_o_title) or raw_o_title or "Isu Industri Agro"
            norm_o_isu = norm_fn(clean_o_isu)
            single_isu_id = (
                f"klaster_{hashlib.sha1(norm_o_isu.encode('utf-8')).hexdigest()[:10]}"
                if norm_o_isu
                else (isu_id or f"klaster_{hashlib.sha1(raw_o_title.lower().encode('utf-8')).hexdigest()[:10]}")
            )
            m["isu_id"] = single_isu_id
            m["isu"] = clean_o_isu
            m["Isu"] = clean_o_isu
            m["sumber_isu"] = "klaster"
            all_outlier_articles.append(m)
            outlier_meta_map[m["id"]] = (single_isu_id, clean_o_isu, norm_o_isu, "klaster")

    # Outlier dinilai ulang secara individual dengan alur per artikel lama
    if all_outlier_articles:
        out_results = classify_tone_batch(all_outlier_articles, use_ai=use_ai, ensure_consistency=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for o_art, o_res in zip(all_outlier_articles, out_results):
            oid = o_art["id"]
            o_isu_id, o_isu_name, o_norm, o_sumber = outlier_meta_map.get(oid, ("", "", "", "klaster"))
            raw_o_title = str(o_art.get("title") or o_art.get("Title") or "").strip()
            if registry is not None and o_isu_id and o_isu_id not in reg_issues:
                o_link = str(o_art.get("link") or o_art.get("Link Website") or "")
                o_can_u = canonical_url(o_link) if o_link else ""
                o_date = str(o_art.get("published") or o_art.get("Tanggal") or now_str[:10])[:10]
                reg_issues[o_isu_id] = {
                    "isu_id": o_isu_id,
                    "isu": o_isu_name,
                    "sumber_isu": o_sumber,
                    "tanggal_awal": o_date,
                    "tanggal_terakhir": o_date,
                    "_norm_title": o_norm,
                    "tone": o_res.get("tone") or "Netral",
                    "tone_alasan": o_res.get("alasan") or "",
                    "tone_keyakinan": o_res.get("keyakinan") or "sedang",
                    "tone_metode": f"{o_res.get('metode', 'fallback')}-outlier",
                    "evaluated_at": now_str,
                    "member_count_at_eval": 1,
                    "member_count": 1,
                    "sample_titles": [raw_o_title] if raw_o_title else [],
                    "sample_snippets": [str(o_art.get("text") or o_art.get("isi") or "").strip()[:400]] if (o_art.get("text") or o_art.get("isi")) else [],
                    "matched_articles": [{
                        "id": oid,
                        "title": raw_o_title,
                        "link": o_link,
                        "canonical_url": o_can_u,
                        "media_name": str(o_art.get("media_name") or o_art.get("Media Name") or ""),
                        "tanggal": str(o_art.get("published") or o_art.get("Tanggal") or ""),
                        "skor": 1.0,
                    }],
                }
            o_entry = dict(o_res)
            o_entry["isu_id"] = o_isu_id
            o_entry["isu"] = o_isu_name
            o_entry["sumber_isu"] = o_sumber
            o_entry["keyakinan"] = o_res.get("keyakinan") or "sedang"
            o_entry["is_outlier"] = True
            o_entry["metode"] = f"{o_res.get('metode', 'fallback')}-outlier"
            final_by_id[oid] = o_entry

    if registry is not None and hasattr(registry, "save"):
        try:
            registry.save()
        except Exception:
            pass

    if print_mixed_report:
        mixed_rep = build_mixed_tone_report(work_arts, old_tones_map, final_by_id)
        print_mixed_tone_report(mixed_rep)

    return [final_by_id.get(a["id"], {}) for a in work_arts]

