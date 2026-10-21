# Arsip Skrip Kurasi & Reproses Batch (Oktober 2026)

Direktori ini berisi skrip pemrosesan batch, kurasi relevansi, evaluasi tone, dan penggabungan dataset harian yang dijalankan secara ad-hoc selama periode magang di Ditjen Industri Agro.

## Daftar Skrip:

1. **`reprocess_and_save_master.py`**: Pembersihan 518 artikel mentah periode 13-20 Oktober 2026 menjadi 378 artikel industri agro terkurasi dan 77 telaah ringkasan isu negatif (5W+1H).
2. **`merge_october_13_to_20.py`**: Skrip penggabungan awal dataset 13-19 Oktober dengan data 20 Oktober.
3. **`create_merged_oct_13_19.py`**: Skrip validasi dan pembuatan dataset 13 s.d. 19 Oktober.
4. **`create_merged_oct_9_11.py`**: Skrip penggabungan dan filter khusus tanggal 9-11 Oktober.
5. **`process_october_9_12.py`**: Filter ulang relevansi dan ringkasan negatif tanggal 9-12 Oktober.
6. **`merge_october_1_to_7.py`**: Penggabungan dataset 1-7 Oktober dan rilis resmi portal agro.kemenperin.go.id.
7. **`run_reprocess_all_october.py`**: Standarisasi skema 12 kolom dan aturan prioritas untuk data 1-6 Oktober.
8. **`run_reprocess_2026_10_05.py`**: Reproses khusus tanggal 5 Oktober.
9. **`run_reprocess_2026_10_07.py`**: Reproses khusus tanggal 7 Oktober.
10. **`run_tone_evaluation_october.py`**: Evaluasi konsistensi tone berita pada batch awal Oktober.
11. **`run_negative_summarizer_pipeline.py`**: Runner pengujian pipeline ekstraksi ringkasan negatif 5W+1H.

> **Catatan Penggunaan**: Seluruh output final dari skrip-skrip di atas telah tersimpan dalam format `.xlsx` di folder `hasil_scrapping/`. Jika ingin menjalankan ulang salah satu skrip dari root repositori, gunakan perintah:
> ```bash
> python scripts/archive/<nama_skrip>.py
> ```
