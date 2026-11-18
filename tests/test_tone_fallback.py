"""
tests/test_tone_fallback.py
Unit test (pytest) untuk rule-based fallback klasifikasi tone berdasarkan
Indikator Sentimen Pemberitaan Biro Humas Kemenperin:
- K1 (aktivitas/narasumber Kemenperin) tanpa serangan -> Positif (P1).
- K3 tanpa serangan/dukungan ke Kemenperin (termasuk kondisi industri A1 & desakan umum A2) -> Netral (Ne2).
- Serangan langsung ke Kemenperin atau kebijakannya -> Negatif (N1..N4).
- Penanganan negasi ("tidak rugi", "tidak naik") -> Netral.
"""

import os
import sys
import pytest

# Pastikan root direktori ada di sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tone_classifier import classify_tone_fallback, classify_tone


BENCHMARK_TITLES = [
    # --- P1: Kemenperin / pejabat Kemenperin pelaku utama tanpa serangan -> Positif ---
    (
        "Kemenperin Siapkan Strategi Hadapi Pelemahan Permintaan Tekstil",
        "Positif",
        "P1 (K1): aktivitas resmi Kemenperin, kata pelemahan bukan serangan ke Kemenperin (A4)",
    ),
    (
        "Kemenperin Antisipasi Lonjakan Harga Gula Jelang Nataru",
        "Positif",
        "P1 (K1): langkah antisipasi resmi Kemenperin",
    ),
    (
        "Menperin Resmikan Pabrik Baru di Kawasan Industri Kendal",
        "Positif",
        "P1 (K1): peresmian oleh Menperin untuk pengembangan industri",
    ),
    (
        "Kemenperin Upayakan Solusi Hadapi Masalah Pasokan Gula Rafinasi",
        "Positif",
        "P1 (K1): upaya resmi Kemenperin",
    ),

    # --- Ne2 / A1 / A2: Berita topik agro tanpa peran atau serangan ke Kemenperin -> Netral ---
    (
        "Ekspor Karet Remah Indonesia 2024 Capai US$2,8 Miliar, Jepang Tujuan Utama",
        "Netral",
        "Ne2 (K3): capaian komoditas umum tanpa penyebutan atau dukungan kebijakan Kemenperin",
    ),
    (
        "Rokok Ilegal Makin Marak, Ekonom Minta Pemerintah Tunda Kenaikan Cukai hingga 2 Tahun",
        "Netral",
        "Ne2 (K3) + A2: usulan ke pemerintah umum tanpa menyerang Kemenperin",
    ),
    (
        "Permintaan Tekstil Melemah, Pabrik Kurangi Produksi dan Rumahkan Karyawan",
        "Netral",
        "Ne2 (K3) + A1: kondisi industri memburuk tanpa serangan ke Kemenperin",
    ),
    (
        "Harga Gula Anjlok, Petani Tebu Merugi",
        "Netral",
        "Ne2 (K3) + A1: penurunan harga tanpa serangan ke Kemenperin",
    ),
    (
        "Penerimaan Negara dari Cukai Naik 8 Persen",
        "Netral",
        "K3 tanpa dukungan/serangan terhadap Kemenperin (cukai ranah fiskal A3/Ne2)",
    ),
    (
        "Bukan Sekadar Olah Bahan Mentah, BPDP Dorong Hilirisasi Perkebunan Jadi Transformasi Ekonomi",
        "Netral",
        "Ne2 (K3): lembaga non-Kemenperin tanpa dukungan/serangan langsung ke kebijakan Kemenperin",
    ),
    (
        "Petani Harus Nikmati Nilai Tambah, Darori Dorong Karet Tak Lagi Dijual Mentah",
        "Netral",
        "Ne2 (K3): dorongan komoditas umum tanpa dukungan eksplisit ke kebijakan Kemenperin",
    ),
    (
        "GAPKI Dorong Kemitraan Sawit antara Indonesia dan India",
        "Netral",
        "Ne2 (K3): inisiatif asosiasi tanpa menyebut/mendukung kebijakan Kemenperin",
    ),
    (
        "Realisasi Investasi Industri Mamin Capai Puluhan Triliun Rupiah",
        "Netral",
        "Ne2 (K3): data investasi umum tanpa penyebutan Kemenperin",
    ),
    (
        "Surplus Perdagangan Sektor Agro Tembus Rekor Tertinggi",
        "Netral",
        "Ne2 (K3): data dagang tanpa penyebutan Kemenperin",
    ),
    (
        "Harga CPO Tidak Naik Pekan Ini",
        "Netral",
        "Ne2 (K3) + negasi: tidak ada kaitan/serangan ke Kemenperin",
    ),
    (
        "Industri Mamin Tidak Rugi Tahun Ini",
        "Netral",
        "Ne2 (K3) + negasi: menafikan kerugian tanpa kaitan Kemenperin",
    ),
    (
        "Jadwal Pameran Trade Expo Indonesia 2026",
        "Netral",
        "K4/Ne2: informasi jadwal umum",
    ),
    (
        "Pemerintah Kaji Dampak Fluktuasi Harga Komoditas Pangan Global",
        "Netral",
        "Ne2 (K3) + A2: kajian pemerintah umum tanpa menyebut Kemenperin",
    ),
    (
        "Ekspor Tumbuh, Tapi Harga Anjlok",
        "Netral",
        "Ne2 (K3) + A1: penurunan harga tanpa serangan ke Kemenperin",
    ),
    (
        "Kenaikan Cukai Bebani Industri Rokok, Ancam PHK Pekerja",
        "Netral",
        "Ne2 (K3) + A1/A4: beban industri tanpa serangan ke Kemenperin atau kebijakannya",
    ),
    (
        "Penerimaan Negara dari Cukai Hasil Tembakau Turun, Kenaikan Tarif Dinilai Tak Efektif",
        "Netral",
        "K3 tanpa menyinggung/menyerang Kemenperin secara spesifik",
    ),
    (
        "BPS Ungkap Penyebab Karet hingga Teh RI Kehilangan Pangsa Pasar Global",
        "Netral",
        "Ne2 (K3) + A1: laporan kondisi pasar tanpa menyalahkan Kemenperin",
    ),
    (
        "Rokok Ilegal Makin Marak, Aturan IHT Jadi Sorotan",
        "Netral",
        "Ne2 (K3) + A4/A5: sorotan umum tanpa menuding Kemenperin secara eksplisit",
    ),
    (
        "Petani Tembakau Keluhkan Serapan Pabrik Rendah",
        "Netral",
        "Ne2 (K3) + A1: keluhan kondisi pasar tanpa menyerang Kemenperin",
    ),
    (
        "Harga Pulp Berpotensi Tertekan pada 2027, Analis Ungkap Prospek INKP",
        "Netral",
        "Ne2 (K3) + A1: prospek pasar emiten tanpa serangan ke Kemenperin",
    ),
    (
        "Pabrik Sawit di Riau Bangkrut dan Tutup Operasional",
        "Netral",
        "Ne2 (K3) + A1: pabrik tutup tanpa serangan ke Kemenperin",
    ),
    (
        "Kelangkaan Bahan Baku Garam Industri Bebani Pabrik Kimia dan Pangan",
        "Netral",
        "Ne2 (K3) + A1: kendala bahan baku tanpa serangan ke Kemenperin",
    ),
]


