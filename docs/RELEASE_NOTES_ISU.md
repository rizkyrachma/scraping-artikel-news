# Release Notes: Pengelompokan Isu & Klasifikasi Tone Biro Humas

Dokumen ini merangkum perubahan fitur pengelompokan isu (Fase 1), klasifikasi satu tone per isu berbasis indikator Biro Humas Kemenperin (Fase 2), integrasi dashboard & workflow GitHub Actions (Fase 3), serta prosedur merge, pemantauan, dan rollback.

---

## 1. Apa yang Berubah untuk Pengguna dan Dashboard

### Pipeline & Output Excel (`main.py`, `src/export_excel.py`, `src/direct_crawl_kemenperin.py`)
- **Direct crawl portal rilis resmi**: `main.py` kini mengambil siaran pers dari `https://www.kemenperin.go.id/siaran-pers` melengkapi `https://agro.kemenperin.go.id/` sebagai sumber judul isu rilis resmi.
- **Kolom Excel baru (opsional/aditif)**: sheet `Berita` menambahkan dua kolom baru, **`Isu`** dan **`Alasan Tone`**, tanpa menghapus atau mengubah nama kolom lama.
- **Pengelompokan isu (`src/isu_grouping.py`)**: berita harian dicocokkan terlebih dahulu ke rilis resmi Kemenperin, lalu sisanya dikelompokkan berdasarkan kemiripan konten ke dalam isu klaster dengan registri lintas-hari (`hasil_scrapping/isu_registry.json`, masa aktif klaster 14 hari).

### Sinkronisasi Data Dashboard (`scripts/sync_dashboard_data.py`)
- `articles_all.json` mengekspor tiga field opsional baru: `isu`, `alasan_tone`, dan `sumber_isu` (`"rilis"` / `"klaster"` bila tersedia).
- Seluruh field lama tetap dipertahankan dengan nama dan tipe yang sama; data historis tanpa kolom `Isu`/`Alasan Tone` tetap terbaca normal (nilai kosong/opsional).

### Tampilan Web Dashboard (`web/lib/types.ts`, `web/components/HalamanBerita.tsx`, `web/app/globals.css`)
- **Kartu berita**: menampilkan label isu ringkas dan `alasan_tone` sebagai teks bantu non-dominan; keduanya otomatis disembunyikan bila kosong (data lama tidak berubah).
- **Tinggi kartu default terjaga**: tinggi tetap `165px` pada data lama tanpa `isu`/`alasan_tone` dipertahankan; perluasan tinggi otomatis hanya diterapkan pada kartu yang memiliki informasi isu/alasan tone.
- **Mode "Kelompokkan per isu"**: berupa toggle dengan posisi **default MATI** sehingga pengalaman awal pengguna tidak berubah. Saat diaktifkan:
  - Menampilkan satu header per isu berisi nama isu, jumlah berita, daftar media, dan badge tone isu.
  - Filter tone dan kotak pencarian yang sudah ada tetap berfungsi di mode terkelompok.
  - Berita lama tanpa isu masuk ke grup **"Tanpa isu"** dengan teks netral `"Tone dinilai per berita"` (tanpa badge tone agregat), terlipat (collapsed) secara default bila besar, serta dipaginasi per 25 kartu agar halaman tetap ringan.
  - Tata letak telah diverifikasi pada viewport desktop dan mobile (`390x844`).

### Workflow GitHub Actions (`.github/workflows/daily_scrape.yml`, `scripts/isu_registry_state.py`)
- Menambahkan pemulihan dan penyimpanan atomik (`tempfile` + `os.replace`) untuk `hasil_scrapping/isu_registry.json` antar run di branch `data` (`pipeline_state/isu_registry.json` sebagai Lapis Utama) dengan cadangan `actions/cache` (Lapis Kedua).
- Klaster kedaluwarsa (`>14` hari terhadap `end_date`) otomatis dipangkas sebelum disimpan, dan penyimpanan hanya dijalankan jika scraping sukses (`steps.run_scraper.outcome == 'success'`).
- Menambahkan guard `github.ref == 'refs/heads/main'` pada seluruh langkah commit, push, dan persist `pipeline_state` sehingga run dari branch lain tidak dapat menulis ke `main` atau `data`.

---

## 2. Perubahan Perilaku Tone

### Pergantian Kerangka Aturan (`src/tone_classifier.py`)
- Prompt tone berubah dari `v2026-11-12-b` (penilaian berbasis kesan positif/negatif kondisi ekonomi industri) menjadi **`v2026-11-18-d`** (kerangka dua langkah Biro Humas Kemenperin: **Hubungan `K1–K4` × Arah `"mendukung" | "tidak ada" | "menyerang"`**).
- Fokus penilaian berpindah dari *"apakah angka/kondisi industri baik atau buruk"* menjadi **peran dan sikap pemberitaan terhadap Kemenperin** (`P1–P2`, `Ne1–Ne2`, `N1–N4`).
- Penilaian tone dilakukan **satu tone per isu** untuk konsistensi antar media yang meliput peristiwa yang sama (kecuali outlier yang jelas berbeda peristiwa atau berlawanan arah).

