"""
tone_classifier.py
Klasifikasi Tone/Sentimen Berita Industri Agro (IA) Ditjen Industri Agro Kemenperin:
- Sudut pandang: DAMPAK TERHADAP INDUSTRI AGRO NASIONAL / KEMENPERIN
- Penilai Utama: Gemini API (batch 5 artikel, text max 3000 chars)
- Fallback Konservatif: Rule-based berbasis frasa dengan penanganan negasi & konteks
- Pencatatan log ke hasil_scrapping/log_tone.jsonl (tanpa menambah kolom baru di Excel)
"""

import os
import sys
import re
import json
import time
from datetime import datetime

# Load environment variable
try:
    from config import load_env_file
    load_env_file()
except Exception:
    pass

CANDIDATE_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
]
_current_model_idx = 0
_model_instance = None
gemini_quota_exhausted = False
TOTAL_API_CALLS = 0


def get_api_call_count() -> int:
    global TOTAL_API_CALLS
    return TOTAL_API_CALLS


def reset_api_call_count():
    global TOTAL_API_CALLS
    TOTAL_API_CALLS = 0


LOG_TONE_FILE = os.path.join("hasil_scrapping", "log_tone.jsonl")


TONE_SYSTEM_PROMPT = """PERAN
Kamu adalah analis tone/sentimen media monitoring untuk Direktorat Jenderal Industri Agro (IA), Kementerian Perindustrian.
Tugasmu menentukan tone berita: "Positif", "Netral", atau "Negatif", dinilai dari sudut pandang DAMPAK TERHADAP INDUSTRI AGRO NASIONAL / KEMENPERIN.

=== DEFINISI TONE ===
1. NEGATIF (masalah, ancaman, atau kerugian bagi industri agro / Kemenperin):
- Krisis / kerugian / penurunan kinerja: PHK, pabrik tutup, pailit, lesu, kontraksi industri, penurunan ekspor/produksi, margin tergerus, proyeksi harga komoditas tertekan.
- Masalah pasokan / hukum: rokok ilegal makin marak, kelangkaan bahan baku, barang disita aparat, unjuk rasa / demo buruh / pemogokan.
- Keluhan petani HANYA untuk sektor tembakau (contoh: serapan pabrik rendah, harga tembakau ditekan). Keluhan petani non-tembakau adalah masalah hulu pertanian, bukan industri manufaktur.
- Judul kontras: "Ekspor tumbuh, tapi harga anjlok" langsung NEGATIF, karena pesan setelah kata "tapi/namun" adalah arah dominan berita.
- Dampak regulasi/biaya: Kenaikan cukai yang membebani industri rokok/IHT (beban biaya naik, ancam PHK, rokok ilegal naik).
- Penerimaan negara dari cukai turun atau dinilai tak efektif mendorong penerimaan.
- Penurunan daya saing atau kehilangan pangsa pasar komoditas agro global.

2. POSITIF (kemajuan, peluang, atau keberhasilan industri agro):
- "dorong hilirisasi", investasi baru, ekspansi kapasitas, peresmian pabrik baru, ekspor meningkat/tumbuh, inovasi industri, surplus perdagangan agro.
- Peningkatan nilai tambah komoditas industri agro: ajakan dorong karet tak lagi dijual mentah, dorong masuk skema BPDP untuk nilai tambah petani, program transformasi ekonomi agro.
- Kemitraan strategis perdagangan bilateral/internasional (contoh: GAPKI dorong kemitraan sawit Indonesia dan India).
- Penerimaan negara dari cukai naik (konteks fiskal negara positif).

3. NETRAL:
- Berita informasi biasa tanpa masalah atau prestasi mencolok (update harga pasar harian/rutin, jadwal pameran/acara, pengumuman seremonial tanpa dampak).
- PENTING: Berita dorong hilirisasi, peningkatan nilai tambah, dan investasi BUKAN Netral, melainkan POSITIF.

=== ATURAN WAJIB: KONTEKS & DASAR HARUS JUJUR ===
a. Kolom "dasar" WAJIB JUJUR:
   - Jika dasar = "judul", alasan HANYA BOLEH menggunakan informasi yang tertulis di judul. DILARANG menyebut informasi yang hanya ada di isi berita (seperti B50, El Nino, atau data teks) jika dasar adalah "judul".
   - Jika alasan menggunakan informasi atau konteks dari isi berita, dasar WAJIB diisi "isi".
b. Sudut Pandang Terdampak:
   - Kenaikan cukai = NEGATIF jika membebani industri tembakau (biaya naik, volume turun, ancaman PHK, dorong rokok ilegal).
   - Kenaikan cukai = POSITIF jika konteksnya penerimaan negara naik.
   - Penerimaan negara dari cukai TURUN = NEGATIF.
   - Harga komoditas naik: Positif bagi produsen/eksportir agro, tapi Negatif jika membebani industri pengolah sebagai kenaikan biaya bahan baku. Nilai dari subjek utama berita.
c. Negasi Wajib Ditangani:
   - Kata negasi: tidak, tak, bukan, belum, tanpa, nihil, bebas dari, batal.
   - "Industri Mamin Tidak Rugi Tahun Ini" -> Positif / Netral, BUKAN Negatif.
   - "Harga CPO Tidak Naik Pekan Ini" -> Netral, BUKAN Positif.
d. Urutan Penilaian:
   - Judul didahulukan. Jika judul sudah jelas mencerminkan dampak (misal: dorong hilirisasi, harga tertekan, resmikan pabrik), gunakan dasar "judul".
   - Jika judul belum jelas atau informatif biasa, baru nilai dari isi berita secara KESELURUHAN, dengan dasar "isi".

=== CONTOH BENCHMARK TEST CASE (WAJIB DIPATUHI) ===
- "Industri Mamin Tidak Rugi Tahun Ini" -> Positif / Netral (BUKAN Negatif)
- "Harga CPO Tidak Naik Pekan Ini" -> Netral (BUKAN Positif)
- "Ekspor Tumbuh, Tapi Harga Anjlok" -> Negatif (dasar: judul)
- "Kenaikan Cukai Bebani Industri Rokok, Ancam PHK Pekerja" -> Negatif (dasar: judul)
- "Penerimaan Negara dari Cukai Naik 8 Persen" -> Positif (dasar: judul)
- "Penerimaan Negara dari Cukai Hasil Tembakau Turun, Kenaikan Tarif Dinilai Tak Efektif" -> Negatif (dasar: judul)
- "Kenaikan Cukai Hasil Tembakau Tak Lagi Efektif Dorong Penerimaan Negara" -> Negatif (dasar: judul)
- "BPS Ungkap Penyebab Karet hingga Teh RI Kehilangan Pangsa Pasar Global" -> Negatif (dasar: judul)
- "Rokok Ilegal Makin Marak, Aturan IHT Jadi Sorotan" -> Negatif (dasar: judul)
- "Menperin Resmikan Pabrik Baru" -> Positif (dasar: judul)
- "Jadwal Pameran Trade Expo Indonesia 2026" -> Netral (dasar: judul)
- "Petani Tembakau Keluhkan Serapan Pabrik Rendah" -> Negatif (dasar: judul)
- "Bukan Sekadar Olah Bahan Mentah, BPDP Dorong Hilirisasi Perkebunan Jadi Transformasi Ekonomi" -> Positif (dasar: judul)
- "Petani Harus Nikmati Nilai Tambah, Darori Dorong Karet Tak Lagi Dijual Mentah" -> Positif (dasar: judul)
- "Minta Karet Masuk Skema BPDP, Darori Wonodipuro: Petani Perlu Nilai Tambah" -> Positif (dasar: judul)
- "GAPKI Dorong Kemitraan Sawit antara Indonesia dan India" -> Positif (dasar: judul, alasan: GAPKI mendorong kemitraan sawit antara Indonesia dan India untuk memperkuat pasar ekspor)
- "Harga Pulp Berpotensi Tertekan pada 2027, Analis Ungkap Prospek INKP" -> Negatif (dasar: judul, alasan: Potensi penurunan harga pulp mengancam kinerja industri dan emiten)

FORMAT OUTPUT
Balas HANYA dengan JSON valid tanpa markdown/backticks, format:
{
  "hasil": [
    {
      "id": <id>,
      "tone": "Positif" | "Netral" | "Negatif",
      "dasar": "judul" | "isi",
      "alasan": "<satu kalimat penjelasan padat>"
    }
  ]
}
"""


