"""
run_negative_summarizer_pipeline.py
Menjalankan pipeline pengujian dan ringkasan otomatis berita negatif:
1. Re-filter relevansi (filter struktural + flag Kemenperin non-IA ILMATE)
2. Klasifikasi tone konsisten per grup judul (rapidfuzz >= 90) + prompt selaras + log jujur
3. Ringkasan otomatis berita bertone Negatif (5W+1H + Stakeholders) via negative_summarizer.py
4. Ekspor ke file baru berakhiran _ringkasan.xlsx (Sheet 1: Berita, Sheet 2: Ringkasan Negatif)
"""

import os
import sys
import json
import re
import pandas as pd
from datetime import datetime

sys.path.insert(0, "src")
from config import load_env_file
load_env_file()

from relevance_filter import is_non_article_structural_noise
from tone_classifier import (
    classify_tone_batch,
    get_api_call_count as get_tone_api_calls,
    reset_api_call_count as reset_tone_api_calls
)
from negative_summarizer import (
    summarize_negative_articles,
    get_summary_api_call_count,
    reset_summary_api_call_count
)
from export_excel import save_to_excel


def process_file_pipeline(
    excel_path: str,
    progress_path: str,
    output_excel_path: str
) -> dict:
    print("\n" + "=" * 80)
    print(f"MEMPROSES PIPELINE REVISI & RINGKASAN: {excel_path}")
    print("=" * 80)

    # 1. Baca data Excel
    df_raw = pd.read_excel(excel_path)
    raw_records = df_raw.to_dict(orient="records")
    print(f"[+] Total artikel awal di file: {len(raw_records)}")

    # 2. Muat teks dari progress.json
    text_map = {}
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            p_data = json.load(f)
            p_arts = p_data.get("articles", [])
            for a in p_arts:
                u = str(a.get("link") or a.get("resolved_url") or "").strip()
                txt = str(a.get("text") or a.get("content") or "").strip()
                if u:
                    text_map[u] = txt
                    clean_u = u.split("?")[0].rstrip("/")
                    text_map[clean_u] = txt
        print(f"[+] Berhasil memetakan teks dari progress.json: {len(text_map)} entri")

    # =========================================================================
    # BAGIAN 0.1: RE-FILTER RELEVANSI
    # =========================================================================
    filtered_records = []
    discarded_articles = []

    for r in raw_records:
        title = str(r.get("Title", "")).strip()
        url = str(r.get("Link Website", "")).strip()
        clean_url = url.split("?")[0].rstrip("/")
        txt = text_map.get(url) or text_map.get(clean_url) or ""

        # Cek filter struktural (termasuk noise ritel, bansos, brand awards, zakat, umkm mikro)
        if is_non_article_structural_noise(title=title, url=url, text=txt):
            discarded_articles.append({
                "Title": title,
                "Media Name": r.get("Media Name", ""),
                "Reason": "Noise struktural / ritel / bansos / brand award / UMKM mikro"
            })
            continue

        # Cek flag Kemenperin non-IA (ILMATE / Mesin)
        r_copy = dict(r)
        if "kemenperin" in title.lower() and ("industri mesin" in title.lower() or "ilmate" in title.lower()):
            r_copy["Status Review"] = "Perlu Dicek Manual: Kebijakan Kemenperin Sektor Non-IA (ILMATE)"

        filtered_records.append(r_copy)

    print(f"[+] Re-filter selesai: {len(filtered_records)} lolos | {len(discarded_articles)} dibuang.")
    if discarded_articles:
        print("    Artikel yang dibuang ulang:")
        for idx, d in enumerate(discarded_articles, start=1):
            print(f"      {idx}. {d['Title']} ({d['Media Name']})")

    # =========================================================================
    # BAGIAN 0.2, 0.3, 0.4: TONE KONSISTEN PER GRUP JUDUL & DASAR JUJUR
    # =========================================================================
    articles_payload = []
    for idx, r in enumerate(filtered_records, start=1):
        url = str(r.get("Link Website", "")).strip()
        clean_url = url.split("?")[0].rstrip("/")
        txt = text_map.get(url) or text_map.get(clean_url) or ""
        articles_payload.append({
            "id": idx,
            "title": str(r.get("Title", "")).strip(),
            "text": txt,
            "row_data": r
        })

    reset_tone_api_calls()
    tone_results = classify_tone_batch(articles_payload, use_ai=True, ensure_consistency=True)
    tone_calls = get_tone_api_calls()

    # Hitung jumlah grup yang tonenya diseragamkan
    from collections import defaultdict
    group_members = defaultdict(list)
    for p_item, res in zip(articles_payload, tone_results):
        gid = res.get("group_id", p_item["id"])
        group_members[gid].append((p_item, res))

    harmonized_groups = [g for g in group_members.values() if len(g) > 1]
    print(f"[+] Tone classification selesai: {len(group_members)} grup ({len(harmonized_groups)} grup memiliki >1 media/baris diseragamkan).")

    records_with_tone = []
    for p_item, res in zip(articles_payload, tone_results):
        row_data = p_item.get("row_data")
        row = dict(row_data) if isinstance(row_data, dict) else {}
        row["Tone"] = res["tone"]
        records_with_tone.append(row)

    # =========================================================================
    # BAGIAN 1: RINGKASAN OTOMATIS BERITA BERT ONE NEGATIF
    # =========================================================================
    reset_summary_api_call_count()
    neg_summaries = summarize_negative_articles(
        records_with_tone,
        progress_text_map=text_map,
        delay_between_batches=3.0
    )
    summary_calls = get_summary_api_call_count()

    # =========================================================================
    # BAGIAN 2: EKSPOR KE EXCEL (_ringkasan.xlsx)
    # =========================================================================
    save_to_excel(
        records_with_tone,
        output_excel_path,
        merge_existing=False,
        negative_summaries=neg_summaries
    )
    print(f"[+] Hasil tersimpan ke: {output_excel_path}")

    return {
        "file": os.path.basename(excel_path),
        "total_initial": len(raw_records),
        "total_filtered": len(filtered_records),
        "discarded": discarded_articles,
        "harmonized_groups_count": len(harmonized_groups),
        "harmonized_groups": harmonized_groups,
        "records_with_tone": records_with_tone,
        "tone_calls": tone_calls,
        "neg_summaries": neg_summaries,
        "summary_calls": summary_calls,
        "output_file": output_excel_path
    }


def main():
    f1 = "hasil_scrapping/Oktober/2026-10-07/all_2026-10-07_tone_revisi.xlsx"
    p1 = "hasil_scrapping/Oktober/2026-10-07/progress.json"
    o1 = "hasil_scrapping/Oktober/2026-10-07/all_2026-10-07_tone_revisi_ringkasan.xlsx"

    f2 = "hasil_scrapping/Oktober/2026-10-01_sd_2026-10-04/all_2026-10-01_sd_2026-10-04_tone_revisi.xlsx"
    p2 = "hasil_scrapping/Oktober/2026-10-01_sd_2026-10-04/progress.json"
    o2 = "hasil_scrapping/Oktober/2026-10-01_sd_2026-10-04/all_2026-10-01_sd_2026-10-04_tone_revisi_ringkasan.xlsx"

    print("=== MENJALANKAN PIPELINE PENGUJIAN LENGKAP ===")
    res1 = process_file_pipeline(f1, p1, o1)
    res2 = process_file_pipeline(f2, p2, o2)

    print("\n" + "=" * 80)
    print("SELESAI MEMPROSES KEDUA FILE.")
    print("=" * 80)


if __name__ == "__main__":
    main()
