"""
merge_october_13_to_20.py
Menggabungkan dataset berita Ditjen Industri Agro periode 13-19 Oktober 2026 dengan data hari kemarin (20 Oktober 2026):
- Sheet 1: Berita (12 kolom standar Ditjen Industri Agro, terurut kronologis 13-20 Oktober 2026)
- Sheet 2: Ringkasan Negatif (15 kolom 5W+1H + Stakeholder untuk seluruh artikel negatif)
- Deduplikasi URL dan judul
- Simpan ke folder hasil_scrapping/Oktober/2026-10-13_sd_2026-10-20/ dan hasil_scrapping/Oktober/
"""

import os
import sys
import pandas as pd
import openpyxl  # type: ignore

sys.path.insert(0, "src")
from export_excel import save_to_excel
from fetch_news import dedup_by_link, dedup_by_title


def clean_url(val: object) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    return s.split("?")[0].rstrip("/").lower()


def merge_datasets():
    src_13_19 = "hasil_scrapping/Oktober/all_2026-10-13_sd_2026-10-19_ringkasan.xlsx"
    if not os.path.exists(src_13_19):
        src_13_19 = "hasil_scrapping/Oktober/2026-10-13_sd_2026-10-19/all_2026-10-13_sd_2026-10-19_ringkasan.xlsx"

    src_20 = "hasil_scrapping/Oktober/2026-10-20/all_2026-10-20_ringkasan.xlsx"
    if not os.path.exists(src_20):
        src_20 = "hasil_scrapping/Oktober/2026-10-20/all_2026-10-20.xlsx"

    print("=" * 70)
    print("MENGGABUNGKAN DATASET 13-19 OKTOBER DENGAN 20 OKTOBER 2026")
    print("=" * 70)

    if not os.path.exists(src_13_19):
        raise FileNotFoundError(f"File 13-19 Oktober tidak ditemukan: {src_13_19}")
    if not os.path.exists(src_20):
        raise FileNotFoundError(f"File 20 Oktober tidak ditemukan: {src_20}")

    # 1. Baca data Berita
    df_b1 = pd.read_excel(src_13_19, sheet_name="Berita")
    df_b2 = pd.read_excel(src_20, sheet_name="Berita")
    print(f"[+] Memuat Berita 13-19 Oktober: {len(df_b1)} baris")
    print(f"[+] Memuat Berita 20 Oktober   : {len(df_b2)} baris")

    df_berita = pd.concat([df_b1, df_b2], ignore_index=True)

    # Normalisasi URL & Deduplikasi Link
    df_berita["_norm_url"] = df_berita["Link Website"].apply(clean_url)
    before_dedup = len(df_berita)
    df_berita = df_berita.drop_duplicates(subset=["_norm_url"], keep="first").drop(columns=["_norm_url"]).reset_index(drop=True)
    print(f"[+] Deduplikasi URL: {before_dedup} -> {len(df_berita)} baris")

    # Filter batas tanggal 13 s.d 20 Oktober 2026
    df_berita["_dt"] = pd.to_datetime(df_berita["Tanggal"], errors="coerce")
    mask = (df_berita["_dt"] >= "2026-10-13 00:00:00") & (df_berita["_dt"] <= "2026-10-20 23:59:59")
    df_filtered = df_berita.loc[mask]
    assert isinstance(df_filtered, pd.DataFrame)
    df_berita = df_filtered.sort_values(by="_dt", ascending=True).drop(columns=["_dt"]).reset_index(drop=True)
    print(f"[+] Total Berita 13-20 Oktober setelah filter tanggal: {len(df_berita)} baris")

    print("\n    Rincian per tanggal:")
    tgl_counts = {}
    for r in df_berita.itertuples():
        t_str = str(getattr(r, "Tanggal", ""))[:10]
        tgl_counts[t_str] = tgl_counts.get(t_str, 0) + 1
    for t_str, c in sorted(tgl_counts.items()):
        print(f"      {t_str}: {c} artikel")

    # 2. Baca data Ringkasan Negatif
    neg_dfs = []
    wb1 = openpyxl.load_workbook(src_13_19)
    if "Ringkasan Negatif" in wb1.sheetnames:
        df_n1 = pd.read_excel(src_13_19, sheet_name="Ringkasan Negatif")
        neg_dfs.append(df_n1)
        print(f"[+] Memuat Ringkasan Negatif 13-19 Okt: {len(df_n1)} baris")

    wb2 = openpyxl.load_workbook(src_20)
    if "Ringkasan Negatif" in wb2.sheetnames:
        df_n2 = pd.read_excel(src_20, sheet_name="Ringkasan Negatif")
        neg_dfs.append(df_n2)
        print(f"[+] Memuat Ringkasan Negatif 20 Okt   : {len(df_n2)} baris")

    neg_records = []
    if neg_dfs:
        df_neg = pd.concat(neg_dfs, ignore_index=True)
        df_neg["_norm_url"] = df_neg["Link Website"].apply(clean_url)
        df_neg = df_neg.drop_duplicates(subset=["_norm_url"], keep="first").drop(columns=["_norm_url"]).reset_index(drop=True)
        df_neg["_dt"] = pd.to_datetime(df_neg["Tanggal"], errors="coerce")
        assert isinstance(df_neg, pd.DataFrame)
        df_neg = df_neg.sort_values(by="_dt", ascending=True).drop(columns=["_dt"]).reset_index(drop=True)
        print(f"[+] Total Ringkasan Negatif setelah dedup & sort: {len(df_neg)} baris")
        neg_records = df_neg.to_dict(orient="records")

    berita_records = df_berita.to_dict(orient="records")

    # 3. Target direktori dan berkas output
    target_dir = "hasil_scrapping/Oktober/2026-10-13_sd_2026-10-20"
    os.makedirs(target_dir, exist_ok=True)

    out_folder_ringkasan = os.path.join(target_dir, "all_2026-10-13_sd_2026-10-20_ringkasan.xlsx")
    out_folder_all = os.path.join(target_dir, "all_2026-10-13_sd_2026-10-20.xlsx")
    out_root_ringkasan = "hasil_scrapping/Oktober/all_2026-10-13_sd_2026-10-20_ringkasan.xlsx"
    out_root_all = "hasil_scrapping/Oktober/all_2026-10-13_sd_2026-10-20.xlsx"

    for path, neg in [
        (out_folder_ringkasan, neg_records),
        (out_folder_all, None),
        (out_root_ringkasan, neg_records),
        (out_root_all, None),
    ]:
        save_to_excel(berita_records, path, merge_existing=False, negative_summaries=neg if neg else None)
        print(f"[SUKSES] Berkas tersimpan ke: {path}")

    print("=" * 70)
    print("PENGGABUNGAN SELESAI!")
    print(f"Total Berita          : {len(berita_records)}")
    print(f"Total Ringkasan Negatif: {len(neg_records)}")
    print("=" * 70)


if __name__ == "__main__":
    merge_datasets()
