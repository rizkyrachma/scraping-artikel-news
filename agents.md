# agents.md — Konteks untuk Antigravity

## Tujuan Proyek

Membangun pipeline scraping berita industri dari Google, lalu mengekstrak tone sentimen dan spokesperson, dan mengekspor hasilnya ke file Excel.

Baca `DOKUMEN_TEKNIS_PIPELINE_SCRAPING_BERITA.md` dulu sebelum mulai coding. Dokumen itu adalah sumber kebenaran untuk arsitektur, jangan menyimpang dari strategi filtering domain yang sudah dijelaskan di sana kecuali ada alasan teknis yang jelas.

## Aturan Kerja untuk Agent

1. Jangan gunakan Google Custom Search JSON API sebagai sumber utama. API itu sudah ditutup untuk pelanggan baru dan akan berhenti total 1 Januari 2027. Gunakan Google News RSS (`feedparser`) sebagai sumber utama, dan crawling langsung ke domain `.go.id` sebagai pelengkap.
2. Implementasi harus modular sesuai struktur folder di dokumen teknis (`config.py`, `query_builder.py`, `fetch_news.py`, `extract_content.py`, `entity_mapper.py`, `sentiment.py`, `export_excel.py`, `main.py`). Jangan menggabungkan semua logika ke satu file besar.
3. Setiap fungsi yang melakukan HTTP request harus punya delay/backoff, jangan spam request ke situs media secara paralel tanpa batas.
4. Filter domain harus dilakukan dua kali: sekali di query (Google dork), sekali lagi di kode Python setelah hasil didapat (post-filter dengan `urlparse`). Jangan hanya mengandalkan salah satu.
5. Kolom Excel wajib persis: `Tanggal`, `Title`, `Link Website`, `Media Name`, `Tone`, `Spokesperson 1`, `Spokesperson 2`, `Unit Eselon`, `Terkait Kemenperin`. Urutan kolom harus konsisten dengan urutan ini.
6. Sebelum mengklaim sentiment classifier "akurat", jalankan validasi manual pada sample kecil (50-100 artikel) dan laporkan hasilnya. Jangan asumsikan akurasi model publik tanpa pengecekan.
7. Sumber data spokesperson sekarang adalah `keyword_nama.xlsx` (bukan lagi `keyword_nama.txt`), dengan dua kolom terstruktur: `nama` dan `jabatan`. Baca file ini dengan `pandas.read_excel()`. Kalau ke depannya ada file baru lagi yang menggantikan ini, update baris ini juga supaya tidak ada modul yang masih merujuk ke sumber data yang sudah tidak dipakai.
8. Setiap perubahan besar pada strategi query/filtering harus dicatat sebagai perubahan di bagian "Riwayat Perubahan" di bawah, supaya iterasi berikutnya (manusia atau agent lain) tahu konteksnya.

## Cara Menjalankan

```bash
pip install feedparser trafilatura newspaper3k rapidfuzz transformers torch pandas openpyxl

# Eksekusi untuk 1 keyword (contoh: gula):
python main.py gula

# Eksekusi batch seluruh keyword (disimpan ke hasil_scrapping/hasil_scraping_berita_lengkap.xlsx):
python main.py --all
```

Catatan: `openpyxl` dipakai dua arah, sebagai engine baca `keyword_nama.xlsx` (lewat `pandas.read_excel`) dan sebagai engine tulis file Excel. Seluruh output file Excel otomatis tersimpan di dalam folder `hasil_scrapping/`.

## Riwayat Perubahan

- Sumber data spokesperson diganti dari `keyword_nama.txt` (format kalimat bebas) menjadi
  `keyword_nama.xlsx` (format terstruktur, kolom `nama` dan `jabatan`). Parsing manual
  regex/split di `load_spokesperson_map()` tidak lagi diperlukan, cukup `pandas.read_excel()`.
