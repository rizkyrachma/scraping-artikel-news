# agents.md — Konteks untuk Antigravity

## Tujuan Proyek

Membangun pipeline scraping berita industri dari Google, lalu mengekstrak tone sentimen dan spokesperson, dan mengekspor hasilnya ke file Excel.

Baca `DOKUMEN_TEKNIS_PIPELINE_SCRAPING_BERITA.md` dulu sebelum mulai coding. Dokumen itu adalah sumber kebenaran untuk arsitektur, jangan menyimpang dari strategi filtering domain yang sudah dijelaskan di sana kecuali ada alasan teknis yang jelas.

## Aturan Kerja untuk Agent

1. Jangan gunakan Google Custom Search JSON API sebagai sumber utama. API itu sudah ditutup untuk pelanggan baru dan akan berhenti total 1 Januari 2027. Gunakan Google News RSS (`feedparser`) sebagai sumber utama, dan crawling langsung ke domain `.go.id` sebagai pelengkap.
2. Implementasi harus modular sesuai struktur folder di dokumen teknis (`config.py`, `query_builder.py`, `fetch_news.py`, `extract_content.py`, `entity_mapper.py`, `sentiment.py`, `export_excel.py`, `main.py`). Jangan menggabungkan semua logika ke satu file besar.
3. Setiap fungsi yang melakukan HTTP request harus punya delay/backoff, jangan spam request ke situs media secara paralel tanpa batas.
4. Filter domain harus dilakukan dua kali: sekali di query (Google dork), sekali lagi di kode Python setelah hasil didapat (post-filter dengan `urlparse`). Jangan hanya mengandalkan salah satu.
5. Kolom Excel wajib persis: `Tanggal`, `Title`, `Link Website`, `Media Name`, `Tone`, `Spokesperson 1`, `Spokesperson 2`, `Unit Eselon`, `Terkait Kemenperin`, `Keywords`. Urutan kolom harus konsisten dengan urutan ini.
6. Sebelum mengklaim sentiment classifier "akurat", jalankan validasi manual pada sample kecil (50-100 artikel) dan laporkan hasilnya. Jangan asumsikan akurasi model publik tanpa pengecekan.
7. Sumber data spokesperson sekarang adalah `keyword_nama.xlsx` (bukan lagi `keyword_nama.txt`), dengan dua kolom terstruktur: `nama` dan `jabatan`. Baca file ini dengan `pandas.read_excel()`. Kalau ke depannya ada file baru lagi yang menggantikan ini, update baris ini juga supaya tidak ada modul yang masih merujuk ke sumber data yang sudah tidak dipakai.
8. Setiap perubahan besar pada strategi query/filtering harus dicatat sebagai perubahan di bagian "Riwayat Perubahan" di bawah, supaya iterasi berikutnya (manusia atau agent lain) tahu konteksnya.
9. Seluruh output scraping (file final `all_<tanggal>.xlsx`, `progress.json`, dan checkpoint) wajib disimpan di dalam folder tanggal evaluasi masing-masing (`hasil_scrapping/<YYYY-MM-DD>/`) via `get_date_folder()`. Dilarang menyimpan file output langsung di root `hasil_scrapping/`, dan dilarang menimpa file tanggal yang sudah ada secara destruktif (selalu gunakan merge dedup URL dan resume checkpoint).

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
- Penambahan `JOB_PORTAL_BLOCKLIST` dan `JOB_URL_PATTERNS` di `config.py` dan `fetch_news.py`, serta fungsi `is_job_posting()` di `relevance_filter.py` dan `main.py` untuk mengeliminasi noise lowongan kerja / karir (Glints, KitaLulus, BeBee, LinkedIn Jobs, dll.).
- Penambahan filter makna ganda komoditas non-industri (`is_kelapa_context_valid`, `is_karet_context_valid`, `is_kakao_context_valid`, `is_kertas_context_valid`) di `relevance_filter.py` untuk membuang false positive seperti "LRT Kelapa Gading", idiom "Jam Karet", evakuasi kecelakaan kapal dengan perahu karet, dan entitas K-Pop "Kakao Entertainment".
- Penambahan rate limiting thread-safe, mutex lock, dan in-memory caching di `resolve_article_url()` (`extract_content.py`) untuk mencegah HTTP 429 Too Many Requests dari Google News decoder saat scraping batch skala besar.
- **Integrasi Alternatif Serper.dev (`serper_search.py`)**:
  - Penambahan modul `serper_search.py` sebagai alternatif sumber pencarian berita saat Google News RSS terkena rate limit atau CAPTCHA gate.
  - Endpoint: `https://google.serper.dev/news` via header `X-API-KEY`. Mengembalikan format data yang identik dengan `fetch_news.py` (`title`, `link`, `published`, `media_name`), sehingga kompatibel langsung dengan seluruh modul pipeline (ekstraksi, filter, sentimen, dan ekspor).
  - Tautan yang dikembalikan oleh Serper adalah direct publisher URL (bukan tautan redirect Google News), sehingga proses ekstraksi teks sama sekali tidak memerlukan resolusi decoder (`googlenewsdecoder` / `batchexecute`), bebas risiko pemblokiran Google.
  - Kuota Serper gratis terbatas (2.500 query sekali pakai, lifetime tanpa reset bulanan). Karena itu Serper.dev strictly dihemat dan hanya diaktifkan saat Google News RSS terblokir via flag `USE_SERPER_ONLY=True` atau argumen `--serper-only`.
