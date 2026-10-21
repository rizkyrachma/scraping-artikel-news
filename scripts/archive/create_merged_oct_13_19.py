"""
create_merged_oct_13_19.py
Memvalidasi dan memastikan dataset gabungan periode 13 s.d 19 Oktober 2026:
- Sheet 1: Berita (12 kolom standar Ditjen Industri Agro)
- Sheet 2: Ringkasan Negatif (15 kolom 5W+1H + Stakeholder untuk berita negatif)
"""

import os
import sys
import pandas as pd
import openpyxl  # type: ignore

sys.path.insert(0, "src")
from export_excel import save_to_excel


def main():
    src_file = "hasil_scrapping/Oktober/2026-10-13_sd_2026-10-19/all_2026-10-13_sd_2026-10-19_ringkasan.xlsx"
    if not os.path.exists(src_file):
        src_file = "hasil_scrapping/Oktober/2026-10-13_sd_2026-10-19/all_2026-10-13_sd_2026-10-19.xlsx"

    print(f"[+] Memuat data dari: {src_file}")
    df_berita = pd.read_excel(src_file, sheet_name="Berita")

    wb = openpyxl.load_workbook(src_file)
    has_neg = "Ringkasan Negatif" in wb.sheetnames
    df_neg = pd.read_excel(src_file, sheet_name="Ringkasan Negatif") if has_neg else pd.DataFrame()

    print(f"Total baris Berita: {len(df_berita)}")
    if has_neg:
        print(f"Total baris Ringkasan Negatif: {len(df_neg)}")

    # Filter rentang 13 - 19 Oktober 2026
    df_berita["_dt"] = pd.to_datetime(df_berita["Tanggal"], errors="coerce")
    mask_berita = (df_berita["_dt"] >= "2026-10-13 00:00:00") & (df_berita["_dt"] <= "2026-10-19 23:59:59")
    df_filtered_berita = df_berita[mask_berita].drop(columns=["_dt"]).reset_index(drop=True)

    # Urutkan berdasarkan tanggal ascending
    df_filtered_berita["_sort"] = pd.to_datetime(df_filtered_berita["Tanggal"], errors="coerce")
    df_filtered_berita = df_filtered_berita.sort_values(by="_sort", ascending=True).drop(columns=["_sort"]).reset_index(drop=True)

    print(f"[+] Total baris Berita 13-19 Oktober: {len(df_filtered_berita)}")
    print("    Rincian per tanggal:")
    tgl_counts: dict[str, int] = {}
    for r in df_filtered_berita.itertuples():
        t_str = str(getattr(r, "Tanggal", ""))[:10]
        tgl_counts[t_str] = tgl_counts.get(t_str, 0) + 1
    for t_str, c in sorted(tgl_counts.items()):
        print(f"    {t_str}: {c}")

    neg_records = []
    if has_neg and not df_neg.empty:
        df_neg["_dt"] = pd.to_datetime(df_neg["Tanggal"], errors="coerce")
        mask_neg = (df_neg["_dt"] >= "2026-10-13 00:00:00") & (df_neg["_dt"] <= "2026-10-19 23:59:59")
        df_filtered_neg = df_neg[mask_neg].drop(columns=["_dt"]).reset_index(drop=True)
        print(f"[+] Total baris Ringkasan Negatif 13-19 Oktober: {len(df_filtered_neg)}")
        neg_records = df_filtered_neg.to_dict(orient="records")

    berita_records = df_filtered_berita.to_dict(orient="records")

    # Lokasi penyimpanan
    target_dir = "hasil_scrapping/Oktober/2026-10-13_sd_2026-10-19"
    os.makedirs(target_dir, exist_ok=True)

    out_folder_ringkasan = os.path.join(target_dir, "all_2026-10-13_sd_2026-10-19_ringkasan.xlsx")
    out_folder_all = os.path.join(target_dir, "all_2026-10-13_sd_2026-10-19.xlsx")
    out_root_ringkasan = "hasil_scrapping/Oktober/all_2026-10-13_sd_2026-10-19_ringkasan.xlsx"
    out_root_all = "hasil_scrapping/Oktober/all_2026-10-13_sd_2026-10-19.xlsx"

    for path, neg in [
        (out_folder_ringkasan, neg_records),
        (out_folder_all, None),
        (out_root_ringkasan, neg_records),
        (out_root_all, None),
    ]:
        save_to_excel(berita_records, path, merge_existing=False, negative_summaries=neg if neg else None)
        print(f"[+] Berhasil disimpan: {path}")


if __name__ == "__main__":
    main()
