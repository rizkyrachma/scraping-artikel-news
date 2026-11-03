"""
auto_recheck.py
Tahap 'Auto Cek Ulang' Otomatis untuk Pipeline Media Monitoring Ditjen Industri Agro (Kemenperin).
Memastikan data akhir HANYA berisi berita sektor HILIR (industri pengolahan/manufaktur), bukan hulu.

Alur:
1. Pass 1 (Aturan Pasti / Deterministic Rules):
   - Blacklist domain/tipe berkas (PDF, foreign spam).
   - Hulu pertanian/perkebunan (lahan, HGU, bibit, benih, tanam, panen raya, produksi mentah, harga petani, Kementan).
   - Keluhan petani (kecuali sektor tembakau).
   - Kriminal, satwa, bencana, harga pasar eceran sembako.
   - Teknis administrasi Bea Cukai lokal (izin NPPBKC satu perusahaan).
   - Headline memuat UMKM.
   - Aksi pendanaan korporasi murni (obligasi, sukuk, rights issue, rating utang Pefindo).
   - Judul hanya nama entitas, resep masakan, promosi ritel supermarket, pelatihan ibu-ibu/KWT desa.
   - Berita Kemenperin non-agro (otomotif/hybrid/EV, galangan kapal, baja/logam skrap, bendung irigasi PU, keramik).
   - Arsip lama & kata bermakna ganda (perahu karet, jam karet, Kelapa Gading, Kakao Entertainment).

2. Pass 2 (AI Batch Relevance Classifier):
   - Menganalisis judul + cuplikan isi teks lengkap (konteks keseluruhan).
   - Prompt resmi Hilir vs Bukan Hilir Ditjen Industri Agro.
   - Output per artikel: {"id": ..., "label": "HILIR" | "BUKAN_HILIR" | "RAGU", "alasan": "..."}.
   - Response caching & model fallback pool.
   - Grounding check.
   - Artikel BUKAN_HILIR dibuang. Artikel HILIR & RAGU lanjut ke Pass 3.

3. Pass 3 dan seterusnya (Audit Loop / Devil's Advocate):
   - Mengaudit ulang HANYA artikel HILIR dan RAGU dengan prompt audit super ketat.
   - Mencari celah/alasan apakah artikel sebenarnya hulu, non-agro, promosi/ritel, atau non-manufaktur.
   - Artikel tetap HILIR hanya jika AI tidak menemukan alasan kuat untuk membuangnya.
   - Loop berulang sampai tidak ada yang dibuang (konvergen), maksimal 4 putaran audit.
   - Artikel berlabel RAGU di akhir TIDAK dibuang, diberi 'Status Review' = 'PERLU CEK MANUAL'.

4. Pencatatan & Pelaporan:
   - Tidak ada penghapusan data permanen.
   - Seluruh artikel yang dibuang dicatat di discarded_articles.json (judul, link, alasan, pass).
   - Laporan ringkas dicetak di konsol (total awal, dibuang per pass, sisa, ragu, analisis 5 artikel acak).
"""

import os
import sys
import re
import json
import time
import random
import hashlib
from pathlib import Path
from datetime import datetime

# Impor internal
try:
    from config import load_env_file
    load_env_file()
except Exception:
    pass

try:
    from relevance_filter import is_pdf_document, is_foreign_noise_domain
except Exception:
    def is_pdf_document(url="", title="", sumber_data=""):
        return bool(sumber_data and sumber_data.upper() == "PDF") or ".pdf" in (url or "").lower()
    def is_foreign_noise_domain(url=""):
        return ".vn" in (url or "").lower()


# ==============================================================================
# 1. KONFIGURASI MODEL & POOL GEMINI AI
# ==============================================================================
CANDIDATE_MODELS = [
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]
_current_model_idx = 0
_model_instance = None
gemini_quota_exhausted = False

CACHE_FILE_DEFAULT = os.path.join("hasil_scrapping", "cache_ai_recheck.json")


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
        print("  [AI POOL] Seluruh model kandidat Gemini telah dicoba / kuota habis.", flush=True)
        return None
    except Exception as e:
        print(f"  [AI POOL] Gagal menginisialisasi Gemini API: {e}", flush=True)
        return None


# ==============================================================================
# 2. CACHE MANAJER UNTUK MENGHEMAT KUOTA API
# ==============================================================================
class RecheckCache:
    def __init__(self, cache_path: str = CACHE_FILE_DEFAULT):
        self.cache_path = cache_path
        self.cache_data = {}
        self._load()

    def _load(self):
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self.cache_data = json.load(f)
            except Exception:
                self.cache_data = {}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  [CACHE WARNING] Gagal menyimpan cache: {e}", flush=True)

    def get_key(self, title: str, snippet: str, pass_name: str) -> str:
        raw = f"{title.strip().lower()}|{snippet.strip()[:200].lower()}|{pass_name}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, title: str, snippet: str, pass_name: str) -> dict | None:
        key = self.get_key(title, snippet, pass_name)
        return self.cache_data.get(key)

    def set(self, title: str, snippet: str, pass_name: str, result: dict):
        key = self.get_key(title, snippet, pass_name)
        self.cache_data[key] = result


