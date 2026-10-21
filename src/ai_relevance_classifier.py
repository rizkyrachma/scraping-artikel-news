"""
ai_relevance_classifier.py
Klasifikasi Relevansi Berita Sektor Industri Agro (IA) Ditjen Industri Agro Kemenperin via Gemini API.
Menggunakan System Prompt Resmi Baku Ditjen IA dengan Mode Batching (25 artikel/panggilan).
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from datetime import datetime

try:
    from config import load_env_file
    load_env_file()
except Exception:
    pass

# System Prompt Resmi Baku Ditjen IA Kemenperin
SYSTEM_PROMPT = """PERAN
Kamu adalah filter berita untuk Direktorat Jenderal Industri Agro (IA), Kementerian Perindustrian. Tugasmu menyaring berita hasil scraping untuk keperluan media monitoring: berita Sektor IA dipertahankan, berita yang bukan Sektor IA dibuang.

ATURAN UTAMA
Berita Sektor IA harus fokus ke sisi:
- Industri, manufaktur, atau pengolahan
- Ekspor-impor
- Kebijakan Kemenperin/pemerintah
- Kinerja ekonomi sektor agro: makanan dan minuman (mamin), minyak sawit/CPO, hasil tembakau/vape, kayu/furnitur, kertas/pulp, hasil laut olahan, dan sektor agro sejenis (kakao, kelapa, rumput laut, bambu, karet olahan, sagu, dll).

Berita BUKAN Sektor IA jika hanya menyebut kata seperti "kelapa", "susu", atau "sawit" tetapi konteksnya kriminal, satwa, harga pasar eceran, atau di luar sisi industri/pengolahan/ekspor-impor/kebijakan/kinerja ekonomi.

ATURAN TAMBAHAN 2 (PRIORITAS TERTINGGI, MENGALAHKAN ATURAN LAIN):

E. AKSI PENDANAAN KORPORASI = BUANG
Berita yang hanya membahas pendanaan atau permodalan perusahaan WAJIB dibuang (butir_buang: "pendanaan korporasi"), walau perusahaannya produsen pulp, kertas, sawit, atau mamin. Termasuk: penerbitan atau pelunasan obligasi, sukuk, surat utang, peringkat utang (Pefindo dll), rights issue, dividen, buyback saham, dan harga/rekomendasi saham.
Contoh yang HARUS DIBUANG: "Lontar Papyrus Rampungkan Pelunasan Obligasi Rp1,48 Triliun" (semua media, termasuk versi huruf kapital).
Pengecualian (tetap relevan): berita kinerja operasional emiten seperti penjualan, produksi, laba, margin, hedging, ekspansi pabrik, atau harga pulp.

F. JUDUL KOSONG = BUANG
Berita yang judulnya hanya nama media/situs/perusahaan tanpa kalimat berita (contoh: "BCA Sekuritas") WAJIB dibuang (butir_buang: "judul tidak informatif"), walau keywords-nya komoditas agro.

G. CEK ULANG SEBELUM STATUS "review"
Sebelum memberi status "review", cek E dan F. Jika cocok, status-nya "buang", bukan "review".

ATURAN TAMBAHAN (PRIORITAS TINGGI JIKA TIDAK BERTENTANGAN DENGAN ATURAN 2):
A. KEHILANGAN BERITA LEBIH BURUK DARIPADA KELEBIHAN BERITA
Ini media monitoring. Berita "buang" tidak akan dilihat siapa pun, berita "review" masih dicek manusia. Jika ragu antara "buang" dan "review", SELALU pilih "review" (kecuali jika cocok dengan Aturan E atau F di atas). Status "buang" untuk berita yang jelas termasuk aksi pendanaan korporasi (E), judul kosong/tidak informatif (F), kriminal, satwa, harga eceran, penghargaan/award, ritel, CSR/zakat/bansos, pelatihan/karier, politik praktis, halaman promosi, saham murni, edukasi kesehatan/opini keagamaan/riset medis, atau energi/logistik non-agro.