### Dampak Nyata: Kasus Isu Rokok Elektrik & Sheet `Ringkasan Negatif`
- Pada simulasi data 17 November 2026 (`hasil_scrapping/ulang_2026-11-17/Media_Monitoring_Agro_2026-11-17_ulang_resmi.xlsx`, 48 berita):
  - Klaster 5 berita *"Industri Rokok Elektrik Nasional Memohon Perlindungan Pemerintah untuk Menjaga Kelangsungan Usaha dan Tenaga Kerja"* (`detikFinance`, `Sumut Pos`, `Tirto.id`, `Harian Jogja`, `Index Sumut`) yang sebelumnya berpotensi dinilai **Negatif** (karena kata *ancaman/larangan/nasib pekerja*) kini dinilai **Netral** (`Ne2 + A2`: desakan asosiasi kepada "pemerintah" secara umum tanpa menyebut atau menyerang kebijakan Kemenperin).
  - Distribusi tone akhir 48 berita simulasi 17 Nov: **Positif = 10**, **Netral = 38**, **Negatif = 0**.
- **Dampak pada sheet `Ringkasan Negatif`**:
  - Jumlah berita yang masuk kategori `Negatif` akan turun drastis dibanding metodologi lama karena berita pelemahan industri, PHK, atau desakan umum ke pemerintah tanpa serangan ke Kemenperin kini menjadi `Netral`.
  - Pada simulasi 17 Nov `ulang_resmi`, sheet `Ringkasan Negatif` berisi **0 baris** (tidak dibuat karena tidak ada berita `Negatif`).
  - Ke depan, `Ringkasan Negatif` akan terfokus khusus pada berita yang memenuhi `N1–N4` (serangan langsung ke Kemenperin/pejabatnya, isu korupsi/pelanggaran hukum/moral Kemenperin, pernyataan pejabat Kemenperin yang berseberangan, atau kritik pihak lain terhadap kebijakan/eksistensi Kemenperin).

### Asumsi Sementara & Status Validasi
- Beberapa batas tafsir masih berstatus **asumsi sementara menunggu konfirmasi manusia / Biro Humas**: `K4 -> Netral`, aturan `A1–A5`, serta `TONE_ISU_MENGIKUTI_PERISTIWA`.
- `data/golden_tone_humas.csv` (20 sampel 17 Nov) **belum memiliki label manusia** (`tone_humas` masih kosong), sehingga akurasi terhadap standar resmi Biro Humas belum dapat diklaim secara empiris sebelum diisi dan divalidasi oleh tim Humas.

---

## 3. Efek Run Pertama Setelah Merge

- **Tidak ada pemakaian ulang cache tone lama**: karena `TONE_PROMPT_VERSION` berubah dari `v2026-11-12-b` ke `v2026-11-18-d`, seluruh kunci cache tone di `hasil_scrapping/cache_decisions.json` otomatis mengalami *cache miss*. Semua berita pada tanggal run pertama akan dinilai ulang dari awal menggunakan aturan `v2026-11-18-d` (entri cache lama tidak dipakai ulang dan akan terpangkas bertahap oleh `prune_pipeline_caches`).
- **Cache tahap lain tetap reusable**: `cache_decode.json`, `cache_decode_failed.json`, dan cache `ai_relevance` tetap dapat dipakai ulang karena versinya tidak berubah.
- **Perkiraan panggilan API Gemini tambahan (tahap isu + tone)**:
  - Untuk volume harian normal 30–60 berita lolos filter (contoh 17 Nov: 48 berita menjadi ~39 isu), mode gabungan (`USE_COMBINED_ISU_TONE=true`) memerlukan sekitar **6–12 panggilan API Gemini** (batch 8–10 kelompok/artikel).
  - Pada hari bervolume tinggi (80–120 berita) atau bila ada pemisahan outlier, perkiraan naik menjadi **12–20 panggilan API Gemini**.
- **Inisialisasi registri isu (run pertama)**: `pipeline_state/isu_registry.json` belum ada di branch `data`, sehingga langkah restore akan mencetak `[Registry] isu_registry.json belum ada (run pertama) - mulai dari registri baru.` lalu membuat dan menyimpan file registri pertama ke branch `data` setelah run sukses.

---

## 4. Diskontinuitas Arsip Lama vs Data Baru