# ==============================================================================
# 3. PASS 1: ATURAN PASTI (DETERMINISTIC RULES)
# ==============================================================================
DETERMINISTIC_RULES = [
    # 1. Non-Agro (Otomotif, Logam, Maritim, Irigasi PU, Kebakaran Hutan, Pabrik Sepatu, Smart City)
    (lambda t: any(w in t for w in ["insentif hybrid", "reev", "ganjil genap", "mobil listrik", "mobil double cabin", "lebih hemat bbm dari hybrid", "toyota perluas produksi"]), "Bukan Agro (Otomotif / Kendaraan Listrik ILMATE)"),
    (lambda t: "galangan kapal" in t, "Bukan Agro (Industri Maritim ILMATE)"),
    (lambda t: "skrap baja" in t, "Bukan Agro (Logam / Baja ILMATE)"),
    (lambda t: "bendung karet" in t, "Bukan Agro (Infrastruktur Irigasi PU / Sumber Daya Air)"),
    (lambda t: "kabut asap" in t or "haze victims" in t, "Bukan Agro (Bencana Kebakaran Hutan / Lingkungan)"),
    (lambda t: "as cabut sebagian tarif impor kanada" in t, "Bukan Agro (Tarif Kayu Luar Negeri AS-Kanada)"),
    (lambda t: "indonesia-rusia perkuat kerja sama ekonomi" in t, "Bukan Agro (Kerja Sama Bilateral Kepolisian)"),
    (lambda t: "indonesia-azerbaijan" in t or "indonesia-eu business forum" in t or "indonesia – eu" in t or "indonesia - eu" in t, "Bukan Agro (Kerja Sama Bilateral Umum Non-Agro)"),
    (lambda t: "smart city temanggung" in t, "Bukan Agro (Profil Smart City Daerah)"),
    (lambda t: "repositori institusi" in t, "Artifact Web (Halaman Repositori Akademik)"),
    (lambda t: "peraturan pemerintah nomor 189 tahun 1961" in t, "Arsip Lama (Regulasi PP Tahun 1961)"),
    (lambda t: "produksi susu september mencapai 2,928 juta ton, nai" in t, "Data Asing (Biro Statistik Nasional China NBS)"),
    (lambda t: "joyland sessions" in t, "Bukan Agro (Festival Musik Joyland)"),
    (lambda t: "pt pwi 6" in t, "Bukan Agro (Pabrik Sepatu PT PWI 6)"),
    (lambda t: "lee biscuits" in t or "setelah 92 tahun, pabrik biskuit legendaris ini akhirnya tutup" in t or "92 tahun berjalan, pabrik biskuit legendaris resmi tutup" in t or "usai 92 tahun produksi biskuit, perusahaan malaysia ini" in t, "Pabrik Luar Negeri (Produsen Biskuit Malaysia Tutup)"),
    (lambda t: "industri keramik" in t, "Bukan Sektor Agro (Keramik IKFT)"),
    (lambda t: any(w in t for w in ["tambang", "menambang", "penambangan"]), "Bukan Sektor Agro (Pertambangan ESDM)"),
    (lambda t: "esdm dalami kebun sawit" in t or "esdm siapkan" in t, "Bukan Sektor Agro (Pertambangan ESDM)"),
    (lambda t: "komisi xii dpr" in t or "dirjen ebtke" in t or "sektor energi dua tahun" in t, "Bukan Sektor Agro (ESDM Energi)"),
    (lambda t: "stuktur data" in t or t == "berita", "Artifact Kosong / Error Web"),
    (lambda t: "kementerian koordinator bidang perekonomian republik indonesia" in t, "Artifact Web Kemenko Perekonomian"),

    # 2. Hulu Perkebunan & Tanaman Pangan (Lahan, STDB, Peremajaan, Budidaya Kebun, Singkong Petani)
    (lambda t: "stdb kelapa sawit" in t, "Hulu Perkebunan (Surat Tanda Daftar Budidaya Kebun Sawit)"),
    (lambda t: "garap 200.000 hektare lahan" in t, "Hulu Perkebunan (Penyediaan Lahan Kebun Sawit)"),
    (lambda t: "dukungan perkebunan kelapa sesuai kebutuhan pekebun" in t, "Hulu Perkebunan (Verifikasi Fisik Kebun Kelapa Rakyat)"),
    (lambda t: "5 daerah penghasil sawit terbesar di kaltim" in t, "Hulu Perkebunan (Produksi Tandan Buah Segar Daerah)"),
    (lambda t: "pengaruh curah hujan terhadap produksi kelapa sawit" in t, "Hulu Perkebunan (Kajian Agronomi Curah Hujan Kebun)"),
    (lambda t: "kajian pemupukan di perkebunan" in t, "Hulu Perkebunan (Kajian Agronomi Pemupukan Kebun)"),
    (lambda t: "beras sumut surplus" in t, "Hulu Tanaman Pangan (Beras Kementan / Dinas Pertanian Daerah)"),
    (lambda t: "pemerintah mimika optimalkan lahan perkebunan" in t, "Hulu Perkebunan (Penyiapan Lahan Kebun Pemda Mimika)"),
    (lambda t: "standar harga" in t and "pembudidaya rumput laut" in t, "Hulu Budidaya (Harga Bahan Mentah Rumput Laut Pembudidaya)"),
    (lambda t: "usulkan harga minimal rp14.000" in t, "Hulu Budidaya (Harga Rumput Laut Mentah Tingkat Pembudidaya)"),
    (lambda t: "mencicipi buah kakao dari kebun" in t, "Hulu Perkebunan (Konsumsi Buah Kakao Segar di Kebun Warga)"),
    (lambda t: "pohon karet tua di boven digoel diarahkan untuk peremajaan" in t, "Hulu Perkebunan (Replanting / Peremajaan Pohon Karet Tua)"),
    (lambda t: "rdpu dengan dewan pimpinan pusat petani karet indonesia" in t, "Hulu Perkebunan (Aspirasi Petani Karet di Komisi IV DPR RI)"),
    (lambda t: "transfer teknologi pakistan untuk petani tembakau" in t, "Hulu Perkebunan (Budidaya Tanaman Tembakau Petani)"),
    (lambda t: "harga singkong di lampung melonjak tembus rekor" in t, "Hulu Pertanian (Harga Bahan Baku Mentah Singkong Petani)"),
    (lambda t: any(w in t for w in ["kebun bibit rumput laut", "rumah budidaya rumput laut", "rumah bibit rumput laut"]), "Hulu Budidaya (Bibit dan Tambak Rumput Laut)"),
    (lambda t: any(w in t for w in ["pembaruan bibit", "rumah bibit", "perbenihan kelapa", "budidaya tambak", "modelling budidaya", "rumah budidaya"]), "Hulu Budidaya / Bibit (KKP / Perbenihan Kebun)"),
    (lambda t: any(w in t for w in ["pembudi daya rumput", "pembudidaya rumput", "nelayan dan pembudi", "panen raya rumput"]), "Hulu Nelayan / Pembudidaya Rumput Laut"),
    (lambda t: "bantuan perikanan bukan untuk" in t or "pengecekan sarana dan prasarana" in t, "Hulu Bantuan Sarpras Perikanan KKP"),
    (lambda t: "ritual baremah" in t, "Hulu Perkebunan (Adat Ritual Peremajaan Kebun PTPN IV)"),
    (lambda t: "ikan patin" in t, "Hulu Budidaya Tambak (Ikan Patin)"),
    (lambda t: "komisi iv dpr ri - dalami potensi bungkil" in t, "Hulu Pertanian (Komisi IV DPR RI)"),
    (lambda t: "moratorium sawit" in t, "Ranah Kehutanan / Lingkungan (KLHK)"),
    (lambda t: "buletin informasi iklim" in t, "Klimatologi Kebun (BMKG)"),
    (lambda t: "petani swadaya di aceh" in t, "Penyuluhan Petani Swadaya Hulu"),
    (lambda t: "dprd lampung optimis harga singkong" in t, "Hulu Harga Panen Singkong Petani (DPRD)"),
    (lambda t: "siap jadi percontohan tata kelola perkebunan" in t or "jalankan psn sawit, agrinas palma" in t, "Penyelenggaraan Kebun Kelapa Sawit PSN"),
    (lambda t: "implementasi pembangunan kelapa sawit yang berkelanjutan" in t, "Artikel Teori Konseptual Pembangunan Sawit"),
    (lambda t: "angkutan cpo diatas 20 ton" in t or "pt sil tegaskan kepatuhan tonase" in t, "Kamtibmas Jalan Desa Tonase Truk Sawit"),

    # 3. Keluhan Petani Non-Tembakau (Kecuali Tembakau)
    (lambda t: "keluh" in t and any(c in t for c in ["sawit", "karet", "kakao", "kopi", "tebu", "singkong", "kelapa"]) and "tembakau" not in t, "Keluhan Petani Non-Tembakau (Hulu Pertanian/Perkebunan)"),

    # 4. Kriminal, Satwa, Bencana, Sembako Eceran
    (lambda t: any(w in t for w in ["tapir", "gajah", "monyet", "buaya", "satwa liar"]) and any(c in t for c in ["sawit", "kebun", "hutan"]), "Satwa Liar / Bencana Lingkungan"),
    (lambda t: any(w in t for w in ["pembunuhan", "perampokan", "alat kejahatan", "maling", "curat", "curas", "polres tangkap"]), "Kriminal Murni Non-Industri"),
    (lambda t: any(w in t for w in ["harga cabai", "harga beras di pasar", "harga daging di pasar", "pasar tradisional", "sembako pasar"]), "Harga Eceran Pasar Tradisional"),

    # 5. Teknis Administrasi Bea Cukai Daerah (izin NPPBKC satu perusahaan)
    (lambda t: "nppbkc" in t and any(w in t for w in ["terbitkan", "satu perusahaan", "layanan hanggar", "sosialisasi nppbkc"]), "Teknis Administrasi Bea Cukai Daerah (NPPBKC)"),

    # 6. Headline Memuat UMKM
    (lambda t: bool(re.search(r"\b(?:umkm|ukm)\b|\busaha\s+mikro\b", t, re.IGNORECASE)), "Headline Memuat UMKM"),

    # 7. Aksi Pendanaan Korporasi, Judul Entitas Tunggal, Resep, Promosi, Pelatihan Desa
    (lambda t: any(w in t for w in ["obligasi", "sukuk", "surat utang", "pefindo", "rights issue", "buyback saham"]), "Aksi Pendanaan Korporasi Murni (Bukan Operasional Pabrik)"),
    (lambda t: any(w in t for w in ["resep ", "cara membuat ", "cara memasak ", "tips memasak "]), "Resep / Tips Kuliner Rumah Tangga"),
    (lambda t: any(w in t for w in ["katalog promo", "promo jsm", "supermarket", "diskon jsm"]), "Promosi Ritel Supermarket"),
    (lambda t: any(w in t for w in ["kwt ", "kelompok wanita tani", "ibu-ibu pkk", "pelatihan ibu-ibu"]), "Pemberdayaan / Pelatihan Skala Desa"),
    (lambda t: "apa itu kertas tisu pulp kayu virgin" in t, "Iklan Katalog Produk Impor (Made-in-China)"),

    # 8. Riset Kampus, Lomba Siswa, Vokasi Sekolah
    (lambda t: "pimnas" in t or "tim unair" in t or "ekspedisi patriot ipb" in t or "tim undana" in t or "karsa nusa" in t or "umpwr" in t or "unkriswina" in t, "Riset / Lomba Mahasiswa Kampus"),
    (lambda t: "tep its kembangkan tepung beras" in t or "tep ui gali potensi" in t or "pmki 2026: itb hadirkan teknologi" in t, "Riset / Pengabdian Mahasiswa Kampus (ITS / UI / ITB)"),
    (lambda t: "hmp bdp unhas tingkatkan nilai ekonomi rumput laut" in t, "Kegiatan Mahasiswa / PKM Kampus (BDP Unhas)"),
    (lambda t: "dari kebun hingga produk cokelat, fakultas pertanian utu" in t, "Program Magang Mahasiswa Kampus UTU"),
    (lambda t: "teaching factory smkn 5 merauke" in t or "riset ai klasifikasi ampas sagu antar 2 siswa" in t or "mahasiswa feb unimal juara satu" in t, "Lomba Siswa / Sekolah"),
    (lambda t: "unand olah gambir jadi minuman dan kosmetik" in t, "Hilirisasi Riset Laboratorium Kampus (UNAND)"),

    # 9. Arsip Lama & Kata Bermakna Ganda
    (lambda t: any(w in t for w in ["perahu karet", "jam karet", "gelang karet", "celana karet"]), "Kata Bermakna Ganda (Karet Non-Agro)"),
    (lambda t: "kelapa gading" in t or "pantai kelapa" in t or "jalan kelapa" in t, "Kata Bermakna Ganda (Nama Lokasi Kelapa)"),
    (lambda t: "kakao entertainment" in t or "kakaotalk" in t, "Kata Bermakna Ganda (Kakao Media K-pop/Korea)"),
    (lambda t: "sagu warnai tarung tiga di jayapura" in t, "Event Budaya / Kuliner Daerah Papua"),
    (lambda t: "10 negara paling doyan mi instan" in t, "Listicle Konsumsi Mie Instan Global"),
    (lambda t: "kombes fredricukus dorong pemuda papua" in t or "michael yarisetouw ajak anak muda papua" in t, "Himbauan Kepolisian Kamtibmas Pemuda"),
    (lambda t: "reses di kupang barat, viktor laiskodat" in t, "Aspirasi Reses DPR Daerah (Kupang Barat)"),
    (lambda t: "kelapa muda naik kelas saat motogp mandalika" in t, "Kuliner Wisata Event Olahraga"),
    (lambda t: "kelapa sawit expo center 2026: dari kampung yang pernah" in t, "Ekonomi Warga Kampung Sawit (Bukan Industri)"),
    (lambda t: "kenalkan potensi industri kelapa sawit berkelanjutan kepada pelajar" in t or "kenalkan kebaikan sawit bagi peternak sapi" in t, "Sosialisasi Edukasi Pelajar / Pelatihan Peternak Sapi"),
    (lambda t: "berkah ekonomi atau kutukan ekologi" in t or "terobosan endy, maya, lutfi" in t, "Blog Opini UGC (Kompasiana)"),
    (lambda t: "kuncup putih di lereng detubapa" in t, "Feature Cerita Kebun Kopi Ende"),
    (lambda t: "menkop ri fasilitasi pengembangan kopi papua" in t, "Koperasi Daerah Pegunungan Papua"),
    (lambda t: "perajin batik tulis" in t or "lilin batik" in t or "batik sawit" in t or "smart batik" in t, "Kerajinan Batik Tulis UMKM"),
    (lambda t: "kisah inspiratif mama lidia mikan" in t, "Profil Human Interest Inspiratif UMKM Lokal"),
    (lambda t: "mengalir ke israel" in t, "Isu Geopolitik / Investigasi Ekspor Transit"),
]


