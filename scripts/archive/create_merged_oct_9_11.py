"""
create_merged_oct_9_11.py
Menggabungkan dan memfilter dataset khusus rentang tanggal 9 s.d 11 Oktober 2026:
- Sheet 1: Berita (12 kolom standar, tanggal 9-11 Oktober 2026)
- Sheet 2: Ringkasan Negatif (15 kolom 5W+1H + Stakeholder untuk artikel negatif 9-11 Oktober)
"""

import os
import sys
import pandas as pd
import openpyxl  # type: ignore

sys.path.insert(0, "src")
from export_excel import save_to_excel

def main():
    src_file = "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-12/all_2026-10-09_sd_2026-10-12_.xlsx"
    if not os.path.exists(src_file):
        src_file = "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-12/all_2026-10-09_sd_2026-10-12.xlsx"

    print(f"[+] Memuat data dari: {src_file}")
    df_berita = pd.read_excel(src_file, sheet_name="Berita")
    
    has_neg = False
    wb = openpyxl.load_workbook(src_file)
    if "Ringkasan Negatif" in wb.sheetnames:
        df_neg = pd.read_excel(src_file, sheet_name="Ringkasan Negatif")
        has_neg = True
    else:
        df_neg = pd.DataFrame()

    print(f"Total baris awal di Berita: {len(df_berita)}")
    if has_neg:
        print(f"Total baris awal di Ringkasan Negatif: {len(df_neg)}")

    # Filter rentang 9 - 11 Oktober 2026
    df_berita["_dt"] = pd.to_datetime(df_berita["Tanggal"], errors="coerce")
    mask_berita = (df_berita["_dt"] >= "2026-10-09 00:00:00") & (df_berita["_dt"] <= "2026-10-11 23:59:59")
    df_filtered_berita = df_berita[mask_berita].drop(columns=["_dt"]).reset_index(drop=True)

    print(f"[+] Total baris Berita 9-11 Oktober: {len(df_filtered_berita)}")
    print("    Rincian per tanggal:")
    tgl_counts: dict[str, int] = {}
    for r in df_filtered_berita.itertuples():
        t_str = str(getattr(r, "Tanggal", ""))[:10]
        tgl_counts[t_str] = tgl_counts.get(t_str, 0) + 1
    for t_str, c in sorted(tgl_counts.items()):
        print(f"    {t_str}: {c}")

    # Filter Ringkasan Negatif 9 - 11 Oktober
    neg_records = []
    if has_neg and not df_neg.empty:
        df_neg["_dt"] = pd.to_datetime(df_neg["Tanggal"], errors="coerce")
        mask_neg = (df_neg["_dt"] >= "2026-10-09 00:00:00") & (df_neg["_dt"] <= "2026-10-11 23:59:59")
        df_filtered_neg = df_neg[mask_neg].drop(columns=["_dt"]).reset_index(drop=True)
        print(f"[+] Total baris Ringkasan Negatif 9-11 Oktober: {len(df_filtered_neg)}")
        neg_records = df_filtered_neg.to_dict(orient="records")  # type: ignore

    berita_records = df_filtered_berita.to_dict(orient="records")  # type: ignore

    # Target folder 2026-10-09_sd_2026-10-11
    target_dir = "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-11"
    os.makedirs(target_dir, exist_ok=True)
    out_path = os.path.join(target_dir, "all_2026-10-09_sd_2026-10-11.xlsx")
    out_ringkasan_path = os.path.join(target_dir, "all_2026-10-09_sd_2026-10-11_ringkasan.xlsx")

    # Ekspor menggunakan save_to_excel agar format, hyperlink, dan freeze panes terjaga
    save_to_excel(
        berita_records,
        out_ringkasan_path,
        merge_existing=False,
        negative_summaries=neg_records if neg_records else None
    )
    print(f"[+] File berhasil diekspor ke: {out_ringkasan_path}")

    save_to_excel(
        berita_records,
        out_path,
        merge_existing=False,
        negative_summaries=neg_records if neg_records else None
    )
    print(f"[+] File berhasil diekspor ke: {out_path}")

    # Salin juga ke folder 2026-10-09_sd_2026-10-12 untuk kemudahan akses
    out_mirror = "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-12/all_2026-10-09_sd_2026-10-11_ringkasan.xlsx"
    save_to_excel(
        berita_records,
        out_mirror,
        merge_existing=False,
        negative_summaries=neg_records if neg_records else None
    )
    print(f"[+] File salinan berhasil disimpan ke: {out_mirror}")


if __name__ == "__main__":
    main()