def _get_gemini_model(force_next: bool = False):
    """Menginisialisasi model Generative AI Gemini secara lazy dengan fallback model dinamis."""
    global _model_instance, _current_model_idx, gemini_quota_exhausted

    if gemini_quota_exhausted:
        return None

    if _model_instance is not None and not force_next:
        return _model_instance

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    if force_next:
        _current_model_idx += 1

    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key, transport="rest")  # type: ignore

        while _current_model_idx < len(CANDIDATE_MODELS):
            m_name = CANDIDATE_MODELS[_current_model_idx]
            try:
                m = genai.GenerativeModel(m_name)  # type: ignore
                _model_instance = m
                return _model_instance
            except Exception:
                _current_model_idx += 1
                continue

        gemini_quota_exhausted = True
        return None
    except Exception:
        return None


# =========================================================================
# FALLBACK RULE-BASED KONSERVATIF
# =========================================================================

NEGATION_WORDS = ["tidak", "tak", "bukan", "belum", "tanpa", "nihil", "bebas dari", "batal"]

CONTRAST_WORDS = ["tapi", "tetapi", "namun", "meski", "meskipun", "walau", "walaupun", "sayangnya"]

# Frasa negatif spesifik industri agro
NEGATIVE_PHRASES = [
    "pemutusan hubungan kerja", "tutup pabrik", "menutup pabrik", "gulung tikar",
    "kehilangan pangsa pasar", "kehilangan pangsa", "pangsa pasar turun",
    "penerimaan negara dari cukai turun", "penerimaan cukai turun", "penerimaan negara turun",
    "tak lagi efektif", "tidak lagi efektif", "tak efektif", "tidak efektif", "kurang efektif",
    "rokok ilegal makin marak", "rokok ilegal", "cukai palsu",
    "harga anjlok", "harga jatuh", "terjun bebas", "turun drastis", "turun tajam",
    "ancam phk", "ancaman phk", "bebani industri", "merugikan industri", "kontraksi",
    "serapan pabrik rendah", "serapan tembakau rendah", "keluhan petani tembakau",
    "petani tembakau keluhkan", "kelangkaan bahan baku", "kelangkaan pasokan",
    "barang disita", "disita petugas", "unjuk rasa buruh", "demo buruh",
    "bangkrut", "pailit", "terpuruk", "anjlok", "phk",
    "berpotensi tertekan", "harga tertekan", "harga pulp berpotensi tertekan"
]