def check_deterministic_rules(article: dict) -> str | None:
    """
    Mengecek apakah artikel terkena aturan deterministik buang (Pass 1).
    Mengembalikan alasan dibuang jika terkena, atau None jika lolos.
    """
    url = str(article.get("link") or article.get("Link Website") or "").strip()
    title = str(article.get("title") or article.get("Title") or "").strip()
    sumber_data = str(article.get("sumber_data") or article.get("Sumber Data") or "").strip()

    # Cek dokumen PDF
    if is_pdf_document(url=url, title=title, sumber_data=sumber_data):
        return "Dokumen PDF (Bukan Berita)"

    # Cek domain asing
    if is_foreign_noise_domain(url):
        return "Domain Luar Negeri Non-Relevan (.vn / noise)"

    t_lower = title.lower()

    for rule_fn, reason in DETERMINISTIC_RULES:
        try:
            if rule_fn(t_lower):
                return reason
        except Exception:
            continue

    return None


# ==============================================================================
# 4. SYSTEM PROMPTS UNTUK PASS 2 & AUDIT LOOP (PASS 3+)
# ==============================================================================
PASS2_SYSTEM_PROMPT = """PERAN
Kamu adalah classifier berita media monitoring untuk Direktorat Jenderal Industri Agro (Ditjen IA), Kementerian Perindustrian Republik Indonesia.
Tugasmu: menyaring berita hasil scraping agar HANYA memuat berita sektor HILIR Industri Agro (industri pengolahan/manufaktur), dan MEMBUANG berita hulu, non-agro, atau noise.

== DEFINISI BERITA YANG DIPERTAHANKAN (HILIR) ==
Berita harus fokus ke salah satu hal berikut:
1. Industri, manufaktur, atau pengolahan pabrik (pabrik, hilirisasi, kapasitas produksi, investasi industri, ekspansi fasilitas, utilisasi kapasitas).
2. Ekspor-impor produk olahan agro (CPO, produk turunan kelapa/sawit, mamin, hasil laut olahan, kakao olahan, furnitur, kertas/pulp, rokok/cerutu, dll).
3. Kebijakan Kemenperin atau pemerintah yang berdampak ke industri agro (termasuk wajib halal, SNI, kemasan makanan, neraca komoditas, insentif industri, pasokan bahan baku industri seperti gula rafinasi).
4. Kinerja ekonomi sektor industri agro: makanan dan minuman (mamin), minyak sawit/CPO olahan, hasil tembakau/vape/IHT, kayu/furnitur/mebel, kertas/pulp, hasil laut olahan, kopi, kakao, gula, susu, atsiri, karet olahan/ban.

== YANG HARUS DIBUANG (BUKAN_HILIR) ==
1. Hulu pertanian atau perkebunan: luas lahan, pembukaan lahan, HGU, benih, bibit, tanam, panen raya mentah, produksi mentah kebun, agronomi/pemupukan, harga bahan baku di tingkat petani/kebun, program budidaya Kementan/dinas pertanian.
2. Keluhan petani, KECUALI keluhan petani tembakau (keluhan petani tembakau terkait serapan pabrik rokok TETAP DIPERTAHANKAN).
3. Kriminal murni, satwa liar di kebun, bencana alam, atau harga eceran sembako di pasar tradisional.
4. Teknis administrasi Bea Cukai lokal (izin NPPBKC satu perusahaan).
5. Headline yang memuat UMKM/UKM/Usaha Mikro (Ditjen Agro membina industri manufaktur menengah-besar).
6. Aksi pendanaan korporasi murni (obligasi, sukuk, rights issue, rating utang Pefindo), judul nama entitas saja, resep masakan, promosi supermarket, pelatihan ibu-ibu/KWT desa.
7. Berita Kemenperin yang bukan sektor agro (galangan kapal, tenun, otomotif/hybrid/EV, baja skrap).
8. Arsip lama, berita penutupan pabrik di luar negeri, dan kata bermakna ganda (perahu karet, jam karet, Kelapa Gading, Kakao Entertainment).

== KLASIFIKASI LABEL ==
- "HILIR": Jelas masuk ranah hilir manufaktur/pengolahan/kebijakan Ditjen Industri Agro.
- "BUKAN_HILIR": Masuk ranah hulu pertanian, non-agro, kriminal, promosi, atau noise yang harus dibuang.
- "RAGU": Ambigu atau berpotensi menyangkut industri agro namun butuh verifikasi manusia.

Wajib baca konteks keseluruhan judul dan cuplikan teks artikel, jangan hanya menilai dari satu kata kunci.
FORMAT OUTPUT (HARUS JSON MURNI TANPA MARKDOWN / BACKTICKS):
[
  {
    "id": <id_artikel>,
    "label": "HILIR" | "BUKAN_HILIR" | "RAGU",
    "alasan": "<satu kalimat singkat alasan klasifikasi>"
  }
]
"""

