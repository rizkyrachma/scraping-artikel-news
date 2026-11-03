"""
curate_hilir_2026_10_21_26.py
Penyaringan khusus Sektor Hilir Industri Agro (IA) Ditjen Industri Agro untuk periode 21 - 26 Oktober 2026:
- Mengeliminasi ranah hulu (lahan, STDB, bibit, peremajaan kebun, budidaya tambak, harga bahan mentah petani)
- Mengeliminasi bukan sektor agro (otomotif mobil hybrid, galangan kapal, baja skrap, bendung irigasi PU)
- Mengeliminasi noise web (katalog made-in-china, repositori akademik, listicle/opini blog umum)
- Mempertahankan 57 artikel hilir industri agro (manufaktur, pabrik mamin, hilirisasi kelapa/sawit, IHT, kakao olahan, mebel, rumput laut olahan, dsb)
- Menyinkronkan 6 ringkasan eksekutif 5W+1H untuk berita bertone Negatif di Sheet 'Ringkasan Negatif'
- Menyimpan berkas master final ke hasil_scrapping/Oktober/2026-10-21_sd_2026-10-26/
"""

import os
import sys
import json
import shutil
import pandas as pd

# Tambahkan src ke sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from export_excel import save_to_excel
from config import load_spokesperson_map
from entity_mapper import find_spokespersons


