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
- **Karakteristik Aliran Berita Industri Agro: Pola "Bursty" Berbasis Event & Penyesuaian Pipeline**:
  - **Temuan Data Referensi Pusdatin (10–17 September 2026, 1.655 baris total, 54 baris Unit Eselon "IA"/Industri Agro)**:
    1. **Pola Aliran Berita Bersifat "Bursty" (Bukan Bug Pipeline)**:
       - 4 dari 8 hari sample referensi (50%) memiliki **0 artikel Industri Agro sama sekali**.
       - Sebanyak 87% (47 dari 54 baris) liputan Industri Agro terkonsentrasi pada hari-hari diselenggarakannya event/pameran industri besar (khususnya *Fi Asia Indonesia 2026*).
       - Volume berita harian yang rendah (0 sampai sedikit artikel) pada hari tanpa agenda pameran/kebijakan besar adalah **kondisi riil dan representatif di industri**, bukan tanda kegagalan scraping atau bug pipeline.
    2. **Perubahan Strategi Deduplikasi: Dari "Hapus Duplikat" Menjadi "Kelompokkan Duplikat" (Kolom `Isu`)**:
       - Sebanyak 41 dari 54 baris Industri Agro di data referensi merupakan liputan sindikasi dari SATU siaran pers yang sama (kunjungan Wamenperin di Fi Asia 2026).
       - Pusdatin **TIDAK menghapus** sindikasi ini menjadi 1 baris karena jumlah media peliput merupakan metrik *exposure/reach* esensial dalam media monitoring pemerintah.
       - Seluruh baris sindikasi dipertahankan dan dikelompokkan dengan nilai seragam pada kolom baru `Isu` (mengambil judul artikel paling representatif/lengkap di kelompok tersebut).
       - Deduplikasi URL persis sama (`exact duplicate link`) tetap dibuang sebagai duplikat teknis.
    3. **Deteksi Event & Pameran Industri Agro Tahunan**:
       - Ditambahkan daftar `INDUSTRY_EVENT_KEYWORDS` di `config.py` (*Fi Asia Indonesia*, *Trade Expo Indonesia*, *SIAL InterFOOD*, *Food & Hotel Indonesia*, *AllPack Indonesia*, *IFFINA*, *Indo Livestock*, *Agrinex Expo*).
       - Pencarian event ini dijalankan berkala berdampingan dengan 48 komoditas untuk menangkap lonjakan liputan publikasi pameran.
    4. **Pelonggaran `is_promotional()` Khusus Partisipasi Brand di Pameran Industri Resmi**:
       - Konten promosi ritel/supermarket konsumen langsung (diskon, katalog JSM, voucher, cashback, syarat dan ketentuan berlaku) tetap dibuang ketat.
       - Konten partisipasi brand/perusahaan di pameran industri resmi (pola `"[Brand] Hadir di [Event]"`, `"[Brand] Perkenalkan [Produk] di [Pameran]"`) diloloskan sebagai berita industri relevan sesuai standar Pusdatin.
    5. **Pembaruan Keyword Spesifik Komoditas & Institusi Baru**:
       - **Gula**: Keyword `"gula"` standalone dihapus permanen untuk mencegah noise resep/kesehatan non-industri, digantikan dengan grup query presisi `"gula rafinasi"` OR `"industri gula rafinasi"`.
       - **Institusi Baru (Akademi Komunitas Bambu)**: Ditambahkan keyword institusi `"akademi komunitas bambu kemenperin"` (frasa langsung) di `config.py` dan `keyword_kemenperin.csv`. Terverifikasi sebagai program strategis binaan Ditjen Industri Agro (bekerja sama dengan BDI Denpasar) untuk pencetakan Master Bambu dan pusat logistik industri bambu nasional, dengan pemetaan otomatis `Unit Eselon` = `"IA"` dan `Terkait Kemenperin` = `"Ya"`.
    6. **Pergantian Menteri Perindustrian (Reshuffle Kabinet 1 Oktober 2026 & Sertijab 2 Oktober 2026)**:
       - **Menteri Aktif**: Muhammad Sarmuji resmi dilantik Presiden Prabowo Subianto sebagai Menteri Perindustrian pada Kamis, 1 Oktober 2026 menggantikan Agus Gumiwang Kartasasmita. Serah terima jabatan (sertijab) dilaksanakan pada Jumat, 2 Oktober 2026.
       - **Mantan Menteri**: Agus Gumiwang Kartasasmita dicatat sebagai entri terpisah *"Mantan Menteri Perindustrian (hingga 1 Oktober 2026)"* di `keyword_nama.xlsx` agar artikel retrospektif/evaluasi kinerja tetap dapat terdeteksi tanpa terhapus.
       - **Pencarian Presisi & Entity Mapping**:
         - `pejabat_keyword_mapping.csv` memperbarui posisi Menteri kepada Muhammad Sarmuji dipasangkan ke seluruh 48 komoditas agro.
         - `entity_mapper.py` dan `config.py` mendeteksi alias wajar (`Muhammad Sarmuji`, `Menperin Sarmuji`, `Menteri Perindustrian Sarmuji`, `M. Sarmuji`, `Sarmuji`) dan memetakannya ke `Spokesperson 1/2` serta `Unit Eselon` = `"MENTERI"`.
         - Faisol Riza tetap menjabat sebagai Wakil Menteri Perindustrian.
     7. **Pembersihan Noise YouTube Shorts, Tabrakan Makna Kata (Pome & Teh), dan Penegakan Seragam Anti-Kriminal/Kecelakaan (6 Oktober 2026)**:
        - **YouTube Shorts & Entertainment Noise (is_shorts_entertainment_noise)**:
          - Deteksi 3+ hashtag, atau kombinasi tag hiburan pendek (#shorts, #fyp, #viral, #trending, #shortvideo) tanpa kata format berita formal (nama media/institusi resmi atau kata kerja jurnalistik seperti *resmikan, umumkan, laporkan, capai, targetkan*).
          - Tolak konten gaming/meme/lucu/hewan (#roblox, #minecraft, smackdown, lucu, kocak, prank).
          - Ambang is_industry_policy_topic() khusus sumber YouTube dinaikkan menjadi minimal 3 sinyal industri (ind_score >= 3).
        - **Tabrakan Kata 'Pome' vs Anjing Pomeranian (is_pome_context_valid)**:
          - Keyword pome wajib memuat konteks industri limbah/sawit/biogas/pabrik/pengolahan/CPO/EBT di judul atau teks.
          - Tolak mutlak jika disertai kata anjing, pomeranian, pet, puppy, cute, suplemen permen gummy, atau musik beat producer.
        - **Tabrakan Kata 'Teh' vs Lagu 'Teh Hijau' (is_teh_context_valid)**:
          - Tolak artikel/video bertema lagu/musik/penyanyi (Tulus, cover, singing battle, DJ teh, remix, AMI Awards, chord gitar, dsb) atau sapaan honorifik Sunda ('Teh Novi', dsb) tanpa konteks industri perkebunan/daun/pabrik teh.
        - **Penegakan Seragam Anti-Kriminal/Kecelakaan ke Semua Sumber (is_crime_accident_noise)**:
          - Diterapkan sama rata ke seluruh sumber data (RSS, YouTube, Exa, Serper).
          - Kamus sinyal diperluas mencakup Densus 88, teroris, tabrakan beruntun, kecelakaan fatal, penipuan bilyet giro kosong, razia miras, satwa liar (ular piton), dan mistis/hantu.
          - Menggunakan boundary matching kata utuh (regex laka) agar tidak salah mendeteksi nama daerah sentra industri seperti *Kolaka* (sentra kakao Sultra).
          - Pengecualian khusus: penindakan rokok ilegal dan pita cukai oleh Bea Cukai / DJBC tetap dilindungi dan diloloskan sebagai bagian dari pemantauan hasil tembakau Ditjen Industri Agro.
     8. **Keputusan Scope Industri Nasional vs Penegakan Ritel Lokal & Katalog Lengkap Pola Noise (6 Oktober 2026)**:
        - **Keputusan Scope Monitoring**:
          - Fokus pipeline adalah **INDUSTRI MANUFAKTUR & KOMODITAS AGRO** (produksi nasional, kapasitas pabrik, investasi industri, ekspor-impor, hilirisasi, pasokan bahan baku, dan regulasi/kebijakan formal Kemenperin).
          - Seluruh berita **PENEGAKAN HUKUM RITEL LOKAL & KETERTIBAN UMUM DAERAH** ditetapkan sebagai **DI LUAR SCOPE** (Satpol PP menyegel toko eceran/kios, pansus/raperda pengendalian miras DPRD kota/kabupaten, moratorium perizinan Rumah Hiburan Umum/RHU/diskotek, dan pengawasan izin karaoke).
          - **Pengecualian Mutlak**: Razia rokok ilegal, penindakan rokok tanpa pita cukai, dan operasi Gempur Rokok Ilegal oleh Direktorat Jenderal Bea dan Cukai (DJBC) / Kemenkeu **TETAP DIPERTAHANKAN** sebagai bagian penting dari monitoring ekosistem Industri Hasil Tembakau (IHT) Ditjen Industri Agro.
        - **Katalog Lengkap Pola Noise yang Berhasil Diidentifikasi & Ditangkal**:
          1. **Title Placeholder, Error & Artifact Web (`is_placeholder_or_error_title`)**:
             - Software katalog perpustakaan OPAC/VuFind Kemendikdasmen: *"Resource discovery - Katalog Induk Kemendikdasmen"*.
             - Sistem Informasi Penelusuran Perkara Pengadilan Negeri: *"SIPP"*.
             - Sistem e-procurement pengadaan tender ESDM/DKI: *"Informasi Paket"* (SPSE INAPROC) dan e-Order BPPBJ DKI.
             - Portal repositori/indeks akademik: *"Garba Rujukan Digital"*, *"ICGAB 2026"*, *"Beranda"* Pustaka Bapanas.
             - Hasil pencarian peraturan: *"62.484 Peraturan ditemukan"* (`peraturan.go.id`).
             - Katalog toko & Flash sale: Kasur pegas Alga Ellery/Jullie/Nara Chandra Karya, biskuit Lotte Grosir, buku tulis SIPLah Intan Pariwara.
             - Lowongan kerja & direktori: *"Staff Teknisi AMDK"* Jobrapido, *"Daftar UMKM Babel"*, *"SimPONI SUMUT"*.
          2. **Penegakan Hukum Ritel Lokal (`is_local_retail_enforcement`)**:
             - Penyegelan toko miras/eceran oleh Satpol PP (Surabaya, Padang, Wonokromo, Padang).
             - Raperda pembatasan/pengendalian miras oleh DPRD Kota/Kabupaten (Surabaya, Purbalingga, Buol).
             - Moratorium RHU / izin diskotek baru oleh Walikota Surabaya.
             - Pengawasan tempat karaoke oleh Satpol PP Tulang Bawang.
             - Pemusnahan barang kedaluwarsa toko oleh Satpol PP Nunukan.
          3. **Kamtibmas & Kegiatan Kepolisian Lokal Non-Industri (`is_crime_accident_noise`)**:
             - Patroli dialogis & Jumat curhat Polsek (seperti Polsek Pangkalan Susu di Langkat yang terseret keyword *susu*).
             - Patroli dialogis polisi di warung kopi / warung makan.
             - Pengamanan turnamen olahraga (basket DBL Kopi Goodday Polresta Sleman).
             - Penindakan miras arak/trobas kriminal umum oleh Polres Malang/Kaur/Ngampilan.
             - Patroli skala besar Brimob di perkebunan PT PAL.
             - Kriminal murni (pembunuhan di kebun kopi, penggelapan kakao non-industri).
          4. **Rekreasi Wisata, Tiket Masuk, Kafe & Resep (`is_lifestyle_tourism_noise`, `is_recipe`)**:
             - Destinasi wisata edukasi anak & ulasan tiket masuk (Kampung Coklat Blitar, Festival Nyusu Bareng Brau Batu).
             - Ulasan kedai kafe & nongkrong (OSMA Osmanthus Tea Solo, Library Cafe Bandung, Kedai Kopi Bah Sipit, Catra Kopi Batang).
             - Tips kuliner memasak/meracik (tips bawang goreng kriuk maizena, cara seduh kopi nikmat).
          5. **Blog & Esai Pribadi Platform UGC (`is_personal_blog_noise`)**:
             - Catatan perjalanan hiking (Tektok Part 2 Bukit Lincing).
             - Curhat personal & kenangan (Ketika Kebahagiaan Cukup Segelas Kopi, Bapak Orang Pertama Mengenalkanku Kopi, Bosan Nunggu Kerja Mending Bisnis Rumahan).
             - Esai lepas non-kebijakan (Tiga Buah Kakao & Wajah Keadilan, LIRA playdate Boyolali, Mahasiswa UNNES Cegah CVS).
          6. **Drama Medsos Viral Tanpa Konteks Kebijakan (`is_viral_social_media_drama`)**:
             - Video kontroversi pejabat/bupati viral di medsos (kasus Bupati Siak) yang terseret tag komoditas daerah tanpa substansi harga/pabrik/hilirisasi.
          7. **Pola Struktural Murah Tanpa AI (Tahap 1 Pre-AI)**:
             - **Deteksi Nomor HP / WA di Judul (`has_phone_number_or_wa_in_title`)**: Regex nomor HP 08xx / +628xx atau prefix WA/Telp (listing bisnis / iklan baris, e.g. *"Search - WA 0859 3970 0884 [[Hatiga Furniture]]"*).
             - **Deteksi Halaman Placeholder Agregator (`is_aggregator_placeholder_title`)**: Judul berpola *"Berita Terbaru Hari Ini - {topik}"*, *"Berita Terkini - {topik}"*, *"Kumpulan Berita {topik}"*, *"Tag: {topik}"*.
             - **Deteksi Halaman Galeri Foto / Stock Image (`is_photo_stock_gallery_noise`)**: Judul berpola *"{angka}+ Foto ... Pictures, Gambar dan Background untuk Unduh Gratis"* atau memuat *"stock photo"*, *"download gratis"*.
             - **Deteksi Campaign Donasi / Crowdfunding (`is_donation_campaign_noise`)**: Judul diawali *"Campaign -"* atau memuat *"wujudkan renovasi musholla"*, *"galang dana"*, platform Kitabisa, sedekah, dsb.
             - **Deteksi Profil Sekolah / Direktori Pendidikan Statis (`is_static_educational_profile_noise`)**: Judul berpola nama sekolah (*"SMK Negeri X"*, *"SMA..."*, *"Universitas..."*) tanpa kata kerja berita formal (*"resmikan"*, *"gelar"*, *"umumkan"*, dst).
             - **Katalog Ritel / Toko Alat Rumah Tangga (`is_promotional`)**: Judul berpola *"Toko Alat Rumah Tangga..."* tanpa konteks industri manufaktur.
             - **Idiom Kertas (`is_kertas_context_valid`)**: Frasa kiasan non-komoditas (*"Di Atas Kertas Semua Setara"*).
        - **Penonaktifan Sementara YouTube**:
          - Flag `ENABLE_YOUTUBE = False` (default) di `config.py` membungkus seluruh pemanggilan YouTube search dan channel crawling. 133 baris YouTube disisihkan dari dataset akhir hingga siap diaktifkan kembali.
        - **Hasil Dataset Final Periode 1–4 Oktober 2026**:
          - Total awal: 768 baris.
          - Total dibuang: 242 baris (133 YouTube dinonaktifkan + 109 baris noise non-industri, ritel lokal, placeholder, kamtibmas, rekreasi, blog, dan drama medsos).
          - **Total bersih final: 526 baris**, tersimpan di:
            - `hasil_scrapping/2026-10-01_sd_2026-10-04/all_2026-10-01_sd_2026-10-04.xlsx`
            - `hasil_scrapping/2026-10-01_sd_2026-10-04/all_2026-10-01_sd_2026-10-04_terbaru.xlsx`
            - `hasil_scrapping/2026-10-01_sd_2026-10-04/progress.json`
          - **Hasil audit komprehensif ke 526 baris akhir: 0 noise tersisa**, 100% berita relevan kebijakan & industri agro.