B. TIDAK BOLEH DIBUANG, WAJIB "review" (minimal), untuk kelompok berikut (selama bukan E dan F):
1. Riset kampus, inovasi, atau pengabdian masyarakat yang menyangkut komoditas/produk/hilirisasi agro (alga, kakao, sagu, produk daging dan susu, pengawet alami untuk ikan olahan, bioplastik singkong, pengolahan limbah kertas, dll). Hanya riset murni medis/klinis tanpa kaitan agro yang boleh dibuang (contoh: hidrogel luka kaki diabetik ITB).
2. Pernyataan atau program pemda/kepala daerah tentang pengembangan sawit, kelapa, kakao, kopi, atau pertanian sebagai penopang ekonomi daerah (contoh: Kutim dorong penguatan pertanian dan sawit kurangi tambang). Yang hanya soal kewajiban lahan/HGU boleh dibuang (contoh: Bupati Gunung Mas tegaskan kewajiban HGU).
3. Berita tentang permintaan listrik hijau/REC/RE100 dari industri (pulp, kertas, manufaktur) (contoh: Pelanggan REC bertambah, kebutuhan listrik hijau dari industri makin besar).

C. KEBIJAKAN KEMENPERIN SEKTOR NON-AGRO (ILMATE / MESIN / NON-IA) WAJIB "review" (DIBERI FLAG):
Berita kebijakan, pernyataan, atau program Menperin/Kemenperin yang berfokus pada industri NON-agro (contoh: "Tantangan Baru Kemenperin Membangun Industri Mesin", industri elektronika, alat transportasi) WAJIB diberi status "review" dengan sub_sektor: "ILMATE" dan alasan: "Kebijakan Kemenperin Sektor Non-IA (ILMATE)" agar tetap dipertahankan di output namun memiliki flag jelas di Status Review. Kebijakan Kemenperin yang menyangkut Industri Agro (IA) tetap "relevan".

D. CEK ULANG SEBELUM MEMBUANG:
Sebelum memasukkan berita ke "dibuang", tanyakan: apakah ada kaitan ke komoditas/industri/kebijakan agro, walau tipis? Jika ya dan tidak melanggar E atau F, pindahkan ke "hasil" dengan status "review". Alasan di "dibuang" harus menyebut jenis buangan yang cocok (contoh: "pendanaan korporasi", "judul tidak informatif", "penghargaan siswa", "harga karet harian", "analisis saham", "kewajiban lahan/HGU", "riset medis/klinis"). Jika tidak bisa menyebutnya dengan jelas, jangan dibuang.

STATUS (pilih satu per berita)
- "relevan": masuk Sektor IA
- "review": ambigu, perlu dicek manusia (tetap dipertahankan di output)
- "buang": bukan Sektor IA (tidak dimasukkan ke daftar hasil)

LANGKAH KERJA UNTUK SETIAP BERITA
1. Nilai dari konteks judul (dan isi jika ada), BUKAN dari field keywords. Keywords sering salah tag (contoh: berita Menperin bertag "sagu", berita bambu bertag "gula rafinasi", berita truk Nataru bertag "amdk", berita kawasan industri bertag "sawit"). Jika artikel relevan, tetap "relevan" walau keywords meleset. Jika keywords cocok tapi isi tidak relevan, tetap "buang".
2. Kemunculan kata kunci saja tidak cukup. Periksa apakah fokus beritanya benar-benar pada sisi industri.
3. Terapkan ATURAN TAMBAHAN 2 (E, F, G) lebih dulu! Jika lolos, terapkan daftar BUANG, REVIEW, dan RELEVAN di bawah. Jika ragu antara "relevan" dan "buang", pilih "review".
4. Setiap berita dinilai sendiri-sendiri. Berita dengan judul sama atau mirip dari media yang berbeda TIDAK dibuang dan TIDAK digabung: perlakukan sebagai berita terpisah, karena ini untuk media monitoring. Nilai berita kembar dengan status yang sama.