@pytest.mark.parametrize("title,expected_tone,keterangan", BENCHMARK_TITLES)
def test_fallback_tone_benchmark(title: str, expected_tone: str, keterangan: str):
    """Memverifikasi seluruh judul benchmark selaras dengan Indikator Biro Humas Kemenperin."""
    actual_tone, dasar, alasan = classify_tone_fallback(title, text="")
    assert actual_tone == expected_tone, (
        f"Gagal pada judul: '{title}'\n"
        f"Diharapkan: {expected_tone}, didapat: {actual_tone}\n"
        f"Dasar: {dasar}, Alasan: {alasan}\n"
        f"Keterangan uji: {keterangan}"
    )


def test_classify_tone_wrapper_compatibility():
    """Memastikan fungsi wrapper legacy classify_tone() tetap sinkron dengan fallback Biro Humas."""
    assert classify_tone(title="Kemenperin Siapkan Strategi Hadapi Pelemahan Permintaan Tekstil") == "Positif"
    assert classify_tone(title="Permintaan Tekstil Melemah, Pabrik Kurangi Produksi dan Rumahkan Karyawan") == "Netral"
    assert classify_tone(title="Asosiasi Kritik Kebijakan Kemenperin yang Menghambat Industri") == "Negatif"


def test_contrast_pair_humas_k1_vs_n1():
    """
    Verifikasi pasangan kontras indikator Humas:
    - Aktivitas Kemenperin menghadapi masalah industri (P1 + A4) -> Positif
    - Kondisi industri memburuk tanpa serangan ke Kemenperin (A1) -> Netral
    - Serangan terhadap kebijakan Kemenperin (N1) -> Negatif
    """
    t_k1 = "Kemenperin Siapkan Strategi Hadapi Pelemahan Permintaan Tekstil"
    t_a1 = "Permintaan Tekstil Melemah, Pabrik Kurangi Produksi dan Rumahkan Karyawan"
    t_n1 = "Gabungan Pengusaha Kritik Kebijakan Kemenperin yang Dinilai Membebani Pabrik"

    assert classify_tone_fallback(t_k1)[0] == "Positif"
    assert classify_tone_fallback(t_a1)[0] == "Netral"
    assert classify_tone_fallback(t_n1)[0] == "Negatif"
