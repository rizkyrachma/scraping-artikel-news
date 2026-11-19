# Panduan Review Manusia Pengelompokan Isu (`isu_review_sheet.csv`)

Dokumen ini menjelaskan cara membuat, mengisi, dan mengevaluasi lembar review pengelompokan isu berita Ditjen Industri Agro.

## 1. Membuat Lembar Kerja Review CSV
Jalankan perintah berikut dari root repositori:

```bash
python make_isu_review_sheet.py
```

Skrip akan membaca file Excel hasil monitoring yang tersedia, menjalankan pengelompokan isu, dan menghasilkan file `data/isu_review_sheet.csv` dengan kolom:
- `id`: ID baris berita.
- `judul`: Judul berita yang sudah dibersihkan dari akhiran nama media.
- `isu_diberikan`: Nama isu hasil pencocokan rilis resmi atau hasil klaster berita.
- `sumber_isu`: `rilis` (siaran pers resmi Kemenperin) atau `klaster` (kelompok berita media).
- `skor`: Skor kemiripan terhadap isu (`0.0000` s.d. `1.0000`).
- `margin`: Selisih skor kandidat terbaik pertama dikurangi kandidat kedua (`top1 - top2`).
- `benar_sama_isu`: Kolom kosong untuk diisi oleh peninjau manusia.

## 2. Cara Mengisi Kolom `benar_sama_isu`
Buka `data/isu_review_sheet.csv` di Excel atau editor tabel, lalu isi kolom **`benar_sama_isu`** pada setiap baris dengan angka **`1`** atau **`0`**:

- Isi **`1` (Benar Satu Isu)** apabila `judul` dan `isu_diberikan` meliput **peristiwa, pernyataan, rilis, atau laporan data yang sama** (keduanya dapat dirangkum dalam satu kalimat *"apa yang terjadi"* tanpa kehilangan fakta utama).
- Isi **`0` (Bukan Satu Isu / Salah Tempel)** apabila `judul` dan `isu_diberikan` hanya kebetulan memiliki topik/komoditas umum yang sama (misal sama-sama membahas sawit atau rokok elektrik), tetapi membahas **peristiwa, pelaku, atau kejadian yang berbeda**.

## 3. Menghitung Precision dan Coverage
Setelah kolom `benar_sama_isu` diisi dan disimpan, jalankan:

```bash
python eval_isu.py data/isu_review_sheet.csv
```

Skrip akan menampilkan:
1. **Precision Keseluruhan** dan rincian per `sumber_isu` (`rilis` vs `klaster`).
2. **Tabel Precision & Coverage** untuk berbagai kombinasi ambang `skor` dan `margin`, guna membantu kalibrasi ambang batas produksi.