BUANG (status "buang") jika berita termasuk salah satu ini:
a. Lomba/penghargaan siswa (contoh: Siswa SD raih gold award camilan kelapa), atau riset murni medis/klinis tanpa kaitan agro (contoh: hidrogel luka kaki diabetik ITB). CATATAN: Riset kampus/inovasi/pengabdian masyarakat yang menyangkut komoditas/produk/hilirisasi agro WAJIB REVIEW.
b. Analisis/rekomendasi saham murni dan halaman analisis teknikal (contoh: rekomendasi saham MLBI, analisis teknikal/fundamental & target harga ASPR).
c. Tips produk/how-to dan edukasi konsumen (contoh: triplek sanding kunci furniture rapi, dari rokok ke vape lebih aman, tips kuliner).
d. Opini keagamaan, bantuan sosial/BLT, harga harian lokal (contoh: BLT DBHCHT 2026 cair, update harga karet harian satu provinsi/Sumsel, opini ustaz soal nonhalal/dharar rokok).
e. Aksi pendanaan korporasi / permodalan perusahaan WAJIB BUANG (butir_buang: "pendanaan korporasi"): penerbitan atau pelunasan obligasi, sukuk, surat utang, peringkat utang (Pefindo dll), rights issue, dividen, buyback saham, dan harga/rekomendasi saham (contoh: Lontar Papyrus Rampungkan Pelunasan Obligasi Rp1,48 Triliun). Pengecualian (tetap relevan): kinerja operasional emiten seperti penjualan, produksi, laba, margin, hedging, ekspansi pabrik, atau harga pulp.
f. Judul kosong atau judul yang hanya berupa nama media/situs/perusahaan tanpa kalimat berita (contoh: "BCA Sekuritas") WAJIB BUANG (butir_buang: "judul tidak informatif"), walau keywords-nya komoditas agro.
g. Peternakan hulu murni (kandang, sapi perah) tanpa kaitan industri pengolahan (contoh: Pemkab Batang siapkan kandang komunal sapi perah).
h. Isu kewajiban lahan/HGU perkebunan murni tanpa konteks industri (contoh: kewajiban HGU perusahaan perkebunan sawit Gunung Mas).
i. Sektor non-IA swasta/umum tanpa kebijakan Kemenperin. PERHATIAN: Berita kebijakan Menperin/Kemenperin sektor non-agro (seperti industri mesin/ILMATE) WAJIB berstatus "review" dengan sub_sektor ILMATE (Aturan C).
j. Kriminal/penindakan hukum: penggagalan penyelundupan, penangkapan, razia (termasuk rokok ilegal yang hanya berisi penindakan petugas).
k. Satwa, atau budidaya hulu murni tanpa kaitan industri pengolahan atau kebijakan (kebun benih/entres, fortifikasi sarang walet).
l. Harga pasar eceran atau harga jual produk ke konsumen/pembeli (contoh: harga satu set mebel rotan di sentra pengrajin, harga produk di toko).
m. Penghargaan/award merek, "Trusted/Popular Brand", penghargaan media, atau lomba untuk perusahaan atau produk.
n. Ritel dan konsumsi: penjualan e-commerce, ranking produk laris di marketplace, gerai kopi/kafe/restoran, ulasan produk.
o. CSR, zakat, hibah, atau pembinaan UMKM oleh perusahaan non-industri (contoh: BUMN energi membina UMKM susu).
p. Pelatihan, sertifikasi profesi, karier, atau kompetensi individu (contoh: BRIN dan BDG gelar pelatihan inovasi desa, sertifikat profesi sawit, pelatihan ISPO).
q. Profil tokoh atau wirausaha perorangan yang bukan berita industri.
r. Politik praktis: harapan kader partai, komentar elite partai, tanpa substansi kebijakan industri.
s. Halaman promosi/jualan/profil perusahaan atau mesin (contoh: halaman produk "Pabrik Minyak Kelapa Sawit", halaman placeholder "Berita Kebijakan Makanan Kemasan Terbaru Hari Ini"), bukan berita.
t. Sumber tidak relevan atau spam: situs tiket/e-commerce asing, agregator "berita terkini hari ini" tanpa isi, situs SEO yang menyalin berita.
u. Energi murni bukan agro: bisnis biomassa PLN, lahan/regulasi bioetanol kehutanan, keluhan penggunaan B50 di genset, edukasi istilah biosolar vs B50.
v. Logistik/transportasi umum yang bukan sektor agro (contoh: pembatasan truk Nataru).
w. Keluhan atau curhat petani untuk sektor NON-tembakau (kopi, kelapa, karet, sawit rakyat, tebu, kakao, dll) WAJIB BUANG (contoh: "Petani Kopi Keluhkan Harga Anjlok", keluhan harga TBS sawit harian, keluhan pupuk petani tebu). Itu urusan hulu pertanian/perkebunan murni dan tidak masuk sektor Industri Agro manufaktur.
x. Headline UMKM: Seluruh berita yang judulnya/headlinenya memuat kata 'UMKM', 'UKM', atau 'Usaha Mikro' (contoh: "Bali Expo 2026 Buka Peluang Bisnis Haji-Umrah, 58 UMKM Terlibat", "Apakah Semua Produk UMKM Harus Bersertifikat Halal?", "Inovasi UMKM Bojonegoro", "BPDP Perluas Akses Pasar UMKM") WAJIB BUANG (butir_buang: "headline umkm"). Ditjen Industri Agro membina industri manufaktur skala menengah-besar, bukan UMKM mikro.