| Aspek | Arsip Lama (sebelum merge) | Data Baru (setelah merge) |
|---|---|---|
| Unit penilaian tone | Per artikel/berita | Satu tone per isu (kecuali outlier) |
| Definisi tone | Kesan kondisi/angka ekonomi industri (`v2026-11-12-b`) | Peran & sikap terhadap Kemenperin (`v2026-11-18-d`) |
| Field `isu`, `alasan_tone`, `sumber_isu` | Kosong / tidak tersedia | Terisi otomatis oleh pipeline |
| Tampilan di mode "Kelompokkan per isu" | Masuk grup **"Tanpa isu"** (terlipat, paginasi, teks `"Tone dinilai per berita"`) | Tergabung ke kartu grup isu masing-masing |

> **Peringatan Analisis Tren**: Persentase tone (khususnya proporsi `Negatif` dan `Positif`) sebelum dan sesudah tanggal merge **tidak dapat dibandingkan secara langsung** tanpa penanda batas perubahan metodologi.

---

## 5. Checklist Merge, Pemantauan, dan Rollback

### A. Sebelum Merge
- [ ] Tinjau dan setujui (atau koreksi) asumsi sementara `K4`, `A1–A5`, dan `TONE_ISU_MENGIKUTI_PERISTIWA` bersama Biro Humas.
- [ ] Lengkapi kolom `tone_humas` pada `data/golden_tone_humas.csv` dan evaluasi akurasi serta recall `Negatif` pada label manusia.
- [ ] Putuskan apakah 19 commit pra-isu (`origin/main..main`) dipisah ke PR tersendiri sebelum PR fitur isu.
- [ ] Pastikan seluruh `pytest` (`tests/`) dan build web (`npm run build`) lolos.
- [ ] **Buat backup branch `data` dan `main` sebelum merge / sebelum run pertama**:
  ```bash
  git fetch origin main data
  git tag backup-main-pre-isu origin/main
  git tag backup-data-pre-isu origin/data
  git push origin backup-main-pre-isu backup-data-pre-isu
  ```

### B. Cara Memantau Run Terjadwal Pertama (03:07 WIB / `20:07 UTC`)
1. Pantau status workflow di GitHub Actions atau via CLI:
   ```bash
   gh run list --workflow daily_scrape.yml --limit 5
   gh run view <RUN_ID> --log
   ```
2. Verifikasi penanda log penting:
   - `[Registry] isu_registry.json belum ada (run pertama)` (normal pada run pertama).
   - Direct crawl `agro.kemenperin.go.id` dan `www.kemenperin.go.id` berjalan tanpa error fatal.
   - Tahap pengelompokan isu & tone selesai tanpa quota exhaustion; cek distribusi `Positif / Netral / Negatif`.
   - `[Registry] Disiapkan untuk persist atomik (... isu aktif, ... klaster >14 hari dipangkas).`
   - Commit ke `main` dan `data` sukses tanpa warning gagal push.
3. Verifikasi artefak di branch `data` dan dashboard web:
   - `git fetch origin data && git show origin/data:pipeline_state/isu_registry.json | head -n 20` (pastikan ada `updated_at` dan daftar `issues`).
   - Cek `data_export/runs.json` berstatus `Berhasil` dan `data_export/articles_all.json` berisi `isu` & `alasan_tone` untuk tanggal baru sementara tanggal lama tetap utuh.
   - Buka dashboard web: cek mode default, aktifkan toggle "Kelompokkan per isu", cek grup isu baru, grup "Tanpa isu", serta unduh file Excel untuk meninjau kolom `Isu`, `Alasan Tone`, dan sheet `Ringkasan Negatif`.

### C. Prosedur Rollback (Non-Destruktif dengan `git revert`)
> Jangan gunakan `git reset --hard` + `git push --force` pada `main` atau `data`.

1. **Rollback kode di branch `main`**:
   - Jika PR di-merge dengan merge commit (`<MERGE_SHA>`):
     ```bash
     git checkout main && git pull origin main
     git revert -m 1 <MERGE_SHA>
     git push origin main
     ```
   - Jika di-merge dengan squash commit (`<SQUASH_SHA>`):
     ```bash
     git checkout main && git pull origin main
     git revert <SQUASH_SHA>
     git push origin main
     ```
2. **Rollback data & state di branch `data` (opsional, jika hasil run pertama perlu dibatalkan)**:
   ```bash
   git fetch origin data --tags
   git checkout -B data origin/data
   git checkout backup-data-pre-isu -- data_export web/public pipeline_state
   git rm -f pipeline_state/isu_registry.json 2>/dev/null || true
   git commit -m "revert(data): pulihkan data_export dan pipeline_state ke backup-data-pre-isu"
   git push origin data
   ```
3. Setelah revert kode kembali ke `v2026-11-12-b`, run berikutnya otomatis tidak menggunakan cache tone `v2026-11-18-d` karena versi prompt kembali ke kunci lama.
