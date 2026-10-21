"""
merge_october_1_to_7.py
Menggabungkan seluruh dataset berita hasil kurasi dari tanggal 1 Oktober sampai 7 Oktober 2026:
- 2026-10-01 s/d 2026-10-04 (214 baris)
- 2026-10-05 (85 baris)
- 2026-10-06 (39 baris)
- 2026-10-07 (55 baris)
- Rilis resmi Ditjen Industri Agro (agro.kemenperin.go.id)
- Deduplikasi berdasarkan Link Website
- Pengurutan Tanggal menurun (descending)
- Ekspor ke Excel standar Ditjen Industri Agro (12 kolom)
"""

import os
import sys
import pandas as pd

sys.path.insert(0, "src")
from export_excel import save_to_excel
from direct_crawl_agro import fetch_agro_kemenperin, cocokkan_rilis_resmi

def main():
    print("=" * 70)
    print("PENGGABUNGAN DATASET EXCEL 1 OKTOBER S/D 7 OKTOBER 2026")
    print("=" * 70)

    # 1. Definisikan file sumber per periode
    source_files = [
        ("1-4 Oktober 2026", "hasil_scrapping/Oktober/2026-10-01_sd_2026-10-04/all_2026-10-01_sd_2026-10-04.xlsx"),
        ("5 Oktober 2026",   "hasil_scrapping/Oktober/2026-10-05/all_2026-10-05.xlsx"),
        ("6 Oktober 2026",   "hasil_scrapping/Oktober/2026-10-06/all_2026-10-06.xlsx"),
        ("7 Oktober 2026",   "hasil_scrapping/Oktober/2026-10-07/all_2026-10-07_perbaikan.xlsx"),
    ]

    dfs = []
    total_raw_rows = 0
    for label, filepath in source_files:
        if not os.path.exists(filepath):
            print(f"[ERROR] File tidak ditemukan: {filepath}")
            continue
        df = pd.read_excel(filepath)
        print(f"[+] Memuat {label:18s} ({filepath}): {len(df)} baris")
        dfs.append(df)
        total_raw_rows += len(df)

    if not dfs:
        print("[ERROR] Tidak ada data yang berhasil dimuat.")
        return

    # 2. Ambil rilis resmi Ditjen Industri Agro jika ada
    print("\n[+] Mengambil rilis resmi Ditjen Industri Agro (agro.kemenperin.go.id)...")
    agro_items = fetch_agro_kemenperin(date_from="2026-10-01", date_to="2026-10-07", include_content=False)
    print(f"    Ditemukan {len(agro_items)} rilis resmi Ditjen Agro.")
    if agro_items:
        df_agro = pd.DataFrame(agro_items)
        dfs.append(df_agro)
        total_raw_rows += len(df_agro)

    # 3. Gabungkan seluruh DataFrame
    df_combined = pd.concat(dfs, ignore_index=True)
    print(f"\n[+] Total baris sebelum deduplikasi: {len(df_combined)} baris")

    # 4. Normalisasi URL & Deduplikasi HANYA berdasarkan Link Website
    # Membersihkan tracking parameter jika ada
    def clean_url(val):
        if pd.isna(val) or not val:
            return ""
        s = str(val).strip()
        return s.split("?")[0].rstrip("/")

    df_combined["_norm_url"] = df_combined["Link Website"].apply(clean_url)
    duplicates_count = df_combined.duplicated(subset=["_norm_url"]).sum()
    df_deduped = df_combined.drop_duplicates(subset=["_norm_url"], keep="first").drop(columns=["_norm_url"]).reset_index(drop=True)
    print(f"[+] Ditemukan dan dieliminasi {duplicates_count} tautan duplikat lintas-tanggal.")
    print(f"[+] Total baris unik setelah dedup: {len(df_deduped)} baris")

    # 5. Verifikasi silang judul media lain dengan rilis resmi Ditjen Agro
    if agro_items:
        df_deduped = cocokkan_rilis_resmi(df_deduped, agro_items, ambang=80)

    # 6. Urutkan berdasarkan Tanggal dari terkecil ke terbesar (ascending)
    df_deduped["_sort_dt"] = pd.to_datetime(df_deduped["Tanggal"], errors="coerce")
    df_deduped = df_deduped.sort_values(by="_sort_dt", ascending=True).drop(columns=["_sort_dt"]).reset_index(drop=True)

    # 7. Pastikan susunan kolom tepat 12 kolom standar
    std_columns = [
        "Tanggal", "Title", "Link Website", "Media Name", "Tone",
        "Spokesperson 1", "Spokesperson 2", "Unit Eselon",
        "Terkait Kemenperin", "Status Review", "Keywords", "Sumber Data"
    ]
    for col in std_columns:
        if col not in df_deduped.columns:
            df_deduped[col] = ""
    df_deduped = df_deduped[std_columns]

    # 8. Simpan ke Excel di 2 lokasi strategis
    out_dir_range = "hasil_scrapping/Oktober/2026-10-01_sd_2026-10-07"
    os.makedirs(out_dir_range, exist_ok=True)
    out_file_1 = os.path.join(out_dir_range, "all_2026-10-01_sd_2026-10-07.xlsx")
    out_file_2 = "hasil_scrapping/Oktober/all_2026-10-01_sd_2026-10-07.xlsx"

    records = df_deduped.to_dict(orient="records")
    saved_1 = save_to_excel(records, out_file_1, merge_existing=False)
    saved_2 = save_to_excel(records, out_file_2, merge_existing=False)

    # Sinkronisasi all_2026-10-07.xlsx agar konsisten memakai 55 baris perbaikan
    out_7_main = "hasil_scrapping/Oktober/2026-10-07/all_2026-10-07.xlsx"
    df_7_clean = pd.read_excel("hasil_scrapping/Oktober/2026-10-07/all_2026-10-07_perbaikan.xlsx")
    save_to_excel(df_7_clean.to_dict(orient="records"), out_7_main, merge_existing=False)

    print("\n" + "=" * 70)
    print("HASIL PENGGABUNGAN SELESAI")
    print("=" * 70)
    print(f"File 1: {saved_1}")
    print(f"File 2: {saved_2}")
    print(f"Total baris artikel: {len(df_deduped)}")
    print(f"Daftar kolom ({len(df_deduped.columns)}): {list(df_deduped.columns)}")

    # Rincian tanggal
    df_deduped["_tgl_str"] = pd.to_datetime(df_deduped["Tanggal"]).dt.strftime("%Y-%m-%d")
    print("\nDistribusi Per Tanggal:")
    print(df_deduped["_tgl_str"].value_counts().sort_index().to_string())

    print("\nDistribusi Tone:")
    print(df_deduped["Tone"].value_counts(dropna=False).to_string())

    print("\nDistribusi Terkait Kemenperin:")
    print(df_deduped["Terkait Kemenperin"].value_counts(dropna=False).to_string())

    print("\nDistribusi Sumber Data:")
    print(df_deduped["Sumber Data"].value_counts(dropna=False).to_string())
    print("=" * 70)

if __name__ == "__main__":
    main()