AUDIT_SYSTEM_PROMPT = """PERAN: AUDITOR KETAT MEDIA MONITORING DITJEN INDUSTRI AGRO (KEMENPERIN).
Kamu menerima daftar artikel yang sebelumnya lolos seleksi sebagai kandidat HILIR.
TUGASMU: LAKUKAN AUDIT KETAT (DEVIL'S ADVOCATE). CARILAH ALASAN UNTUK MEMBUANG ARTIKEL INI!

Ajukan pertanyaan kritis untuk setiap artikel:
1. Apakah artikel ini sebenarnya ranah hulu (perkebunan petani mentah, budidaya tambak, bibit, harga TBS/singkong/karet di petani, bukan pengolahan pabrik)?
2. Apakah ini sektor non-agro (otomotif, baterai/EV, maritim kapal, logam baja, tambang batubara/migas ESDM, festival musik)?
3. Apakah ini pabrik luar negeri (contoh: produsen biskuit di Malaysia tutup) atau isu luar negeri tanpa dampak bagi industri Indonesia?
4. Apakah ini hanya riset mahasiswa/kampus skala laboratorium, pengabdian desa pesisir, atau promosi kerajinan tanpa skala industri manufaktur?
5. Apakah ini hanya aksi pendanaan korporasi murni (surat utang/obligasi) tanpa membahas operasional industri?

ATURAN KELULUSAN AUDIT:
- Artikel TETAP "HILIR" HANYA JIKA kamu TIDAK MENEMUKAN alasan kuat untuk membuangnya (benar-benar terbukti industri manufaktur, pabrik, hilirisasi, ekspor-impor olahan agro, atau kebijakan Kemenperin industri agro).
- Jika kamu menemukan alasan kuat bahwa artikel ini hulu atau non-agro atau noise, ubah labelnya menjadi "BUKAN_HILIR" dan sebutkan alasannya.
- Jika informasinya sangat ambigu atau borderline, tandai "RAGU".

Wajib grounded: alasan harus berbasis isi teks artikel asli, jangan mengarang.
FORMAT OUTPUT (HARUS JSON MURNI TANPA MARKDOWN / BACKTICKS):
[
  {
    "id": <id_artikel>,
    "label": "HILIR" | "BUKAN_HILIR" | "RAGU",
    "alasan": "<satu kalimat alasan audit>"
  }
]
"""