- **Kronologi Insiden CAPTCHA Gate (15 September 2026, Mulai 11:00 WIB)**:
  - Pada pukul 11:00 WIB saat eksekusi Batch 7, IP jaringan kantor (`202.47.80.21`) mengalami redirect ke `google.com/sorry/index` (CAPTCHA gate) akibat akumulasi request `batchexecute` oleh `googlenewsdecoder`.
  - Batch 1–6 (29 keyword) dan 5 keyword besar telah tersimpan aman dengan total 171 baris berita bersih di `hasil_scrapping/hasil_scraping_semua_keyword_clean.xlsx`.
  - Monitoring polling otomatis tiap 10 menit dihentikan sepenuhnya agar IP kantor benar-benar istirahat dari traffic Google dan tidak memperpanjang masa blokir.
- **Pembaruan Deduplikasi Lintas Keyword (`dedup_across_keywords`)**:
  - Penambahan fungsi `merge_keywords()` dan `dedup_across_keywords()` di `fetch_news.py` dan `run_all_batches.py`.
  - Sebelumnya, jika artikel yang sama muncul pada beberapa keyword yang berbeda (baik lewat kemiripan URL maupun skor judul `rapidfuzz` >= 85), sistem hanya menyimpan keyword yang pertama kali ditemukan dan membuang keyword berikutnya.
  - Logika baru secara otomatis menggabungkan (*merge*) seluruh keyword yang cocok untuk artikel yang sama menjadi format daftar unik dipisahkan koma (contoh: `"gula, kelapa"`, `"cokelat, kakao"`, `"cpo, minyak sawit"`).
- **Integrasi Exa Search sebagai Sumber Pelengkap Permanen (`exa_search.py`)**:
  - Exa Search API diintegrasikan sebagai sumber berita pelengkap permanen (BUKAN pengganti Google News RSS) dengan batasan ketat:
    1. **Hanya Keyword Satu Kata**: Otomatis dicek via `is_single_word_keyword()` di `config.py` (panjang split == 1, contoh: "gula", "karet", "kakao"). Keyword frasa 2+ kata (seperti "industri agro", "makanan dan minuman") tetap hanya diproses via RSS karena hasil uji banding membuktikan Exa tidak efektif untuk frasa multi-kata.
    2. **Filter Domain Indonesia Ketat**: Hanya menerima URL yang domainnya berakhiran `.id` atau `.co.id` (`is_allowed_id_domain()`). Seluruh domain lain (`.com`, `.org`, `.net`, TLD negara lain seperti `.mx`, `.ar`) dibuang untuk mengeliminasi noise situs luar negeri dan web spam.
    3. **Konservasi Kredit API**: Menggunakan keyword search standar (`type: "keyword"` non-agent/deep, `num_results=25`) dengan batas tanggal tepat kemarin. Karena kuota kredit terbatas, dilarang menjalankan tes berulang tanpa kebutuhan jelas.
    4. **Kolom Baru 'Sumber Data'**: Penambahan kolom `"Sumber Data"` (bernilai `"RSS"`, `"Exa"`, atau `"Serper"`) di posisi paling akhir kolom Excel (`export_excel.py`) untuk keperluan audit asal data.
    5. **Penerapan Filter Seragam**: Seluruh rantai filter konten (`min_length`, anti-loker, override Ditjen Agro, topik utama, anti-resep, anti-iklan ritel, rasio industri vs kesehatan, dan dedup kemiripan judul) diterapkan sama rata tanpa perlakuan khusus.
- **Struktur Folder Output Terorganisir per Tanggal Evaluasi**:
  - Seluruh output pipeline tidak lagi disimpan langsung di root `hasil_scrapping/`, melainkan dipartisi ke dalam subfolder tanggal: `hasil_scrapping/<YYYY-MM-DD>/`.
  - Fungsi `get_date_folder(target_date: date) -> str` di `config.py` dipanggil di awal proses (sebelum fetch keyword pertama) untuk membuat folder tanggal secara otomatis (`os.makedirs(folder, exist_ok=True)`).
  - Standar struktur subfolder:
    ```text
    hasil_scrapping/
    ├── 2026-09-14/
    │   ├── all_2026-09-14.xlsx          (file final gabungan hari itu)
    │   ├── progress.json                 (checkpoint keyword yang sudah selesai hari itu)
    │   └── checkpoint_<keyword>.xlsx     (checkpoint per keyword, jika dieksekusi parsial)
    ├── 2026-09-15/
    │   ├── all_2026-09-15.xlsx
    │   ├── progress.json
    │   └── checkpoint_<keyword>.xlsx
    └── 2026-09-16/
        └── ...
    ```
  - **Aturan Proteksi Data**:
    1. **Satu folder per tanggal**: Pemisahan tegas antar-tanggal evaluasi, mencegah file tertimpa atau bercampur baur antar-hari.
    2. **Resume Checkpoint Otomatis**: Sebelum memulai scraping tanggal tertentu, pipeline mengecek `hasil_scrapping/<tanggal>/progress.json`. Keyword yang sudah tercatat selesai akan di-skip otomatis.
    3. **Non-Destructive Merge**: File gabungan `all_<tanggal>.xlsx` menggunakan mode `merge_existing=True` di `save_to_excel()`. Data baru akan digabung ke file yang sudah ada dengan deduplikasi URL dan judul (`threshold=85`), tanpa menimpa data yang telah terkumpul sebelumnya.
    4. **Root Bersih**: Direktori root `hasil_scrapping/` steril dari file lepas (loose files), hanya berisi subdirektori berformat tanggal `YYYY-MM-DD`.
