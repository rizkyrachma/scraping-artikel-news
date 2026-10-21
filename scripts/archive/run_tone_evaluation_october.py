"""
run_tone_evaluation_october.py
Menjalankan evaluasi tone revisi pada:
1. all_2026-10-07.xlsx (55 baris)
2. all_2026-10-01_sd_2026-10-04.xlsx (214 baris)

Menghasilkan file Excel baru dengan tone revisi (tanpa menimpa file lama),
dan mencatat seluruh log penilaian ke hasil_scrapping/log_tone.jsonl.
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime

sys.path.insert(0, "src")
from config import load_env_file
load_env_file()

from tone_classifier import classify_tone_batch, get_api_call_count, reset_api_call_count
from export_excel import save_to_excel


def evaluate_file(excel_path: str, progress_path: str, output_excel_path: str):
    print("\n" + "=" * 70)
    print(f"MEMPROSES EVALUASI TONE: {excel_path}")
    print("=" * 70)

    # 1. Baca Excel yang sudah ada
    df_old = pd.read_excel(excel_path)
    print(f"[+] Total baris artikel di Excel: {len(df_old)}")

    # 2. Muat teks artikel dari progress.json
    text_map = {}
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            p_data = json.load(f)
            p_arts = p_data.get("articles", [])
            for a in p_arts:
                u = a.get("link") or a.get("resolved_url") or ""
                txt = a.get("text") or a.get("content") or ""
                if u:
                    text_map[u.strip()] = txt.strip()
                    # Simpan juga versi strip query
                    clean_u = u.split("?")[0].rstrip("/")
                    text_map[clean_u] = txt.strip()
        print(f"[+] Berhasil memetakan teks dari progress.json: {len(text_map)} URL")

    # 3. Siapkan payload artikel
    articles_payload = []
    old_records = df_old.to_dict(orient="records")
    for idx, r in enumerate(old_records):
        url = str(r.get("Link Website", "")).strip()
        clean_url = url.split("?")[0].rstrip("/")
        article_text = text_map.get(url) or text_map.get(clean_url) or ""
        articles_payload.append({
            "id": idx + 1,
            "title": str(r.get("Title", "")).strip(),
            "text": article_text,
            "row_data": r
        })

    # 4. Jalankan klasifikasi batch (5 artikel/batch)
    batch_size = 5
    total_batches = (len(articles_payload) + batch_size - 1) // batch_size
    print(f"[+] Memulai klasifikasi tone untuk {len(articles_payload)} artikel ({total_batches} batch)...")

    reset_api_call_count()
    results = classify_tone_batch(articles_payload, use_ai=True)
    api_calls_used = get_api_call_count()

    # 5. Analisis perubahan tone & statistik
    ai_count = 0
    fallback_count = 0
    changed_articles = []
    new_records = []

    old_tone_dist = df_old["Tone"].value_counts(dropna=False).to_dict()
    new_tone_dist = {"Positif": 0, "Netral": 0, "Negatif": 0}

    for r, payload_item, res in zip(old_records, articles_payload, results):
        row = r if isinstance(r, dict) else {}
        tone_val = row.get("Tone")
        old_tone = str(tone_val).strip().capitalize() if tone_val is not None else ""
        new_tone = res["tone"]
        dasar = res["dasar"]
        alasan = res["alasan"]
        metode = res["metode"]

        if metode == "AI":
            ai_count += 1
        else:
            fallback_count += 1

        new_tone_dist[new_tone] = new_tone_dist.get(new_tone, 0) + 1

        if old_tone != new_tone:
            changed_articles.append({
                "id": payload_item["id"],
                "Title": row.get("Title"),
                "Media Name": row.get("Media Name"),
                "Tone Lama": old_tone,
                "Tone Baru": new_tone,
                "Dasar": dasar,
                "Metode": metode,
                "Alasan": alasan
            })

        # Update nilai Tone di baris Excel (TANPA menambah kolom baru)
        row["Tone"] = new_tone
        new_records.append(row)

    # 6. Simpan ke file Excel baru
    save_to_excel(new_records, output_excel_path, merge_existing=False)
    print(f"[+] Hasil tersimpan ke file Excel baru: {output_excel_path}")

    # 7. Tampilkan Laporan
    print("\n" + "-" * 70)
    print(f"LAPORAN EVALUASI: {os.path.basename(excel_path)}")
    print("-" * 70)
    print(f"Total Artikel           : {len(df_old)}")
    print(f"Dinilai via AI          : {ai_count}")
    print(f"Jatuh ke Fallback       : {fallback_count}")
    print(f"Panggilan API Terpakai  : {api_calls_used} panggilan (dari {total_batches} batch)")
    print(f"Total Tone Berubah      : {len(changed_articles)} artikel ({len(changed_articles)/len(df_old)*100:.1f}%)")

    print("\n[DISTRIBUSI TONE SEBELUM vs SESUDAH]")
    print(f"  Positif : {old_tone_dist.get('Positif', 0):3d} -> {new_tone_dist.get('Positif', 0):3d}")
    print(f"  Netral  : {old_tone_dist.get('Netral', 0):3d} -> {new_tone_dist.get('Netral', 0):3d}")
    print(f"  Negatif : {old_tone_dist.get('Negatif', 0):3d} -> {new_tone_dist.get('Negatif', 0):3d}")

    print(f"\n[DAFTAR SEMUA ARTIKEL YANG TONENYA BERUBAH ({len(changed_articles)} ARTIKEL)]:")
    for idx, c in enumerate(changed_articles, 1):
        print(f"{idx:2d}. [{c['Tone Lama']} -> {c['Tone Baru']}] {c['Title']}")
        print(f"    Media: {c['Media Name']} | Dasar: {c['Dasar']} ({c['Metode']}) | Alasan: {c['Alasan']}")

    return {
        "file": os.path.basename(excel_path),
        "total": len(df_old),
        "ai_count": ai_count,
        "fallback_count": fallback_count,
        "api_calls": api_calls_used,
        "old_dist": old_tone_dist,
        "new_dist": new_tone_dist,
        "changed": changed_articles,
        "new_file": output_excel_path
    }


def main():
    report_7 = evaluate_file(
        excel_path="hasil_scrapping/Oktober/2026-10-07/all_2026-10-07.xlsx",
        progress_path="hasil_scrapping/Oktober/2026-10-07/progress.json",
        output_excel_path="hasil_scrapping/Oktober/2026-10-07/all_2026-10-07_tone_revisi.xlsx"
    )

    report_14 = evaluate_file(
        excel_path="hasil_scrapping/Oktober/2026-10-01_sd_2026-10-04/all_2026-10-01_sd_2026-10-04.xlsx",
        progress_path="hasil_scrapping/Oktober/2026-10-01_sd_2026-10-04/progress.json",
        output_excel_path="hasil_scrapping/Oktober/2026-10-01_sd_2026-10-04/all_2026-10-01_sd_2026-10-04_tone_revisi.xlsx"
    )

    # Simpan summary laporan ke json untuk referensi jika dibutuhkan
    summary_path = "hasil_scrapping/summary_revisi_tone.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"report_7": report_7, "report_14": report_14}, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 70)
    print("SELURUH EVALUASI TONE 7 OKTOBER & 1-4 OKTOBER SELESAI!")
    print(f"Ringkasan tersimpan ke: {summary_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