# Frasa positif spesifik industri agro
POSITIVE_PHRASES = [
    "resmikan pabrik baru", "meresmikan pabrik baru", "pabrik baru",
    "penerimaan negara dari cukai naik", "penerimaan cukai naik", "penerimaan negara naik",
    "ekspor tumbuh", "ekspor naik", "ekspor meningkat", "peningkatan ekspor",
    "dorong hilirisasi", "hilirisasi industri", "hilirisasi perkebunan", "investasi baru", "realisasi investasi",
    "inovasi industri", "surplus perdagangan", "surplus", "daya saing industri",
    "nilai tambah", "nikmati nilai tambah", "dorong kemitraan", "kemitraan sawit",
    "dorong karet", "skema bpdp", "transformasi ekonomi", "tak lagi dijual mentah",
    "resmikan pabrik", "meresmikan pabrik", "resmikan", "meresmikan"
]


def _has_negation_before(text_lower: str, match_start: int, window_words: int = 3) -> bool:
    """Mengecek apakah kata/frasa didahului negasi dalam jendela 3 kata."""
    prefix = text_lower[:match_start].strip()
    words = prefix.split()
    if not words:
        return False
    preceding_window = " ".join(words[-window_words:])
    for neg in NEGATION_WORDS:
        # Cocokkan negasi sebagai kata utuh di jendela prefix
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