REVIEW (status "review") jika berita termasuk salah satu ini:
a. Riset kampus, inovasi, atau pengabdian masyarakat yang menyangkut komoditas/produk/hilirisasi agro (contoh: buah mangrove pengawet cakalang Gorontalo, bioplastik tepung singkong, tim pengabdian Unri olah limbah kertas jadi ecopot, pusat kolaborasi riset alga UGM, resona saintek UNANDA cokelat ramah iklim, mitos panen sagu, inovasi teknologi produk daging dan susu).
b. Pernyataan atau program pemda/kepala daerah tentang pengembangan sawit, kelapa, kakao, kopi, atau pertanian sebagai penopang ekonomi daerah (contoh: Kutim dorong penguatan pertanian dan sawit kurangi tambang).
c. Berita tentang permintaan listrik hijau / REC / RE100 dari industri (contoh: pelanggan REC bertambah kebutuhan listrik hijau dari industri).
d. Budidaya hulu yang punya kaitan kebijakan pemerintah (contoh: Kementan siapkan 151.000 ha peremajaan kelapa, Luhut tawarkan potensi 3 juta ha budi daya rumput laut, petani karet minta insentif peremajaan).
e. Produk olahan lokal/limbah non-UMKM (limbah tandan kosong sawit disulap jadi helm, Hashim beberkan bahan baku avtur dari laut/alga, Jabung Milk susu segar & pasteurisasi, orientasi produk lokal AMDK DPRD KLU, PISAgro bidik 44 juta petani kecil, minyak atsiri Duskar dari Ambon). CATATAN: Jika headline menyebut UMKM, WAJIB BUANG sesuai aturan x.
f. Limbah sawit (POME), BioCNG, biomethane, EBT, emisi, atau ESG dari pabrik sawit/PTPN: sisi energi/lingkungan, bukan inti industri. (Pengolahan limbah di dalam proses pabrik sawit, seperti pemisahan sludge, adalah "relevan".)
g. Berita B50/biodiesel yang fokus ke distribusi BBM, SPBU, terminal, kapal/asuransi, impor solar, atau energi. (B50 yang fokus ke pasokan sawit/CPO, ekspor, harga/kebijakan yang berdampak ke industri sawit adalah "relevan".)
h. EUDR dari sisi kesiapan daerah/budidaya (Kementan, dinas perkebunan, petani). (EUDR dari sisi ekspor/perundingan dagang adalah "relevan".)
i. Galon guna ulang/BPA yang ditulis ke arah konsumen atau dari sumber berkualitas rendah. (Yang membahas dampak ke industri AMDK atau sikap industri adalah "relevan".)
j. Swasembada susu, target sapi perah, produksi susu lokal: fokus peternakan yang menyentuh pasokan bahan baku industri atau kebijakan pemerintah secara eksplisit.
k. Pameran dagang umum yang tidak spesifik agro (TEI, misi dagang antarprovinsi). Pameran khusus promosi produk agro oleh lembaga pemerintah (misalnya BPDP untuk UMKM sawit/kakao) adalah "relevan".
l. Harga bursa harian komoditas (karet SGX-SICOM, minyak atsiri) tanpa konteks industri, prosedur karantina/fumigasi untuk ekspor, data sebaran perusahaan.
m. Pembiayaan/OJK untuk petani, ekosistem hulu-hilir campuran, kemitraan plasma/hulu sawit berkelanjutan, moratorium/lahan sawit, pembangunan perkebunan oleh dinas.
n. Sosialisasi cukai/DBHCHT oleh pemerintah daerah.
o. Kebijakan, pernyataan, atau program Menperin/Kemenperin terkait sektor non-agro (contoh: Tantangan Baru Kemenperin Membangun Industri Mesin, elektronika, alat transportasi) WAJIB "review" (sub_sektor: ILMATE).

RELEVAN (status "relevan"), termasuk yang sering salah dinilai:
- WAJIB RELEVAN: Semua berita kebijakan, pernyataan, atau program Menperin/Kemenperin dan pejabat Kemenperin yang menyangkut industri agro atau manufaktur nasional (PMI, IKI). Pejabat Kemenperin sektor agro = selalu relevan.