- **Perluasan Validasi Konteks Spesifik Komoditas & Eliminasi False Positive**:
  - `is_cokelat_context_valid`: membuang deskriptor warna (*amplop cokelat*, *baju cokelat*).
  - `is_tar_context_valid`: menyaring inisial merek non-rokok (akronim merek beras TAR) dan mewajibkan asosiasi istilah residu tembakau/rokok.
  - `is_teh_context_valid`: menyaring sapaan kehormatan Sunda (*Teh Cely*) dan lirik lagu pop.
  - `is_susu_context_valid`: menyaring istilah kedokteran gigi (*gigi susu*), metafora warna air (*kopi susu*), dan riset parodi *susu kecoa*.
  - `is_kopi_context_valid`: menyaring insiden disiplin sekolah (*kena skors*), akronim parenting *KOPI Aceh*, etiket makan, dan tips asam lambung.
  - `is_fame_context_valid`: menyaring penghargaan olahraga/hiburan (*Hall of Fame*) dan memastikan hanya merujuk pada *Fatty Acid Methyl Ester* / biofuel sawit.
  - `is_kertas_context_valid`: mewajibkan istilah industri manufaktur kertas/pulp dan membuang penggunaan non-industri (*uang kertas*, *tiket kertas*, *wayang kertas*, *ujian kertas*).
  - `is_foreign_noise_domain`: menyaring domain luar negeri non-relevan (`.vn`) yang mengindeks artikel lokal Vietnam dalam bahasa Indonesia otomatis.
- **Pembaruan Skema Monitoring Terstruktur "Kompilasi Data Monitoring Media Massa"**:
  - Database Pejabat diperluas menjadi 13 pejabat di `keyword_nama.xlsx` dengan kolom terstruktur: `nama`, `jabatan`, `unit_eselon`, `kategori`, dan `level`.
  - Pemisahan keyword umum Kemenperin (`keyword_kemenperin.csv`) dan 46 keyword komoditas Ditjen Industri Agro (`keyword_topik_ia.csv` dan `keyword_data.txt`).
  - Penambahan kolom baru di skema Excel dan DataFrame:
    `Tanggal`, `Title`, `Link Website`, `Media Name`, `Category Group`, `Category`, `Unit Eselon`, `Spokesperson 1`, `Spokesperson 2`, `Tone`, `Keterangan Tone`, `Terkait Kemenperin`, `Keywords`, `Sumber Data`.
  - Logika Tagging Otomatis:
    1. **Terkait Kemenperin** = `"Ya"` jika menyebut keyword umum Kemenperin, pejabat di database, atau topik industri agro yang memiliki konteks industri/kebijakan (membuang resep masakan & isu kesehatan pribadi lewat heuristik filter).
    2. **Category Group**: `"Kemenperin"` jika menyebut institusi/pejabat Kemenperin, `"PReskripsi"` jika membahas topik industri manufaktur/agro umum tanpa menyebut Kemenperin secara langsung.
    3. **Unit Eselon**: Diambil dari database pejabat (`IA`, `IKFT`, `ILMATE`, `IKMA`, `KPAII`, `MENTERI`, `WAMEN`, `SETJEN`, `ITJEN`) atau `"IA"` untuk topik komoditas agro.
    4. **Spokesperson 1 & 2**: Diurutkan berdasarkan **kemunculan pertama** nama/alias pejabat di dalam teks artikel.
    5. **Category**: Mapping unit eselon (`IA` -> `"03. Industri Agro"`, `MENTERI`/`WAMEN`/`SETJEN`/`ITJEN` -> `"01. Kementerian Perindustrian"`, dst.).
    6. **Tone & Keterangan Tone**: Sentimen rule-based 3 kelas (`Positif`, `Netral`, `Negatif`) dilengkapi kolom keterangan `"Estimasi Otomatis (Dapat Direvisi Manual)"`.
  - Formatting Hyperlink Excel: Kolom `Link Website` menggunakan relasi hyperlink aktif OOXML dengan styling biru `#0563C1` dan single underline (`Font(color="0563C1", underline="single")`).