# ==============================================================================
# 5. FUNGSI INTI PIPELINE AUTO CEK ULANG
# ==============================================================================
class AutoRecheckPipeline:
    def __init__(self, target_dir: str = "hasil_scrapping"):
        self.target_dir = target_dir
        self.cache = RecheckCache()
        self.discarded_log = []

    def run_pass_1_deterministic(self, articles: list[dict]) -> tuple[list[dict], list[dict]]:
        """Pass 1: Menjalankan aturan pasti."""
        kept = []
        discarded = []

        for idx, art in enumerate(articles, start=1):
            title = str(art.get("title") or art.get("Title") or "").strip()
            link = str(art.get("link") or art.get("Link Website") or "").strip()
            reason = check_deterministic_rules(art)

            if reason:
                discarded.append({
                    "judul": title,
                    "link": link,
                    "alasan": reason,
                    "pass": 1
                })
            else:
                art["_recheck_id"] = idx
                kept.append(art)

        return kept, discarded

    def _call_ai_batch(self, batch: list[dict], system_prompt: str, pass_name: str) -> list[dict]:
        """Memanggil Gemini AI untuk batch artikel dengan caching dan fallback pool."""
        results = []
        uncached = []

        # 1. Cek Cache
        for art in batch:
            title = str(art.get("title") or art.get("Title") or "").strip()
            snip = str(art.get("text") or art.get("text_snippet") or art.get("snippet") or "")[:500].strip()
            cached_val = self.cache.get(title, snip, pass_name)
            if cached_val:
                res_item = dict(cached_val)
                res_item["id"] = art["_recheck_id"]
                results.append(res_item)
            else:
                uncached.append(art)

        if not uncached:
            return results

        # 2. Siapkan Payload untuk artikel yang belum ada di cache
        payload_items = []
        for art in uncached:
            snip = str(art.get("text") or art.get("text_snippet") or art.get("snippet") or "")[:500].strip()
            item = {
                "id": art["_recheck_id"],
                "title": str(art.get("title") or art.get("Title") or "").strip(),
            }
            media = str(art.get("media_name") or art.get("Media Name") or "").strip()
            if media:
                item["media"] = media
            if snip:
                item["snippet"] = snip
            payload_items.append(item)

        user_content = f"Daftar berita untuk dinilai (total {len(payload_items)}):\n{json.dumps(payload_items, ensure_ascii=False, indent=2)}"
        full_prompt = f"{system_prompt}\n\n{user_content}"

        # 3. Eksekusi dengan retry dan fallback model pool
        max_attempts = 3
        ai_resp_data = None

        for attempt in range(max_attempts):
            model = _get_gemini_model()
            if model is None:
                break
            try:
                resp = model.generate_content(full_prompt, request_options={"retry": None, "timeout": 45})  # type: ignore
                text = (resp.text or "").strip()

                # Parse JSON
                m = re.search(r"\[[\s\S]*\]", text)
                if m:
                    ai_resp_data = json.loads(m.group(0))
                    break
                else:
                    m2 = re.search(r"\{[\s\S]*\}", text)
                    if m2:
                        parsed = json.loads(m2.group(0))
                        ai_resp_data = parsed.get("hasil") or parsed.get("articles") or [parsed]
                        break
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str:
                    print(f"    [AI LIMIT] Kuota model limit, beralih ke model berikutnya di pool...", flush=True)
                    _get_gemini_model(force_next=True)
                    time.sleep(1.0)
                    continue
                else:
                    print(f"    [AI ERROR] {e}. Mencoba beralih model...", flush=True)
                    _get_gemini_model(force_next=True)
                    time.sleep(1.5)
                    continue

        # 4. Petakan hasil respon AI ke uncached items
        resp_map = {}
        if ai_resp_data and isinstance(ai_resp_data, list):
            for r in ai_resp_data:
                if isinstance(r, dict) and "id" in r:
                    resp_map[r["id"]] = r

        for art in uncached:
            art_id = art["_recheck_id"]
            title = str(art.get("title") or art.get("Title") or "").strip()
            snip = str(art.get("text") or art.get("text_snippet") or art.get("snippet") or "")[:500].strip()

            val = resp_map.get(art_id)
            if val is None and str(art_id) in resp_map:
                val = resp_map[str(art_id)]

            if val:
                label = str(val.get("label", "HILIR")).strip().upper()
                if label not in ["HILIR", "BUKAN_HILIR", "RAGU"]:
                    label = "RAGU"
                alasan = str(val.get("alasan", "Dinilai oleh AI")).strip()
            else:
                # Fallback aman jika respon tidak lengkap: RAGU (jangan langsung buang)
                label = "RAGU"
                alasan = "Respon AI tidak memuat ID artikel (Perlu verifikasi manual)"

            res_entry = {
                "id": art_id,
                "label": label,
                "alasan": alasan
            }
            results.append(res_entry)

            # Simpan ke cache jika AI berhasil mengevaluasi
            if val:
                self.cache.set(title, snip, pass_name, res_entry)

        return results

    def run_pass_2_ai(self, articles: list[dict], batch_size: int = 15) -> tuple[list[dict], list[dict]]:
        """Pass 2: Mengirim seluruh artikel lolos Pass 1 ke AI batch classifier."""
        print(f"\n[PASS 2] Mengirim {len(articles)} artikel ke AI Relevance Classifier (Batch {batch_size})...", flush=True)
        kept = []
        discarded = []

        all_ai_results = {}
        for i in range(0, len(articles), batch_size):
            batch = articles[i : i + batch_size]
            b_idx = (i // batch_size) + 1
            b_tot = (len(articles) + batch_size - 1) // batch_size
            print(f"  -> Memproses Batch {b_idx}/{b_tot} ({len(batch)} artikel)...", flush=True)

            batch_res = self._call_ai_batch(batch, PASS2_SYSTEM_PROMPT, pass_name="pass2_relevance")
            for r in batch_res:
                all_ai_results[r["id"]] = r
            time.sleep(1.0)

        self.cache.save()

        for art in articles:
            art_id = art["_recheck_id"]
            ai_eval = all_ai_results.get(art_id, {"label": "RAGU", "alasan": "Evaluasi AI terlewat"})
            label = ai_eval.get("label", "HILIR")
            alasan = ai_eval.get("alasan", "")

            art["_pass2_label"] = label
            art["_pass2_alasan"] = alasan

            title = str(art.get("title") or art.get("Title") or "").strip()
            link = str(art.get("link") or art.get("Link Website") or "").strip()

            if label == "BUKAN_HILIR":
                discarded.append({
                    "judul": title,
                    "link": link,
                    "alasan": f"AI Pass 2 (Bukan Hilir): {alasan}",
                    "pass": 2
                })
            else:
                # HILIR atau RAGU dipertahankan untuk diaudit di Pass 3+
                kept.append(art)

        print(f"  [PASS 2 SELESAI] Lolos: {len(kept)} artikel (HILIR/RAGU) | Dibuang: {len(discarded)} artikel", flush=True)
        return kept, discarded

    def run_audit_loop(
        self,
        articles: list[dict],
        max_audit_passes: int = 4,
        batch_size: int = 15
    ) -> tuple[list[dict], list[dict], dict[int, int]]:
        """
        Pass 3 dan seterusnya: Audit loop ketat (devil's advocate).
        Hanya mengaudit artikel HILIR dan RAGU.
        Berhenti saat tidak ada artikel dibuang (konvergen) atau batas putaran tercapai.
        """
        print(f"\n[PASS 3+] Memulai Audit Loop Ketat (Maksimal {max_audit_passes} putaran audit)...", flush=True)

        current_candidates = list(articles)
        all_audit_discarded = []
        discarded_by_pass = {}

        for audit_round in range(1, max_audit_passes + 1):
            pass_num = audit_round + 2  # Pass 3, Pass 4, Pass 5, Pass 6
            pass_key = f"audit_round_{audit_round}"

            print(f"\n  [AUDIT PUTARAN {audit_round} / PASS {pass_num}] Mengaudit {len(current_candidates)} artikel...", flush=True)

            all_evals = {}
            for i in range(0, len(current_candidates), batch_size):
                batch = current_candidates[i : i + batch_size]
                b_res = self._call_ai_batch(batch, AUDIT_SYSTEM_PROMPT, pass_name=pass_key)
                for r in b_res:
                    all_evals[r["id"]] = r
                time.sleep(1.0)

            self.cache.save()

            round_kept = []
            round_discarded = []

            for art in current_candidates:
                art_id = art["_recheck_id"]
                ai_eval = all_evals.get(art_id, {"label": "RAGU", "alasan": "Audit AI terlewat"})
                label = ai_eval.get("label", "HILIR")
                alasan = ai_eval.get("alasan", "")

                art[f"_pass{pass_num}_label"] = label
                art[f"_pass{pass_num}_alasan"] = alasan
                art["_final_label"] = label
                art["_final_alasan"] = alasan

                title = str(art.get("title") or art.get("Title") or "").strip()
                link = str(art.get("link") or art.get("Link Website") or "").strip()

                if label == "BUKAN_HILIR":
                    round_discarded.append({
                        "judul": title,
                        "link": link,
                        "alasan": f"Audit Pass {pass_num}: {alasan}",
                        "pass": pass_num
                    })
                else:
                    round_kept.append(art)

            discarded_by_pass[pass_num] = len(round_discarded)
            all_audit_discarded.extend(round_discarded)
            current_candidates = round_kept

            print(f"  [HASIL PUTARAN {audit_round}] Dibuang: {len(round_discarded)} artikel | Tersisa: {len(current_candidates)} artikel", flush=True)

            # Cek kondisi konvergensi
            if len(round_discarded) == 0:
                print(f"  [KONVERGEN] Tidak ada artikel yang dibuang pada Putaran {audit_round}. Audit selesai lebih cepat!", flush=True)
                break

        return current_candidates, all_audit_discarded, discarded_by_pass

    def run(self, raw_articles: list[dict], target_dir: str | None = None) -> tuple[list[dict], list[dict]]:
        """
        Menjalankan seluruh alur Auto Cek Ulang:
        Pass 1 -> Pass 2 -> Pass 3+ (Audit Loop) -> Finalisasi RAGU -> Laporan.
        """
        if target_dir:
            self.target_dir = target_dir

        total_initial = len(raw_articles)
        print("=" * 80)
        print("TAHAP 'AUTO CEK ULANG' SEKTOR HILIR INDUSTRI AGRO (KEMENPERIN)")
        print(f"Total Artikel Masuk Evaluasi: {total_initial}")
        print("=" * 80)

        # 1. Pass 1 (Aturan Pasti)
        p1_kept, p1_discarded = self.run_pass_1_deterministic(raw_articles)
        print(f"[PASS 1 SELESAI] Lolos Aturan Pasti: {len(p1_kept)} | Dibuang: {len(p1_discarded)}")

        # 2. Pass 2 (AI Batch Classifier)
        p2_kept, p2_discarded = self.run_pass_2_ai(p1_kept, batch_size=15)

        # 3. Pass 3+ (Audit Loop)
        final_kept, audit_discarded, audit_counts = self.run_audit_loop(p2_kept, max_audit_passes=4, batch_size=15)

        # Kumpulkan semua artikel yang dibuang
        all_discarded = p1_discarded + p2_discarded + audit_discarded
        self.discarded_log = all_discarded

        # 4. Finalisasi Artikel RAGU (Jangan Dibuang, Beri Flag PERLU CEK MANUAL)
        ragu_count = 0
        hilir_count = 0

        for art in final_kept:
            final_lbl = art.get("_final_label", "HILIR")
            final_als = art.get("_final_alasan", "")

            if final_lbl == "RAGU":
                ragu_count += 1
                art["Status Review"] = f"PERLU CEK MANUAL: {final_als}" if final_als else "PERLU CEK MANUAL"
            else:
                hilir_count += 1
                # Jika sebelumnya kosong atau bukan review khusus, kosongkan status review
                curr_sr = str(art.get("Status Review") or "").strip()
                if "perlu cek manual" in curr_sr.lower():
                    art["Status Review"] = ""

        # 5. Simpan Log Artikel yang Dibuang
        discard_json_path = os.path.join(self.target_dir, "discarded_articles.json")
        try:
            os.makedirs(self.target_dir, exist_ok=True)
            with open(discard_json_path, "w", encoding="utf-8") as f:
                json.dump(all_discarded, f, ensure_ascii=False, indent=2)
            print(f"\n[DATA SAFETY] Seluruh {len(all_discarded)} artikel dibuang dicatat di: {discard_json_path}")
        except Exception as e:
            print(f"[WARNING] Gagal menulis discarded_articles.json: {e}")

        # 6. Cetak Laporan Singkat Akhir
        self._print_final_report(
            total_initial=total_initial,
            p1_count=len(p1_discarded),
            p2_count=len(p2_discarded),
            audit_counts=audit_counts,
            final_kept=final_kept,
            ragu_count=ragu_count,
            hilir_count=hilir_count,
            all_discarded=all_discarded
        )

        return final_kept, all_discarded

    def _print_final_report(
        self,
        total_initial: int,
        p1_count: int,
        p2_count: int,
        audit_counts: dict[int, int],
        final_kept: list[dict],
        ragu_count: int,
        hilir_count: int,
        all_discarded: list[dict]
    ):
        """Mencetak laporan akhir proses auto cek ulang dan analisis 5 artikel acak."""
        print("\n" + "=" * 80)
        print("LAPORAN AKHIR TAHAP 'AUTO CEK ULANG' SEKTOR HILIR INDUSTRI AGRO")
        print("=" * 80)
        print(f"1. Jumlah Artikel Awal                    : {total_initial} artikel")
        print(f"2. Rincian Dibuang per Pass:")
        print(f"   - Pass 1 (Aturan Pasti / Domain / Hulu): {p1_count} artikel")
        print(f"   - Pass 2 (AI Batch Classifier)         : {p2_count} artikel")
        for p_num, cnt in audit_counts.items():
            print(f"   - Pass {p_num} (Audit Putaran {p_num - 2})           : {cnt} artikel")
        print(f"   --------------------------------------------------------")
        print(f"   Total Artikel Dibuang                  : {len(all_discarded)} artikel")
        print(f"3. Jumlah Artikel Tersisa (Final)         : {len(final_kept)} artikel")
        print(f"   - Berstatus HILIR (Pasti)              : {hilir_count} artikel")
        print(f"   - Berstatus RAGU (PERLU CEK MANUAL)    : {ragu_count} artikel")
        print("=" * 80)

        # Analisis 5 Artikel Acak (campuran lolos dan dibuang)
        print("\nANALISIS 5 ARTIKEL ACAK (VALIDASI KEPUTUSAN AUTO CEK ULANG):")
        print("-" * 80)

        sample_pool = []
        for a in final_kept:
            title = str(a.get("title") or a.get("Title") or "").strip()
            lbl = "RAGU" if "perlu cek manual" in str(a.get("Status Review", "")).lower() else "HILIR"
            als = a.get("_final_alasan") or a.get("_pass2_alasan") or "Sektor industri manufaktur agro"
            sample_pool.append((lbl, title, als))

        for d in all_discarded:
            title = str(d.get("judul") or "").strip()
            als = str(d.get("alasan") or "")
            p = d.get("pass", 1)
            sample_pool.append((f"BUKAN_HILIR (Pass {p})", title, als))

        random.seed(42)  # Deterministic seed for reproducible reporting
        selected_samples = random.sample(sample_pool, min(5, len(sample_pool)))

        for i, (status, title, reason) in enumerate(selected_samples, start=1):
            print(f"[{i}] [{status}]")
            print(f"    Judul : {title}")
            print(f"    Alasan: {reason}")
            print("-" * 80)


def run_auto_recheck(articles: list[dict], target_dir: str = "hasil_scrapping") -> tuple[list[dict], list[dict]]:
    """Fungsi pembungkus sederhana untuk dipanggil dari main.py atau script eksternal."""
    pipeline = AutoRecheckPipeline(target_dir=target_dir)
    return pipeline.run(articles, target_dir=target_dir)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Jalankan Auto Cek Ulang pada file Excel atau folder hasil scrapping.")
    parser.add_argument("--file", type=str, default=None, help="Path ke file Excel yang akan dicek ulang")
    parser.add_argument("--dir", type=str, default=None, help="Folder hasil scrapping (berisi file Excel dan progress.json)")
    args = parser.parse_args()

    target_file = args.file
    target_folder = args.dir or "hasil_scrapping"

    if target_file and os.path.exists(target_file):
        import pandas as pd
        df = pd.read_excel(target_file, sheet_name="Berita")
        records = df.to_dict(orient="records")
        kept, disc = run_auto_recheck(records, target_dir=os.path.dirname(target_file))
    else:
        print("Gunakan argumen --file <path_excel> untuk menjalankan Auto Cek Ulang pada file tertentu.")