NON_HILIR_RULES = [
    # 1. Non-Agro (Otomotif, Logam, Maritim, PU Bendung, Bencana Kabut Asap, Smart City)
    (lambda t: "insentif hybrid" in t or "reev" in t or "ganjil genap" in t, "Bukan Agro (Otomotif / Kendaraan Listrik ILMATE)"),
    (lambda t: "galangan kapal" in t, "Bukan Agro (Industri Maritim ILMATE)"),
    (lambda t: "skrap baja" in t, "Bukan Agro (Logam / Baja ILMATE)"),
    (lambda t: "lebih hemat bbm dari hybrid" in t, "Bukan Agro (Otomotif / Mobil)"),
    (lambda t: "bendung karet" in t, "Bukan Agro (Infrastruktur Irigasi PU / Sumber Daya Air)"),
    (lambda t: "kabut asap" in t or "haze victims" in t, "Bukan Agro (Bencana Kebakaran Hutan)"),
    (lambda t: "as cabut sebagian tarif impor kanada" in t, "Bukan Agro (Tarif Kayu Luar Negeri AS-Kanada)"),
    (lambda t: "indonesia-rusia perkuat kerja sama ekonomi" in t, "Bukan Agro (Kerja Sama Bilateral Umum Kepolisian)"),
    (lambda t: "smart city temanggung" in t, "Bukan Agro (Profil Smart City Daerah)"),
    (lambda t: "repositori institusi" in t, "Artifact Web (Halaman Repositori STIKES)"),
    (lambda t: "peraturan pemerintah nomor 189 tahun 1961" in t, "Arsip Lama (Regulasi PP Tahun 1961)"),
    (lambda t: "produksi susu september mencapai 2,928 juta ton, nai" in t, "Data Asing (Biro Statistik Nasional China / NBS)"),

    # 2. Hulu Perkebunan & Tanaman Pangan (Lahan, STDB, Peremajaan/Replanting, Budidaya, Agronomi)
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

    # 3. Non-Industri / Edukasi Pelajar / Listicle Konsumsi / Promosi Luar
    (lambda t: "apa itu kertas tisu pulp kayu virgin" in t, "Iklan Katalog Produk Impor (Made-in-China B2B Video)"),
    (lambda t: "kenalkan potensi industri kelapa sawit berkelanjutan kepada pelajar" in t, "Sosialisasi Edukasi Pelajar (BPDP Sawit Goes to School)"),
    (lambda t: "kenalkan kebaikan sawit bagi peternak sapi" in t, "Pelatihan Peternak Sapi Lokal (BPDP Limbah Pakan)"),
    (lambda t: "kelapa sawit expo center 2026: dari kampung yang pernah" in t, "Pemberdayaan Ekonomi Warga Kampung Sawit"),
    (lambda t: "kelapa muda naik kelas saat motogp mandalika" in t, "Pariwisata / Kuliner Event Olahraga (Minuman Kelapa Muda)"),
    (lambda t: "berkah ekonomi atau kutukan ekologi" in t, "Blog Opini UGC (Kompasiana)"),
    (lambda t: "terobosan endy, maya, lutfi" in t, "Blog Opini UGC (Kompasiana)"),
    (lambda t: "hmp bdp unhas tingkatkan nilai ekonomi rumput laut" in t, "Kegiatan Mahasiswa / PKM Kampus (BDP Unhas)"),
    (lambda t: "sagu warnai tarung tiga di jayapura" in t, "Event Budaya / Kuliner Lokal Papua"),
    (lambda t: "10 negara paling doyan mi instan" in t, "Listicle Konsumsi Mie Instan Global"),
    (lambda t: "kombes fredricukus dorong pemuda papua" in t, "Himbauan Kepolisian Kamtibmas Pemuda"),
    (lambda t: "michael yarisetouw ajak anak muda papua" in t, "Himbauan Kepemudaan Daerah Papua"),
    (lambda t: "dari kebun hingga produk cokelat, fakultas pertanian utu" in t, "Program Magang Mahasiswa Kampus UTU"),

    # 4. Riset Kampus, Lomba Mahasiswa, Pengabdian Dosen di Desa & UMKM Lokal Non-Pabrik
    (lambda t: "pimnas" in t or "tim unair" in t, "Riset / Lomba Mahasiswa Kampus (PIMNAS UNAIR)"),
    (lambda t: "ekspedisi patriot ipb" in t, "Pengabdian Mahasiswa di Desa (IPB Merauke)"),
    (lambda t: "tim undana" in t or "karsa nusa" in t, "Lomba Mahasiswa Kampus (Undana Karsa Nusa)"),
    (lambda t: "umpwr" in t or "unkriswina" in t, "Pengabdian Dosen Kampus ke Desa Pesisir (UMPWR & Unkriswina)"),
    (lambda t: "kompetisi bisnis sosial" in t or "finalis kompetisi dunia" in t or "juarai kompetisi kewirausahaan" in t, "Kompetisi Startup / Wirausaha Sosial Global"),
    (lambda t: "kentang afkir petani podokoyo" in t, "Olahan Makanan Skala Desa / Rumah Tangga (Podokoyo Pasuruan)"),
    (lambda t: "limbah kulit singkong" in t, "Artikel Tips / Kuliner Rumah Tangga (RRI)"),
    (lambda t: "perajin sleman" in t, "Kerajinan Tangan / UMKM Lokal Sleman"),
    (lambda t: "sabut kelapa solusi bahan komposit" in t, "Wacana Artikel Laboratorium / Artikel Umum (RRI)"),
    (lambda t: "hadir di berbagai produk harian" in t, "Artikel Edukasi Umum Produk Harian (Jambi Ekspres)"),
    (lambda t: "tanjabbar" in t or "tanjab barat" in t, "Wacana Indikasi Geografis Pemda Tanjab Barat"),
    (lambda t: "program hilir berau" in t, "Program Dinas Kelautan & Perikanan Daerah Berau"),
    (lambda t: "sagu di aceh barat" in t, "Liputan Potensi Usaha Skala Daerah Aceh Barat"),

    # 5. Bukan Sektor Agro (Pertambangan ESDM Bahlil, Industri Keramik IKFT, ESDM Energi, Artifact)
    (lambda t: any(w in t for w in ["tambang", "menambang", "penambangan"]), "Bukan Sektor Agro (Pertambangan ESDM Bahlil)"),
    (lambda t: "esdm dalami kebun sawit" in t or "esdm siapkan" in t, "Bukan Sektor Agro (Pertambangan ESDM)"),
    (lambda t: "industri keramik" in t, "Bukan Sektor Agro (Keramik IKFT)"),
    (lambda t: "komisi xii dpr" in t or "dirjen ebtke" in t, "Bukan Sektor Agro (ESDM Energi)"),
    (lambda t: "sektor energi dua tahun pemerintahan" in t, "Bukan Sektor Agro (ESDM Energi)"),
    (lambda t: "stuktur data" in t, "Artifact Error Web"),

    # 6. Hulu Perkebunan, Budidaya Tambak & Pesisir, Bibit & Agronomi
    (lambda t: any(w in t for w in ["pembaruan bibit", "rumah bibit", "perbenihan kelapa", "budidaya tambak", "modelling budidaya", "rumah budidaya"]), "Hulu Budidaya / Bibit (KKP / Perbenihan Kebun)"),
    (lambda t: any(w in t for w in ["pembudi daya rumput", "pembudidaya rumput", "nelayan dan pembudi", "panen raya rumput"]), "Hulu Nelayan / Pembudidaya Rumput Laut"),
    (lambda t: "bantuan perikanan bukan untuk" in t or "pengecekan sarana dan prasarana" in t, "Hulu Bantuan Sarpras Perikanan KKP"),
    (lambda t: "ritual baremah" in t, "Hulu Perkebunan (Adat Ritual Peremajaan Kebun PTPN IV)"),
    (lambda t: "ikan patin" in t, "Hulu Budidaya Tambak (Ikan Patin)"),
    (lambda t: "komisi iv dpr ri - dalami potensi bungkil" in t, "Hulu Pertanian (Komisi IV DPR RI)"),
    (lambda t: "moratorium sawit" in t, "Ranah Kehutanan / Lingkungan (KLHK)"),
    (lambda t: "buletin informasi iklim" in t, "Klimatologi Kebun (BMKG)"),
    (lambda t: "petani swadaya di aceh" in t, "Penyuluhan Petani Swadaya Hulu"),
    (lambda t: "kuncup putih di lereng detubapa" in t, "Feature Cerita Kebun Kopi Ende"),
    (lambda t: "menkop ri fasilitasi pengembangan kopi papua" in t, "Koperasi Daerah Pegunungan Papua"),
    (lambda t: "perajin batik tulis" in t or "lilin batik" in t or "batik sawit" in t or "smart batik" in t, "Kerajinan Batik Tulis UMKM"),
    (lambda t: "siap jadi percontohan tata kelola perkebunan" in t or "jalankan psn sawit, agrinas palma" in t, "Penyelenggaraan Kebun Kelapa Sawit PSN"),
    (lambda t: "implementasi pembangunan kelapa sawit yang berkelanjutan" in t, "Artikel Teori Konseptual Pembangunan Sawit"),
    (lambda t: "dprd lampung optimis harga singkong" in t, "Hulu Harga Panen Singkong Petani (DPRD)"),
    (lambda t: "teaching factory smkn 5 merauke" in t, "Vokasi Sekolah Menengah (SMK Teh Sarang)"),
    (lambda t: "riset ai klasifikasi ampas sagu antar 2 siswa" in t, "Lomba Karya Ilmiah Siswa Madrasah (MAN IC)"),
    (lambda t: "mahasiswa feb unimal juara satu" in t, "Lomba Business Plan Mahasiswa FEB"),
    (lambda t: "kisah inspiratif mama lidia mikan" in t, "Profil Human Interest Inspiratif UMKM Lokal"),
    (lambda t: "unand olah gambir jadi minuman dan kosmetik" in t, "Hilirisasi Riset Laboratorium Kampus (UNAND)"),
    (lambda t: "mengalir ke israel" in t, "Isu Geopolitik / Investigasi Ekspor Transit"),
    (lambda t: "angkutan cpo diatas 20 ton" in t or "pt sil tegaskan kepatuhan tonase" in t, "Kamtibmas Jalan Desa Tonase Truk Sawit"),
]