def classify_tone_fallback(title: str, text: str = "") -> tuple[str, str, str]:
    """
    Fallback rule-based konservatif:
    - Judul diprioritaskan.
    - Cek kontras judul (contoh: 'X, tapi Y').
    - Negatif hanya jika judul punya frasa negatif tanpa negasi, ATAU >= 3 frasa negatif unik di isi.
    - Mengembalikan (tone, dasar, alasan).
    """
    t_clean = (title or "").strip()
    t_low = t_clean.lower()
    b_clean = (text or "").strip()
    b_low = b_clean.lower()

    # 1. Cek pola kontras di judul (contoh: "Ekspor Tumbuh, Tapi Harga Anjlok")
    for cw in CONTRAST_WORDS:
        pattern = re.compile(rf"\b{re.escape(cw)}\b", re.IGNORECASE)
        m = pattern.search(t_low)
        if m:
            after_contrast = t_low[m.end():]
            neg_after = _find_unnegated_phrases(after_contrast, NEGATIVE_PHRASES)
            if neg_after:
                return "Negatif", "judul", f"Judul kontras dengan pesan negatif dominan ({neg_after[0]})"
            pos_after = _find_unnegated_phrases(after_contrast, POSITIVE_PHRASES)
            if pos_after:
                return "Positif", "judul", f"Judul kontras dengan pesan positif dominan ({pos_after[0]})"

    # Pengecualian khusus: Kenaikan cukai/tarif/pajak tidak boleh otomatis positif
    is_cukai_increase = bool(re.search(r"\b(kenaikan|naik)\s+(cukai|tarif|pajak)\b", t_low))
    is_penerimaan_naik = bool(re.search(r"\bpenerimaan\s+negara\b.*\bnaik\b", t_low)) or \
                          bool(re.search(r"\b(cukai|penerimaan)\b.*\bnaik\s+\d+", t_low))

    # 2. Evaluasi judul berita
    neg_in_title = _find_unnegated_phrases(t_low, NEGATIVE_PHRASES)
    pos_in_title = _find_unnegated_phrases(t_low, POSITIVE_PHRASES)

    # Filter: jika judul hanya memuat kenaikan cukai tapi bukan penerimaan negara naik, abaikan dari pos
    if is_cukai_increase and not is_penerimaan_naik:
        pos_in_title = [p for p in pos_in_title if "naik" not in p]

    if neg_in_title and not pos_in_title:
        return "Negatif", "judul", f"Judul memuat indikator masalah industri ({neg_in_title[0]})"

    if pos_in_title and not neg_in_title:
        return "Positif", "judul", f"Judul memuat indikator kemajuan industri ({pos_in_title[0]})"

    if neg_in_title and pos_in_title:
        if len(neg_in_title) > len(pos_in_title):
            return "Negatif", "judul", f"Masalah industri dominan di judul ({neg_in_title[0]})"
        elif len(pos_in_title) > len(neg_in_title):
            return "Positif", "judul", f"Kemajuan industri dominan di judul ({pos_in_title[0]})"
        return "Netral", "judul", "Sinyal positif dan negatif seimbang di judul"

    # Khusus kasus negasi di judul: "Tidak Rugi" -> Netral/Positif, "Tidak Naik" -> Netral
    if re.search(r"\b(tidak|tak|belum|bukan)\s+rugi\b", t_low):
        return "Netral", "judul", "Judul menafikan kerugian (tidak rugi)"
    if re.search(r"\b(tidak|tak|belum|bukan)\s+naik\b", t_low):
        return "Netral", "judul", "Judul menafikan kenaikan harga/kinerja (tidak naik)"

    # 3. Evaluasi isi berita (jika judul tidak jelas/netral)
    if b_low:
        neg_in_body = _find_unnegated_phrases(b_low, NEGATIVE_PHRASES)
        pos_in_body = _find_unnegated_phrases(b_low, POSITIVE_PHRASES)

        # Wajib minimal 3 frasa negatif berbeda di isi tanpa negasi
        if len(neg_in_body) >= 3 and len(neg_in_body) > len(pos_in_body):
            return "Negatif", "isi", f"Ditemukan {len(neg_in_body)} indikator masalah industri di isi artikel"

        if len(pos_in_body) >= 3 and len(pos_in_body) > len(neg_in_body):
            return "Positif", "isi", f"Ditemukan {len(pos_in_body)} indikator kemajuan industri di isi artikel"

    # Default fallback: Ketidakjelasan = Netral
    return "Netral", "judul", "Informasi umum tanpa masalah atau prestasi mencolok"