- Keluhan atau aspirasi petani TEMBAKAU (harga tembakau, serapan pabrik rokok, kuota impor tembakau, regulasi tembakau/IHT) = TETAP RELEVAN (karena bahan baku tembakau terkait langsung dengan rantai pasok industri hasil tembakau/IHT. Contoh: "Petani Tembakau Keluhkan Serapan Pabrik Rendah" adalah RELEVAN).
- Harga referensi/patokan pemerintah (HR CPO, kakao, bea keluar, harga patokan ekspor), harga biodiesel yang ditetapkan pemerintah, dan benchmark bursa adalah kinerja sektor, bukan harga eceran.
- Seluruh klaster rumput laut Menperin Sarmuji / KKP / Luhut (hilirisasi rumput laut, target produsen nomor satu dunia, investasi dan ekspor).
- Hilirisasi Kelapa US$100 Juta, Kementan fokus program hilirisasi kelapa, perlindungan KI minyak goreng kelapa, Munas KOPEK hilirisasi kelapa.
- BPDP buka proposal pendanaan hilirisasi perkebunan.
- Seluruh artikel Darori Wonodipuro soal karet dan skema BPDP (judul sama dari media beda tidak boleh di-dedup).
- Ekspor Kakao dan Kopi 2025, BPS ungkap pangsa ekspor komoditas agro, senja kala hulu-hilir karet.
- KT&G Esse investasi US$650 Juta di Indonesia, artikel kebijakan cukai hasil tembakau.
- Menko Muhaimin dorong nilai tambah kopi.
- PMI manufaktur, IKI, kinerja industri nasional, pernyataan atau program Menperin/Kemenperin, walau sudut pandangnya dari asosiasi industri lain (misalnya Inaplas), karena itu kebijakan/kinerja manufaktur.
- Kinerja emiten mamin/kertas/sawit: penjualan, margin, laba, harga pulp, hedging, dampak kurs.
- Kendala pasokan bahan baku/hulu yang menghambat hilirisasi sawit, kakao, kelapa.
- Ekspor-impor produk agro (rumput laut, cerutu, furnitur, kertas, CPO, kelapa olahan), larangan/penahanan impor oleh negara lain.
- Kebijakan hasil tembakau (PP 28/2024, cukai, larangan perisa, NPPBKC, kajian dampak ke pekerja industri), aturan halal produk agro/mamin, pengolahan produk agro skala IKM.
- Hilirisasi dan pengolahan: rumput laut, kelapa, kakao, sagu, bambu, karet olahan, pulp, mebel.
- JIKA RAGU antara "relevan" dan "buang", selalu pilih "review".

FORMAT OUTPUT
Balas HANYA dengan JSON valid, tanpa teks lain, tanpa markdown/backticks.

{
  "total_diproses": <jumlah berita input>,
  "total_relevan": <jumlah>,
  "total_review": <jumlah>,
  "total_dibuang": <jumlah>,
  "hasil": [
    {
      "id": <id input>,
      "status": "relevan" | "review",
      "sub_sektor": "Sawit/CPO" | "Biodiesel/B50" | "Hasil Tembakau" | "Kayu & Furnitur" | "Pulp & Kertas" | "Mamin" | "Kakao" | "Kelapa" | "Rumput Laut/Hasil Laut" | "Bambu" | "Karet" | "Susu" | "Industri Umum" | "Lainnya",
      "alasan": "<satu kalimat singkat>"
    }
  ],
  "dibuang": [
    {"id": <id input>, "alasan": "<satu kalimat singkat>"}
  ]
}

