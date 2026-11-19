# Panduan Pelabelan Tone Manual (Blind Evaluation)

> **PERINGATAN WAJIB:** **JANGAN membuka, membaca, atau mengintip `data/label_tone_key.csv` sebelum Anda menyelesaikan seluruh pelabelan di `data/label_tone_blind.csv`.** File kunci tersebut berisi prediksi dan alasan model yang dapat memengaruhi objektivitas penilaian manusia.

---

## 1. File yang Dikerjakan
- **File kerja (isi di sini):** `data/label_tone_blind.csv`
- **File kunci (JANGAN dibuka saat melabel):** `data/label_tone_key.csv`

## 2. Kolom di `data/label_tone_blind.csv`
| Kolom | Keterangan | Diisi Pelabel? |
|---|---|---|
| `id` | ID unik artikel (`BLD-001` s/d `BLD-086`) — jangan diubah | Tidak |
| `tanggal` | Tanggal publikasi berita (`YYYY-MM-DD`) | Tidak |
| `media` | Nama media penerbit | Tidak |
| `judul` | Judul asli berita | Tidak |
| `cuplikan_isi` | Cuplikan teks isi berita (jika tersedia di arsip) | Tidak |
| `tone_manusia` | Isi tepat salah satu: **`Positif`**, **`Netral`**, atau **`Negatif`** | **Ya (Wajib)** |
| `kategori_K` | Isi tepat salah satu: **`K1`**, **`K2`**, **`K3`**, atau **`K4`** | **Ya (Wajib)** |
| `catatan` | Catatan opsional untuk kasus ragu/ambigu atau masukan ke aturan | Opsional |

## 3. Ringkasan Pedoman Penilaian (Indikator Biro Humas Kemenperin)

Nilai berdasarkan **peran dan sikap pemberitaan terhadap Kemenperin**, bukan semata baik/buruknya angka ekonomi industri.

### Langkah 1 — Tentukan `kategori_K` (Hubungan dengan Kemenperin)
- **`K1`**: Kemenperin (institusi, Menperin, Wamenperin, Sekjen, Dirjen, pejabat/jubir resmi) menjadi **pelaku atau narasumber utama**.
- **`K2`**: Kemenperin (institusi atau pejabatnya) disebut **hanya sebagai pelengkap / bagian kecil** pemberitaan.
- **`K3`**: Kemenperin **tidak disebut langsung**, tetapi isunya berkaitan dengan kebijakan, kepentingan, atau program kerja Kemenperin (sektor industri/agro).
- **`K4`**: **Tidak berkaitan** dengan Kemenperin (mis. murni kebijakan K/L lain, perusahaan/komoditas tanpa kaitan kebijakan Kemenperin).

### Langkah 2 — Tentukan `tone_manusia`
- **`Positif`**:
  - Kemenperin/pejabat menjadi pelaku/narasumber utama untuk kepentingan & eksistensi Kemenperin (`K1` tanpa serangan), **atau**
  - Pihak lain menyatakan dukungan terhadap kebijakan/eksistensi Kemenperin (`K3` mendukung).
- **`Netral`**:
  - Kemenperin hanya disebut pelengkap tanpa serangan (`K2`), **atau**
  - Isu terkait sektor/program Kemenperin tanpa menyebut langsung dan tanpa dukungan/serangan jelas (`K3`), **atau**
  - Berita tidak berkaitan dengan Kemenperin (`K4`).
- **`Negatif`**:
  - Menyebut Kemenperin/pejabat secara menyerang atau menyudutkan eksistensi Kemenperin (`K1`/`K2` menyerang), **atau**
  - Isu korupsi atau aktivitas bertentangan hukum/moral yang menyerang lembaga/person Kemenperin, **atau**
  - Pernyataan/aktivitas dari Kemenperin yang berseberangan dengan kepentingan & eksistensi Kemenperin, **atau**
  - Pihak lain menyerang kebijakan atau eksistensi Kemenperin (`K3` menyerang).

> **Catatan kasus ambigu:** Jika menurut standar Biro Humas suatu berita kondisi industri memburuk atau desakan asosiasi ke "pemerintah" seharusnya `Negatif` atau `Netral`, tulis penilaian profesional Anda apa adanya dan beri catatan singkat di kolom `catatan`.

## 4. Evaluasi Setelah Pelabelan Selesai
Setelah kolom `tone_manusia` (dan `kategori_K`) diisi dan disimpan, jalankan:
```bash
python eval_tone.py --blind data/label_tone_blind.csv --key data/label_tone_key.csv
```
Skrip akan menghitung **Confusion Matrix 3×3**, **Precision/Recall/F1 per kelas**, **Recall Negatif terpisah**, **kesesuaian kategori K**, dan **perbandingan terhadap baseline "selalu Netral"**.