def main():
    target_dir = os.path.join("hasil_scrapping", "Oktober", "2026-10-21_sd_2026-10-26")
    src_excel = os.path.join(target_dir, "all_2026-10-21_sd_2026-10-26_ringkasan.xlsx")
    backup_excel = os.path.join(target_dir, "all_2026-10-21_sd_2026-10-26_mentah_unfiltered.xlsx")
    progress_file = os.path.join(target_dir, "progress.json")

    print("=" * 70)
    print("PENYARINGAN EKSKLUSIF SEKTOR HILIR INDUSTRI AGRO (21 - 26 OKTOBER 2026)")
    print("=" * 70)

    # Backup file mentah jika belum ada
    if not os.path.exists(backup_excel) and os.path.exists(src_excel):
        shutil.copy2(src_excel, backup_excel)
        print(f"[Backup] Dataset mentah dicadangkan ke: {backup_excel}")

    source_to_read = backup_excel if os.path.exists(backup_excel) else src_excel
    if not os.path.exists(source_to_read):
        raise FileNotFoundError(f"File sumber tidak ditemukan: {source_to_read}")

    df_berita = pd.read_excel(source_to_read, sheet_name="Berita")
    df_neg = pd.read_excel(source_to_read, sheet_name="Ringkasan Negatif")

    print(f"[+] Total Berita Awal       : {len(df_berita)}")
    print(f"[+] Total Ringkasan Negatif : {len(df_neg)}")

    hilir_articles = []
    discarded_articles = []

    for _, row in df_berita.iterrows():
        item = row.to_dict()
        title_raw = str(item.get("Title", "")).strip()
        t_lower = title_raw.lower()

        discard_reason = None
        for rule_fn, reason in NON_HILIR_RULES:
            if rule_fn(t_lower):
                discard_reason = reason
                break

        if discard_reason:
            discard_item = dict(item)
            discard_item["Alasan Dibuang"] = discard_reason
            discarded_articles.append(discard_item)
        else:
            hilir_articles.append(item)

    print(f"\n[+] Artikel Lolos Sektor Hilir IA : {len(hilir_articles)} artikel")
    print(f"[+] Artikel Dibuang (Hulu/Noise) : {len(discarded_articles)} artikel")

    # Filter Ringkasan Negatif: hanya yang artikelnya lolos di hilir_articles
    hilir_links = {
        str(a.get("Link Website", "")).strip().split("?")[0].rstrip("/").lower()
        for a in hilir_articles if a.get("Link Website")
    }
    hilir_titles = {
        str(a.get("Title", "")).strip().lower() for a in hilir_articles if a.get("Title")
    }

    processed_neg = []
    for _, row in df_neg.iterrows():
        neg_item = row.to_dict()
        link_clean = str(neg_item.get("Link Website", "")).strip().split("?")[0].rstrip("/").lower()
        title_clean = str(neg_item.get("Title", "")).strip().lower()

        if link_clean in hilir_links or title_clean in hilir_titles:
            processed_neg.append(neg_item)

    print(f"[+] Ringkasan Negatif Hilir Valid : {len(processed_neg)} baris")

    # Simpan log artikel yang dibuang
    discard_log = os.path.join(target_dir, "discarded_articles.json")
    with open(discard_log, "w", encoding="utf-8") as f:
        json.dump(discarded_articles, f, ensure_ascii=False, indent=2, default=str)
    print(f"[+] Log artikel dibuang tersimpan di: {discard_log}")

    # Ekspor ke Excel
    out_ringkasan = os.path.join(target_dir, "all_2026-10-21_sd_2026-10-26_ringkasan.xlsx")
    out_all = os.path.join(target_dir, "all_2026-10-21_sd_2026-10-26.xlsx")

    save_to_excel(hilir_articles, out_ringkasan, merge_existing=False, negative_summaries=processed_neg)
    print(f"[SUKSES] Master Ringkasan tersimpan ke: {out_ringkasan}")

    save_to_excel(hilir_articles, out_all, merge_existing=False, negative_summaries=None)
    print(f"[SUKSES] Master Berita tersimpan ke: {out_all}")

    # Sinkronisasi checkpoint progress.json
    if os.path.exists(progress_file):
        backup_prog = os.path.join(target_dir, "progress_unfiltered.json")
        if not os.path.exists(backup_prog):
            shutil.copy2(progress_file, backup_prog)
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                prog_data = json.load(f)
            prog_data["articles"] = hilir_articles
            prog_data["discarded_count"] = len(discarded_articles)
            with open(progress_file, "w", encoding="utf-8") as f:
                json.dump(prog_data, f, ensure_ascii=False, indent=2, default=str)
            print(f"[+] progress.json diperbarui ({len(hilir_articles)} artikel hilir)")
        except Exception as e:
            print(f"[Warning] Gagal memperbarui progress.json: {e}")

    # Rincian Laporan Akhir
    df_final = pd.DataFrame(hilir_articles)
    df_final["_tgl"] = pd.to_datetime(df_final["Tanggal"], errors="coerce").dt.strftime("%Y-%m-%d")

    print("\n" + "=" * 50)
    print("DISTRIBUSI DATASET HILIR PER TANGGAL:")
    print("=" * 50)
    for t_str, c in df_final["_tgl"].value_counts().sort_index().items():
        print(f"  {t_str}: {c} artikel")

    print("\nDISTRIBUSI TONE HILIR:")
    for tone, c in df_final["Tone"].value_counts().items():
        print(f"  {tone}: {c} artikel")

    print("\nSTATUS TERKAIT KEMENPERIN:")
    for tk, c in df_final["Terkait Kemenperin"].value_counts().items():
        print(f"  {tk}: {c} artikel")
    print("=" * 50)


if __name__ == "__main__":
    main()
