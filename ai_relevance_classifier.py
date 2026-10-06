"""
ai_relevance_classifier.py
Lapis terakhir klasifikasi relevansi Industri Agro menggunakan Google Gemini API.
"""

import os
import json
import re
import time
from pathlib import Path
from datetime import datetime

# Pastikan environment variable terisi dari .env jika belum
try:
    from config import load_env_file
    load_env_file()
except Exception:
    pass

# Flag global untuk quota limit Gemini API
gemini_quota_exhausted = False
_model_instance = None
_model_init_attempted = False

SYSTEM_PROMPT = (
    "Kamu adalah classifier untuk menentukan apakah sebuah artikel berita membahas Industri "
    "Agro Indonesia: industri/manufaktur/pengolahan/ekspor-impor/kebijakan Kemenperin terkait "
    "sektor Mamin (makanan-minuman), CPO/sawit, hasil tembakau/vape, kayu/furnitur, kertas, "
    "hasil laut olahan, dan komoditas agro lainnya (gula, kelapa, kopi, kakao, karet, dst). "
    "BUKAN relevan kalau isinya soal: kriminal/kecelakaan, satwa liar, iklan/listing bisnis, "
    "galeri foto, profil sekolah/institusi tanpa berita, campaign donasi, harga pasar eceran "
    "harian, penegakan hukum/ritel lokal (Satpol PP, DPRD daerah), atau konteks lain yang "
    "cuma kebetulan menyebut nama komoditas tanpa substansi industri. Jawab HANYA dalam "
    'format JSON: {"relevan": true/false, "alasan": "..."} (alasan 1 kalimat singkat).'
)


def _get_gemini_model():
    """Menginisialisasi model Generative AI Gemini secara lazy."""
    global _model_instance, _model_init_attempted
    if _model_init_attempted:
        return _model_instance

    _model_init_attempted = True
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        # Coba model 'gemini-flash-lite-latest', 'gemini-flash-latest', atau 'gemini-flash-lite'
        candidate_models = [
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-flash-lite",
            "gemini-2.5-flash",
            "gemini-1.5-flash"
        ]
        for m_name in candidate_models:
            try:
                m = genai.GenerativeModel(m_name)
                _model_instance = m
                break
            except Exception:
                continue

        return _model_instance
    except Exception as e:
        print(f"[PERINGATAN] Gagal menginisialisasi Gemini API: {e}")
        return None


def classify_agro_relevance(title: str, text_snippet: str = "") -> tuple[bool | None, str]:
    """
    Mengklasifikasikan apakah berita relevan dengan Industri Agro Indonesia via Gemini API.

    Returns:
        tuple[bool | None, str]:
        - (True, alasan): Artikel relevan dengan Industri Agro.
        - (False, alasan): Artikel ditolak/tidak relevan.
        - (None, alasan): API Key tidak ada / AI nonaktif (pipeline lanjut tanpa filter AI).
    """
    global gemini_quota_exhausted

    # 1. Jika kuota sudah habis sebelumnya, loloskan by default tanpa panggil API
    if gemini_quota_exhausted:
        return True, "quota_exhausted"

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None, "api_key_missing"

    model = _get_gemini_model()
    if model is None:
        return None, "model_unavailable"

    # User message: title + 200 karakter pertama teks
    snippet_clean = (text_snippet or "").strip()[:200]
    user_content = f"Judul: {title}\nCuplikan Teks: {snippet_clean}"
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_content}"

    try:
        # Berikan jeda kecil 0.5 - 1.0 detik antar panggilan untuk mencegah rate-limit per menit
        time.sleep(0.7)

        response = model.generate_content(full_prompt)
        resp_text = (response.text or "").strip()

        # Ekstrak JSON dari response (tangani blok ```json ... ```)
        json_match = re.search(r"\{.*?\}", resp_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            is_rel = bool(data.get("relevan", True))
            reason = str(data.get("alasan", "")).strip()
            return is_rel, reason
        else:
            # Fallback aman jika parsing JSON gagal
            return True, "parse_fallback"

    except Exception as e:
        err_msg = str(e).lower()
        # Deteksi rate limit / kuota habis (429, quota exceeded, ResourceExhausted)
        if "429" in err_msg or "quota" in err_msg or "resourceexhausted" in err_msg:
            gemini_quota_exhausted = True
            print("[PERINGATAN] Kuota Gemini API harian habis, sisa artikel lolos tanpa filter AI.")
            return True, "quota_exhausted"

        # Error lainnya (misal network glitch sementara), fallback aman ke True
        return True, f"error_fallback: {e}"


def log_ai_rejection(
    title: str,
    reason: str,
    published: str = "",
    keyword: str = "",
    log_path: str | Path | None = None,
) -> None:
    """
    Mencatat penolakan artikel oleh AI ke file log JSONL terpisah.
    Default: hasil_scrapping/log_ai_rejection.jsonl
    """
    if log_path is None:
        log_dir = Path("hasil_scrapping")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "log_ai_rejection.jsonl"
    else:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "title": title,
        "alasan": reason,
        "tanggal": str(published or ""),
        "keyword": str(keyword or "")
    }

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[PERINGATAN] Gagal menulis log rejection AI: {e}")