# =========================================================================
# PENILAI UTAMA GEMINI API DENGAN BATCH 5 ARTIKEL
# =========================================================================

def _log_tone_decision(title: str, tone: str, dasar: str, alasan: str, metode: str):
    """Mencatat keputusan tone ke hasil_scrapping/log_tone.jsonl."""
    os.makedirs(os.path.dirname(LOG_TONE_FILE), exist_ok=True)
    entry = {
        "title": title,
        "tone": tone,
        "dasar": dasar,
        "alasan": alasan,
        "metode": metode,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(LOG_TONE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def classify_tone_batch(articles: list[dict], use_ai: bool = True, ensure_consistency: bool = True) -> list[dict]:
    """
    Mengklasifikasikan tone sekumpulan artikel:
    - Input: list of dict {'id': ..., 'title': ..., 'text': ...}
    - Jika ensure_consistency=True: mengelompokkan judul mirip (rapidfuzz >= 90) agar bertone SAMA.
    - Batch kecil: 5 artikel per pemanggilan Gemini API.
    - Output: list of dict {'id': ..., 'tone': ..., 'dasar': ..., 'alasan': ..., 'metode': 'AI'|'fallback'}
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
            "dasar": "judul",
            "alasan": "Informasi umum tanpa masalah atau prestasi",
            "metode": "fallback"
        }
        for art in grp:
            art_id = art.get("id")
            art_title = str(art.get("title", "")).strip()
            art_res = {
                "id": art_id,
                "title": art_title,
                "tone": g_res["tone"],
                "dasar": g_res["dasar"],
                "alasan": g_res["alasan"],
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
                    metode=g_res["metode"]
                )

    return [orig_results_map.get(a.get("id"), {}) for a in articles]


def _process_one_chunk(chunk: list[dict], use_ai: bool = True) -> list[dict]:
    """Memproses 1 batch (maksimal 5 artikel) dengan AI, fallback jika gagal."""
    global gemini_quota_exhausted, TOTAL_API_CALLS

    # Siapkan payload
    formatted_items = []
    for a in chunk:
        item_text = str(a.get("text", "")).strip()[:3000]
        formatted_items.append({
            "id": a["id"],
            "title": str(a.get("title", "")).strip(),
            "text": item_text
        })

    resolved_by_id = {}

    if use_ai and not gemini_quota_exhausted:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            model = _get_gemini_model()
            if model is not None:
                payload_str = json.dumps(formatted_items, ensure_ascii=False, indent=2)
                user_msg = f"Berikut daftar artikel untuk dinilai tonenya (total: {len(formatted_items)}):\n{payload_str}"
                full_prompt = f"{TONE_SYSTEM_PROMPT}\n\n{user_msg}"

                max_retries = 3
                for attempt in range(max_retries):
                    if model is None:
                        break
                    try:
                        TOTAL_API_CALLS += 1
                        resp = model.generate_content(full_prompt, request_options={"timeout": 60})
                        resp_text = (resp.text or "").strip()
                        # Bersihkan markdown json jika ada
                        clean_json = re.sub(r"^```(?:json)?\s*", "", resp_text, flags=re.MULTILINE)
                        clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE).strip()
                        m = re.search(r"\{[\s\S]*\}", clean_json)
                        if m:
                            clean_json = m.group(0)

                        hasil_list = []
                        try:
                            data = json.loads(clean_json, strict=False)
                            hasil_list = data.get("hasil", [])
                        except Exception:
                            # Regex fallback jika JSON decode gagal
                            pattern = r'\{\s*"id"\s*:\s*([^,]+?)\s*,\s*"tone"\s*:\s*"([^"]+?)"\s*,\s*"dasar"\s*:\s*"([^"]+?)"\s*,\s*"alasan"\s*:\s*"(.*?)"\s*\}'
                            matches = re.findall(pattern, clean_json, re.DOTALL)
                            for m_id, m_tone, m_dasar, m_alasan in matches:
                                try:
                                    p_id = json.loads(m_id)
                                except Exception:
                                    p_id = m_id.strip().strip('"')
                                hasil_list.append({
                                    "id": p_id,
                                    "tone": m_tone,
                                    "dasar": m_dasar,
                                    "alasan": m_alasan.strip()
                                })

                        for h in hasil_list:
                            h_id = h.get("id")
                            t_val = str(h.get("tone", "")).strip().capitalize()
                            if t_val not in ["Positif", "Netral", "Negatif"]:
                                t_val = "Netral"
                            d_val = str(h.get("dasar", "judul")).strip().lower()
                            if d_val not in ["judul", "isi"]:
                                d_val = "judul"
                            alasan_val = str(h.get("alasan", "")).strip()

                            res_obj = {
                                "id": h_id,
                                "tone": t_val,
                                "dasar": d_val,
                                "alasan": alasan_val,
                                "metode": "AI"
                            }
                            if h_id is not None:
                                resolved_by_id[h_id] = res_obj
                                try:
                                    resolved_by_id[int(h_id)] = res_obj
                                except (ValueError, TypeError):
                                    pass
                                resolved_by_id[str(h_id)] = res_obj

                        # Jika semua artikel di chunk berhasil terisi, selesai
                        if all(a["id"] in resolved_by_id for a in chunk):
                            break
                        # Jika belum semua tapi ada hasil, retry sekali jika masih ada sisa attempt
                        if attempt == max_retries - 1:
                            break
                    except Exception as e:
                        err_s = str(e).lower()
                        if "429" in err_s or "quota" in err_s or "resourceexhausted" in err_s:
                            if "perday" in err_s or "daily" in err_s:
                                print(f"[GEMINI] Batas harian tercapai. Beralih model...", flush=True)
                                model = _get_gemini_model(force_next=True)
                                if model is None:
                                    gemini_quota_exhausted = True
                                    break
                            else:
                                wait_sec = 5.0 * (attempt + 1)
                                print(f"[GEMINI 429] Rate limit, jeda {wait_sec}s...", flush=True)
                                time.sleep(wait_sec)
                        else:
                            print(f"[GEMINI ERROR] {e}. Retry {attempt+1}/{max_retries}...", flush=True)
                            model = _get_gemini_model(force_next=True)
                            if model is None:
                                gemini_quota_exhausted = True
                                break
                            time.sleep(2.0)

    # Cek ID yang hilang atau jika AI tidak dipakai / gagal
    final_chunk_results = []
    for a in chunk:
        a_id = a["id"]
        t_str = str(a.get("title", "")).strip()
        txt_str = str(a.get("text", "")).strip()

        if a_id in resolved_by_id:
            res = resolved_by_id[a_id]
        else:
            # Fallback rule-based
            fb_tone, fb_dasar, fb_alasan = classify_tone_fallback(t_str, txt_str)
            res = {
                "id": a_id,
                "tone": fb_tone,
                "dasar": fb_dasar,
                "alasan": fb_alasan,
                "metode": "fallback"
            }

        # 0.4 Enforce dasar honesty: jika dasar == 'judul', alasan hanya boleh memakai informasi di judul
        if res.get("dasar") == "judul":
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
            str(res.get("metode") or "fallback")
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