- Strategi domain filtering diubah dari allowlist-first (`MEDIA_ALLOWLIST`) menjadi denylist-first (`MARKETPLACE_BLOCKLIST`, `ASSET_HOST_BLOCKLIST`, `ASSET_EXTENSION_BLOCKLIST`). Hal ini memperluas cakupan media nasional dan lokal (long-tail media), dengan tetap menyaring e-commerce dan file aset non-artikel.
- Penambahan `SOCIAL_MEDIA_BLOCKLIST` (YouTube, Instagram, TikTok, Wikipedia, X/Twitter, Facebook) untuk membuang platform non-berita dari hasil scraping.
- Penambahan modul `relevance_filter.py` (filter relevansi berbasis judul dengan `is_likely_relevant()`) untuk membuang artikel kesehatan/gaya hidup (misal gula darah, diabetes) yang tidak memuat konteks industri/ekonomi pada tahap fetch.
- Perbaikan bug substring matching: seluruh pencocokan kata/nama di `relevance_filter.py`, `entity_mapper.py`, dan domain checking di `fetch_news.py` beralih ke regex word boundary (`\b...\b`) dan exact/subdomain match untuk mencegah false match (misal kata 'gula' mencocokkan 'regulasi', nama 'agus' mencocokkan 'bagus').
- Perluasan filter di `relevance_filter.py` dan `main.py` dengan deteksi `is_recipe` (membuang konten resep kuliner berformat takaran bahan) dan `is_promotional` (membuang materi iklan/promo ritel supermarket).
- Penambahan filter wajib content-level `contains_keyword_in_content(text, keyword)` di `relevance_filter.py` dan `main.py` menggunakan regex word boundary `\b...\b` untuk membuang artikel hasil ekstraksi yang sama sekali tidak memuat kata kunci topik (misal halaman portal umum / noise .go.id).
- Pembaruan klasifikasi tone di `sentiment.py` menjadi 3 kelas asli IndoBERT (`Positif`, `Netral`, `Negatif`) tanpa pemaksaan mapping netral ke biner, selaras dengan skema data monitoring manual.
- Penambahan deduplikasi berbasis kemiripan judul (`is_near_duplicate_title` threshold >= 85, `rapidfuzz.fuzz.ratio`) di `fetch_news.py` dan `main.py` untuk mengeliminasi artikel ganda/sindikasi dengan menyimpan versi yang isi teksnya lebih lengkap/panjang.
- Peningkatan filter konten menjadi filter frekuensi topik utama (`is_keyword_primary_topic` di `relevance_filter.py` dan `main.py`): artikel lolos hanya jika keyword muncul di judul ATAU muncul minimal 2 kali di isi teks artikel, membuang artikel yang hanya menyebut keyword 1 kali (misal daftar sembako/bantuan sosial).
- Penambahan filter topik industri/kebijakan vs kesehatan/nutrisi pribadi (`is_industry_policy_topic()` di `relevance_filter.py` dan `main.py`) berbasis perbandingan kemunculan `INDUSTRY_POLICY_SIGNALS` vs `HEALTH_PERSONAL_SIGNALS` untuk membuang artikel nutrisi, diet, dan penyakit personal.
- Pemisahan `Media Name` dari `Title` dan penambahan kolom `Media Name` di skema ekspor Excel (di antara `Link Website` dan `Tone`). Ekstraksi nama media mengandalkan field terstruktur `entry.source.title` dari feedparser, dan suffix ` - <Media Name>` pada raw title dibersihkan tanpa rsplit sembarangan, menjaga nama media yang mengandung tanda hubung (seperti 'DINAS PERPUSTAKAAN DAN KEARSIPAN - Kabupaten Sidoarjo') tetap utuh.
- Pengalihan direktori penyimpanan output Excel ke folder `hasil_scrapping/` (auto-create dengan `os.makedirs(exist_ok=True)`), tidak lagi mengotori direktori root.
- Penambahan filter tanggal publikasi dinamis (`get_date_range()` dan `is_published_yesterday()` di `config.py` dan `main.py`): artikel yang lolos ekspor hanya yang tanggal rilisnya persis sama dengan 'kemarin' (H-1 dari hari eksekusi) untuk menyaring arsip dokumen lama di domain pemerintah (.go.id).
- Penerapan OPSI B untuk sinyal Kemenperin: `is_kemenperin_related()` tidak lagi membuang artikel, melainkan berfungsi sebagai penanda/flagging dengan kolom baru `Terkait Kemenperin` ("Ya" / "Tidak") di akhir kolom Excel (`export_excel.py`). Seluruh berita industri tanggal kemarin tetap tersimpan lengkap.
- Penambahan penanganan timeout toleran 20 detik dan retry 2x khusus untuk domain `.go.id` di `extract_content.py` (`fetch_gov_html_with_retry()`) untuk mengatasi server portal daerah/pemerintah yang lambat merespons.
- Penanganan limit 100 entri Google News RSS: Query media (`build_media_query`) dan query pemerintah (`build_gov_query`) dijalankan terpisah, masing-masing membawa hingga 100 entri (total hingga ~200 entri unik sebelum dedup URL). Keterbatasan 100 entri per query adalah batasan arsitektur RSS Google News.




