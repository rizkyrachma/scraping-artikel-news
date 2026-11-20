"""
scripts/verify_dashboard_vs_excel.py
Skrip audit BACA-SAJA untuk memverifikasi kebenaran data dashboard terhadap Excel harian.
Mencetak seluruh selisih per tanggal dan per tone, serta keluar dengan exit code non-nol bila ada selisih.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
import pandas as pd


def verify_dashboard_vs_excel(data_dir: Path, files_dir: Path, verbose: bool = False) -> int:
    daily_files = sorted([
        f for f in files_dir.glob("Media_Monitoring_Agro_*.xlsx")
        if f.name != "Media_Monitoring_Agro_Semua_Data.xlsx" and not f.name.endswith(".tmp.xlsx")
    ])

    if not daily_files:
        print(f"[Error] Tidak ditemukan file Excel harian di {files_dir}")
        return 1

    articles_json_path = data_dir / "articles_all.json"
    summary_json_path = data_dir / "summary.json"
    semua_excel_path = files_dir / "Media_Monitoring_Agro_Semua_Data.xlsx"

    if not articles_json_path.exists() or not summary_json_path.exists():
        print(f"[Error] Berkas JSON tidak lengkap di {data_dir}")
        return 1

    with open(articles_json_path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    with open(summary_json_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    # Indeks artikel JSON berdasarkan tanggal
    json_by_date = defaultdict(list)
    for a in articles:
        d = (a.get("date") or "")[:10]
        if d:
            json_by_date[d].append(a)

    cal_counts = summary.get("metadata", {}).get("calendar_counts", {})
    daily_tones = summary.get("metadata", {}).get("daily_tones", {})
    summary_total = summary.get("metadata", {}).get("total_articles", 0)

    discrepancies = []
    total_excel_rows = 0

    print("=" * 80)
    print(f"AUDIT DATA DASHBOARD VS EXCEL HARIAN ({len(daily_files)} file)")
    print(f"Data Dir : {data_dir}")
    print(f"Files Dir: {files_dir}")
    print("=" * 80)

    for f in daily_files:
        d_str = f.name.replace("Media_Monitoring_Agro_", "").replace(".xlsx", "")
        df = pd.read_excel(f, sheet_name="Berita")
        excel_cnt = len(df)
        total_excel_rows += excel_cnt

        j_arts = json_by_date.get(d_str, [])
        j_cnt = len(j_arts)
        cal_cnt = cal_counts.get(d_str, 0)
        s_day = daily_tones.get(d_str, {})
        s_cnt = s_day.get("count", 0)

        # Hitung tone Excel
        ex_tones = {"Positif": 0, "Netral": 0, "Negatif": 0}
        for _, r in df.iterrows():
            t = str(r.get("Tone") or "Netral").strip().capitalize()
            if t not in ex_tones:
                t = "Netral"
            ex_tones[t] += 1

        # Hitung tone JSON
        j_tones = {"Positif": 0, "Netral": 0, "Negatif": 0}
        for a in j_arts:
            t = a.get("tone", "Netral")
            j_tones[t] = j_tones.get(t, 0) + 1

        # Cek jumlah baris
        if excel_cnt != j_cnt:
            discrepancies.append({
                "date": d_str,
                "type": "count_mismatch",
                "detail": f"Excel={excel_cnt} baris vs articles_all.json={j_cnt} baris",
            })
        if excel_cnt != cal_cnt:
            discrepancies.append({
                "date": d_str,
                "type": "calendar_count_mismatch",
                "detail": f"Excel={excel_cnt} baris vs summary.calendar_counts={cal_cnt}",
            })
        if excel_cnt != s_cnt:
            discrepancies.append({
                "date": d_str,
                "type": "daily_tone_count_mismatch",
                "detail": f"Excel={excel_cnt} baris vs summary.daily_tones.count={s_cnt}",
            })

        # Cek distribusi tone
        if ex_tones != j_tones:
            discrepancies.append({
                "date": d_str,
                "type": "tone_mismatch_json",
                "detail": f"Excel {ex_tones} vs articles_all {j_tones}",
            })
        s_tones_cmp = {
            "Positif": s_day.get("pos", 0),
            "Netral": s_day.get("net", 0),
            "Negatif": s_day.get("neg", 0),
        }
        if ex_tones != s_tones_cmp:
            discrepancies.append({
                "date": d_str,
                "type": "tone_mismatch_summary",
                "detail": f"Excel {ex_tones} vs summary.daily_tones {s_tones_cmp}",
            })

        if verbose and excel_cnt == j_cnt and ex_tones == j_tones:
            print(f"  [OK] {d_str}: {excel_cnt} berita {ex_tones}")

    # Cek total keseluruhan
    if total_excel_rows != len(articles):
        discrepancies.append({
            "date": "ALL",
            "type": "total_articles_mismatch",
            "detail": f"Total Excel={total_excel_rows} vs articles_all.json={len(articles)} (selisih {total_excel_rows - len(articles)})",
        })

    if total_excel_rows != summary_total:
        discrepancies.append({
            "date": "ALL",
            "type": "summary_total_mismatch",
            "detail": f"Total Excel={total_excel_rows} vs summary.metadata.total_articles={summary_total} (selisih {total_excel_rows - summary_total})",
        })

    # Cek Media_Monitoring_Agro_Semua_Data.xlsx
    if semua_excel_path.exists():
        df_semua = pd.read_excel(semua_excel_path, sheet_name="Berita")
        semua_cnt = len(df_semua)
        if semua_cnt != total_excel_rows:
            discrepancies.append({
                "date": "ALL",
                "type": "semua_data_excel_mismatch",
                "detail": f"Total Excel Harian={total_excel_rows} vs Media_Monitoring_Agro_Semua_Data.xlsx={semua_cnt} (selisih {total_excel_rows - semua_cnt})",
            })
        print(f"Total baris Media_Monitoring_Agro_Semua_Data.xlsx: {semua_cnt}")

    print(f"Total baris seluruh Excel Harian : {total_excel_rows}")
    print(f"Total rekaman articles_all.json  : {len(articles)}")
    print(f"Total metadata summary.json       : {summary_total}")
    print("-" * 80)

    if discrepancies:
        print(f"[FAIL] DITEMUKAN {len(discrepancies)} SELISIH:")
        for d in discrepancies:
            print(f"  - [{d['date']}] ({d['type']}): {d['detail']}")
        print("=" * 80)
        return 1
    else:
        print("[PASS] 0 SELISIH. Seluruh data JSON dan summary 100% cocok dengan Excel harian!")
        print("=" * 80)
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit kesesuaian data dashboard vs Excel harian")
    parser.add_argument("--data-dir", type=str, default="data_export", help="Direktori data_export")
    parser.add_argument("--files-dir", type=str, default="data_export/files", help="Direktori files Excel")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail per tanggal yang lolos")

    args = parser.parse_args()
    code = verify_dashboard_vs_excel(Path(args.data_dir), Path(args.files_dir), verbose=args.verbose)
    sys.exit(code)