ATURAN KERJA
- Proses semua berita dalam input, satu per satu, tanpa ada yang terlewat.
- Setiap id input harus muncul tepat satu kali, di "hasil" atau di "dibuang".
- Pastikan total_diproses = total_relevan + total_review + total_dibuang.
- Gunakan id persis seperti input. Jangan mengubah atau mengarang id.
- Jangan mengarang isi berita. Jika hanya ada judul, nilai dari judul.
- Jika input kosong, balas {"total_diproses":0,"total_relevan":0,"total_review":0,"total_dibuang":0,"hasil":[],"dibuang":[]}.
"""

# Urutan model Gemini kandidat dengan fallback dinamis
CANDIDATE_MODELS = [
    "gemini-3-flash-preview",
    "gemini-flash-lite-latest",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
]
_current_model_idx = 0
_model_instance = None
gemini_quota_exhausted = False


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
                print(f"[AI MODEL] Menggunakan model Gemini: {m_name}", flush=True)
                return _model_instance
            except Exception:
                _current_model_idx += 1
                continue

        gemini_quota_exhausted = True
        print("[PERINGATAN] Seluruh kandidat model Gemini telah dicoba / kuota harian habis.", flush=True)
        return None
    except Exception as e:
        print(f"[PERINGATAN] Gagal menginisialisasi Gemini API: {e}", flush=True)
        return None


def parse_and_validate_batch_response(resp_text: str, sent_articles: list[dict]) -> dict:
    """
    Memvalidasi respon JSON dari Gemini untuk batch artikel.
    Memetakan tiap ID artikel ke status: 'relevan', 'review', atau 'buang'.
    Menangani array 'hasil' (relevan & review) dan 'dibuang' (tidak_relevan & duplikat).
    Jika ada ID yang terlewat / tidak konsisten, default ke 'review' (Perlu Dicek Manual).
    """
    sent_ids = [a["id"] for a in sent_articles]

    # Ekstrak blok JSON dari teks respon
    json_match = re.search(r"\{[\s\S]*\}", resp_text)
    if not json_match:
        print("  [WARNING] Respon Gemini tidak memuat JSON valid. Menandai seluruh batch sebagai 'review'.", flush=True)
        return {
            art_id: {
                "id": art_id,
                "status": "review",
                "sub_sektor": "-",
                "alasan": "AI tidak dijalankan (alasan: respon Gemini tidak memuat format JSON valid)"
            }
            for art_id in sent_ids
        }

    try:
        data = json.loads(json_match.group(0))
    except Exception as e:
        print(f"  [WARNING] Error json.loads: {e}. Menandai seluruh batch sebagai 'review'.", flush=True)
        return {
            art_id: {
                "id": art_id,
                "status": "review",
                "sub_sektor": "-",
                "alasan": f"AI tidak dijalankan (alasan: error parsing JSON AI: {e})"
            }
            for art_id in sent_ids
        }

    hasil_list = data.get("hasil", [])
    dibuang_list = data.get("dibuang", [])

    returned_map = {}

    # 1. Parse array 'hasil' (status: 'relevan' atau 'review')
    for item in hasil_list:
        if isinstance(item, dict) and "id" in item:
            item_id = item["id"]
            st = str(item.get("status", "relevan")).strip().lower()
            if st not in ["relevan", "review"]:
                st = "review"
            returned_map[item_id] = {
                "id": item_id,
                "status": st,
                "sub_sektor": str(item.get("sub_sektor", "Industri Umum")).strip() or "Industri Umum",
                "alasan": str(item.get("alasan", "")).strip()
            }

    # 2. Parse array 'dibuang'
    for item in dibuang_list:
        if isinstance(item, dict) and "id" in item:
            item_id = item["id"]
            returned_map[item_id] = {
                "id": item_id,
                "status": "buang",
                "sub_sektor": "-",
                "alasan": str(item.get("alasan", "Bukan Sektor Industri Agro")).strip()
            }

    result_by_id = {}
    for art_id in sent_ids:
        val = returned_map.get(art_id)
        if val is None and str(art_id) in returned_map:
            val = returned_map[str(art_id)]
        if val is None and isinstance(art_id, str) and art_id.isdigit() and int(art_id) in returned_map:
            val = returned_map[int(art_id)]

        if val is not None:
            result_by_id[art_id] = val
        else:
            # Jika ada id yang terlewat dari respon AI: default ke "review"
            result_by_id[art_id] = {
                "id": art_id,
                "status": "review",
                "sub_sektor": "Industri Umum",
                "alasan": "ID tidak ditemukan/terlewat dalam respon AI (perlu verifikasi manual)"
            }

    sent_by_id = {a["id"]: a for a in sent_articles}
    for art_id, val in result_by_id.items():
        art = sent_by_id.get(art_id, {})
        t_raw = str(art.get("title", ""))
        t_low = t_raw.lower()
        if "industri mesin" in t_low and "kemenperin" in t_low:
            val["status"] = "review"
            val["sub_sektor"] = "ILMATE"
            val["alasan"] = "Kebijakan Kemenperin Sektor Non-IA (ILMATE)"
        elif bool(re.search(r"\b(?:umkm|ukm)\b|\busaha\s+mikro\b", t_raw, re.IGNORECASE)):
            val["status"] = "buang"
            val["sub_sektor"] = "-"
            val["alasan"] = "Headline UMKM (Bukan Sektor Industri Agro)"

    return result_by_id


def classify_agro_relevance_batch(articles: list[dict]) -> dict:
    """
    Mengklasifikasikan satu batch artikel (20-30 artikel) ke Gemini API.
    Menerima list artikel: [{'id': ..., 'title': ..., 'text_snippet': ...}].
    Mengembalikan dictionary:
    {
      'total_diproses': int,
      'total_relevan': int,
      'total_review': int,
      'total_dibuang': int,
      'total_dipertahankan': int,
      'hasil': list[dict],
      'dibuang': list[dict],
      'by_id': dict[id, dict]
    }
    """
    global gemini_quota_exhausted

    if not articles:
        return {
            "total_diproses": 0,
            "total_relevan": 0,
            "total_review": 0,
            "total_dibuang": 0,
            "total_dipertahankan": 0,
            "hasil": [],
            "dibuang": [],
            "by_id": {}
        }

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("[WARNING] GEMINI_API_KEY tidak ditemukan. Menandai batch sebagai 'review'.", flush=True)
        by_id = {
            a["id"]: {
                "id": a["id"],
                "status": "review",
                "sub_sektor": "-",
                "alasan": "AI tidak dijalankan (alasan: GEMINI_API_KEY tidak ditemukan)"
            }
            for a in articles
        }
        return {
            "total_diproses": len(articles),
            "total_relevan": 0,
            "total_review": len(articles),
            "total_dibuang": 0,
            "total_dipertahankan": len(articles),
            "hasil": list(by_id.values()),
            "dibuang": [],
            "by_id": by_id
        }

    # Format input berita ke JSON
    formatted_input = []
    for a in articles:
        snip = str(a.get("text_snippet") or a.get("snippet") or a.get("text") or "").strip()[:300]
        item_entry = {
            "id": a["id"],
            "title": str(a.get("title", "")).strip(),
        }
        media = str(a.get("media_name") or a.get("media") or "").strip()
        if media:
            item_entry["media_name"] = media
        if snip:
            item_entry["text_snippet"] = snip
        formatted_input.append(item_entry)

    user_payload = f"Daftar berita untuk dinilai (total: {len(formatted_input)}):\n{json.dumps(formatted_input, ensure_ascii=False, indent=2)}"
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_payload}"

    max_attempts = 3
    last_error_reason = ""
    for attempt in range(max_attempts):
        model = _get_gemini_model()
        if model is None:
            last_error_reason = "seluruh model Gemini gagal diinisialisasi / kuota habis"
            break

        try:
            response = model.generate_content(full_prompt, request_options={"retry": None, "timeout": 45})  # type: ignore
            resp_text = (response.text or "").strip()
            by_id = parse_and_validate_batch_response(resp_text, formatted_input)

            retained = [v for v in by_id.values() if v["status"] in ["relevan", "review"]]
            relevan_items = [v for v in by_id.values() if v["status"] == "relevan"]
            review_items = [v for v in by_id.values() if v["status"] == "review"]
            discarded = [v for v in by_id.values() if v["status"] == "buang"]

            return {
                "total_diproses": len(articles),
                "total_relevan": len(relevan_items),
                "total_review": len(review_items),
                "total_dibuang": len(discarded),
                "total_dipertahankan": len(retained),
                "hasil": retained,
                "dibuang": discarded,
                "by_id": by_id
            }

        except Exception as e:
            err_msg = str(e).lower()
            last_error_reason = str(e)
            is_rate_limit = "429" in err_msg or "quota" in err_msg or "resourceexhausted" in err_msg

            if is_rate_limit:
                is_daily = "generaterequestsperday" in err_msg or "perday" in err_msg
                if is_daily:
                    print("[RATE LIMIT HARIAN] Model mencapai batas harian. Beralih ke model kandidat berikutnya...", flush=True)
                    _get_gemini_model(force_next=True)
                    time.sleep(1.0)
                    continue

                # RPM limit: tunggu 60 detik
                print(f"[RATE LIMIT RPM] Terkena batas per menit. Menunggu 60 detik (percobaan {attempt + 1}/{max_attempts})...", flush=True)
                time.sleep(60.0)
                continue
            else:
                print(f"[ERROR GEMINI] {e}. Mencoba beralih model / retry...", flush=True)
                _get_gemini_model(force_next=True)
                time.sleep(2.0)
                continue

    # Fallback aman jika seluruh percobaan gagal: Tandai sebagai "review" (Aturan 3)
    fallback_reason = f"AI tidak dijalankan (alasan: {last_error_reason or 'panggilan Gemini gagal/timeout'})"
    print(f"  [FALLBACK] Gagal memproses batch via AI. {fallback_reason}", flush=True)
    by_id = {
        a["id"]: {
            "id": a["id"],
            "status": "review",
            "sub_sektor": "-",
            "alasan": fallback_reason
        }
        for a in articles
    }
    return {
        "total_diproses": len(articles),
        "total_relevan": 0,
        "total_review": len(articles),
        "total_dibuang": 0,
        "total_dipertahankan": len(articles),
        "hasil": list(by_id.values()),
        "dibuang": [],
        "by_id": by_id
    }


def classify_articles_in_batches(
    articles: list[dict],
    batch_size: int = 25,
    delay_between_batches: float = 2.5
) -> dict:
    """
    Memecah seluruh artikel menjadi batch-batch berukuran batch_size (default: 25),
    mengirim ke classify_agro_relevance_batch, dan menggabungkan hasilnya.
    Tetap menjaga jeda antar-batch (2-3 detik) untuk stabilitas koneksi.
    """
    total_articles = len(articles)
    all_by_id = {}
    api_calls_count = 0

    print(f"\n[BATCH CLASSIFIER] Memulai klasifikasi {total_articles} artikel dalam batch {batch_size}...", flush=True)

    for i in range(0, total_articles, batch_size):
        batch = articles[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_articles + batch_size - 1) // batch_size

        print(f"  [Batch {batch_num}/{total_batches}] Mengirim {len(batch)} artikel (ID {batch[0]['id']} s/d {batch[-1]['id']})...", flush=True)
        res = classify_agro_relevance_batch(batch)
        api_calls_count += 1

        all_by_id.update(res["by_id"])

        # Jeda antar batch jika masih ada batch berikutnya
        if i + batch_size < total_articles and delay_between_batches > 0:
            time.sleep(delay_between_batches)

    retained = [v for v in all_by_id.values() if v["status"] in ["relevan", "review"]]
    relevan_count = sum(1 for v in all_by_id.values() if v["status"] == "relevan")
    review_count = sum(1 for v in all_by_id.values() if v["status"] == "review")
    buang_count = sum(1 for v in all_by_id.values() if v["status"] == "buang")
    discarded = [v for v in all_by_id.values() if v["status"] == "buang"]

    print(f"[BATCH CLASSIFIER SELESAI] Total: {total_articles} | Relevan: {relevan_count} | Review: {review_count} | Dibuang: {buang_count} | Panggilan API: {api_calls_count}\n", flush=True)

    return {
        "total_diproses": total_articles,
        "total_relevan": relevan_count,
        "total_review": review_count,
        "total_dibuang": buang_count,
        "total_dipertahankan": len(retained),
        "api_calls_terpakai": api_calls_count,
        "hasil": retained,
        "dibuang": discarded,
        "by_id": all_by_id
    }


class RelevanceResult(tuple):
    """Hasil klasifikasi relevansi yang mendukung akses tuple (is_rel, reason) dan atribut (.status, .sub_sektor)."""
    def __new__(cls, is_rel: bool, reason: str, status: str = "review", sub_sektor: str = "-"):
        return super().__new__(cls, (is_rel, reason))

    def __init__(self, is_rel: bool, reason: str, status: str = "review", sub_sektor: str = "-"):
        self.is_rel = is_rel
        self.reason = reason
        self.status = status
        self.sub_sektor = sub_sektor


def classify_agro_relevance(title: str, text_snippet: str = "", delay: float = 0.0) -> RelevanceResult:
    """
    Fungsi kompatibilitas ke belakang untuk satu artikel.
    Mengembalikan RelevanceResult(is_rel, alasan, status, sub_sektor)
    yang kompatibel dengan unpack 2-elemen (is_rel, alasan = ...) maupun akses atribut.
    """
    item = [{"id": 1, "title": title, "text_snippet": text_snippet}]
    res = classify_agro_relevance_batch(item)
    art_res = res["by_id"].get(1, {})
    status = art_res.get("status", "review")
    is_rel = status in ["relevan", "review"]
    reason = art_res.get("alasan", "")
    sub_sektor = art_res.get("sub_sektor", "-")
    return RelevanceResult(is_rel, reason, status, sub_sektor)


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
        log_dir = Path("hasil_scrapping") / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "log_ai_rejection.jsonl"
    else:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "title": title,
        "alasan": reason,
        "tanggal": published or "",
        "keyword": keyword or "",
    }

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[PERINGATAN] Gagal menulis log rejection AI: {e}")
