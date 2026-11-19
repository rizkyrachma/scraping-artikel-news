"""
make_isu_review_sheet.py
Menghasilkan lembar kerja CSV (data/isu_review_sheet.csv) dari data nyata untuk ditinjau manusia.
Kolom wajib: id, judul, isu_diberikan, sumber_isu, skor, margin, benar_sama_isu (kosong untuk diisi 1 atau 0).
Mengambil sampel berimbang dari skor tinggi, sedang, rendah/ambigu, serta tiap sumber_isu (rilis dan klaster).
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.isu_grouping import (
    IsuRegistry,
    assign_and_cluster_issues,
    clean_display_title,
    load_rilis_kemenperin,
)

REVIEW_COLUMNS = [
    "id",
    "judul",
    "isu_diberikan",
    "sumber_isu",
    "skor",
    "margin",
    "benar_sama_isu",
]


def load_real_articles_from_excels(excel_paths: list[str]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for p in excel_paths:
        if not os.path.exists(p):
            continue
        try:
            df = pd.read_excel(p, sheet_name="Berita")
        except Exception:
            try:
                df = pd.read_excel(p)
            except Exception:
                continue
        for _, row in df.iterrows():
            title = str(row.get("Title") or row.get("title") or "").strip()
            if not title or title.lower() in ("nan", "none"):
                continue
            key = clean_display_title(title).lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            articles.append({
                "id": f"art_{len(articles) + 1}",
                "title": title,
                "published": str(row.get("Tanggal") or row.get("published") or ""),
                "link": str(row.get("Link Website") or row.get("link") or ""),
                "media_name": str(row.get("Media Name") or row.get("media_name") or ""),
                "Tone": str(row.get("Tone") or "Netral"),
            })
    return articles


def select_balanced_review_sample(
    assigned: list[dict[str, Any]],
    max_samples: int = 60,
) -> list[dict[str, Any]]:
    """
    Memilih sampel berimbang dari:
    - Semua anggota klaster multi-berita (ukuran >= 2) dan berita yang cocok ke rilis
    - Strata skor tinggi (>= 0.65), sedang (0.42 - 0.65), dan rendah/ambigu (< 0.42)
    - Perwakilan klaster tunggal sebagai kontrol
    """
    isu_counts: dict[str, int] = {}
    for a in assigned:
        iid = str(a.get("isu_id") or "")
        isu_counts[iid] = isu_counts.get(iid, 0) + 1

    rilis_items = [a for a in assigned if a.get("sumber_isu") == "rilis"]
    multi_cluster_items = [
        a for a in assigned
        if a.get("sumber_isu") == "klaster" and isu_counts.get(str(a.get("isu_id") or ""), 0) >= 2
    ]
    single_cluster_items = [
        a for a in assigned
        if a.get("sumber_isu") == "klaster" and isu_counts.get(str(a.get("isu_id") or ""), 0) == 1
    ]

    # Bagi multi_cluster_items ke dalam strata skor
    high_score = [a for a in multi_cluster_items if float(a.get("skor_isu", 0.0)) >= 0.65]
    mid_score = [a for a in multi_cluster_items if 0.45 <= float(a.get("skor_isu", 0.0)) < 0.65]
    low_score = [a for a in multi_cluster_items if float(a.get("skor_isu", 0.0)) < 0.45]

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _add_bucket(bucket: list[dict[str, Any]], limit: int) -> None:
        count = 0
        for item in bucket:
            if count >= limit or len(selected) >= max_samples:
                break
            aid = str(item.get("id"))
            if aid not in seen_ids:
                seen_ids.add(aid)
                selected.append(item)
                count += 1

    quota_each = max(8, max_samples // 4)
    # Prioritaskan artikel dari batch/file pertama (misal fixture nyata 17 Nov: art_1 s.d. art_23)
    priority_items = [a for a in assigned if str(a.get("id", "")).startswith("art_") and int(str(a["id"]).split("_")[1]) <= 23]
    _add_bucket(priority_items, 23)
    _add_bucket(rilis_items, quota_each)
    _add_bucket(low_score, quota_each)
    _add_bucket(mid_score, quota_each)
    _add_bucket(high_score, quota_each)
    _add_bucket(multi_cluster_items, max_samples - min(8, len(single_cluster_items)))
    _add_bucket(single_cluster_items, max_samples)

    return selected


def generate_review_csv(
    excel_paths: list[str],
    output_csv: str | os.PathLike = "data/isu_review_sheet.csv",
    max_samples: int = 60,
) -> Path:
    articles = load_real_articles_from_excels(excel_paths)
    reg = IsuRegistry(filepath="hasil_scrapping/isu_registry_review_tmp.json")
    reg.issues.clear()
    reg.seed_releases(load_rilis_kemenperin())

    assigned = assign_and_cluster_issues(
        articles,
        registry=reg,
        method="tfidf",
        use_ai=False,
        log_path=None,
        coverage_path=None,
    )
    sampled = select_balanced_review_sample(assigned, max_samples=max_samples)

    out_p = Path(output_csv)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for item in sampled:
            writer.writerow({
                "id": item.get("id", ""),
                "judul": clean_display_title(str(item.get("title") or "")),
                "isu_diberikan": item.get("isu", ""),
                "sumber_isu": item.get("sumber_isu", "klaster"),
                "skor": f"{float(item.get('skor_isu', 0.0)):.4f}",
                "margin": f"{float(item.get('margin_isu', 0.0)):.4f}",
                "benar_sama_isu": "",
            })

    try:
        Path("hasil_scrapping/isu_registry_review_tmp.json").unlink(missing_ok=True)
    except Exception:
        pass
    return out_p


def main() -> None:
    parser = argparse.ArgumentParser(description="Buat CSV review pengelompokan isu dari data nyata")
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Path file Excel (.xlsx). Kosongkan untuk otomatis membaca file Excel November yang tersedia.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="data/isu_review_sheet.csv",
        help="Path output CSV review (default: data/isu_review_sheet.csv)",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=60,
        help="Jumlah maksimum sampel baris review (default: 60)",
    )
    args = parser.parse_args()

    excel_files = list(args.inputs)
    if not excel_files:
        uploaded_17 = r"C:\Users\Hallo\.gemini\antigravity\brain\bded542c-a6f5-4748-859b-e94a0213ea29\.user_uploaded\media_1794972024573_ddea845b.xlsx"
        if os.path.exists(uploaded_17):
            excel_files.append(uploaded_17)
        excel_files.extend(sorted(glob.glob("hasil_scrapping/November/**/*_ringkasan.xlsx", recursive=True)))

    out_path = generate_review_csv(excel_files, output_csv=args.output, max_samples=args.max_samples)
    print(f"[OK] File CSV review berhasil dibuat: {out_path}")


if __name__ == "__main__":
    main()
