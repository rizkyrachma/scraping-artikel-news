"""
eval_isu.py
Membaca CSV review pengelompokan isu yang sudah diisi manusia (kolom benar_sama_isu: 1 atau 0),
lalu menghitung precision penugasan per ambang skor dan margin serta persentase coverage.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Any


def load_filled_review_csv(csv_path: str | Path) -> tuple[list[dict[str, Any]], int]:
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"File CSV review tidak ditemukan: {p}")

    filled_rows: list[dict[str, Any]] = []
    total_rows = 0
    with open(p, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            raw_lbl = str(row.get("benar_sama_isu") or "").strip()
            if raw_lbl not in ("0", "1"):
                continue
            try:
                skor = float(row.get("skor") or 0.0)
            except ValueError:
                skor = 0.0
            try:
                margin = float(row.get("margin") or 0.0)
            except ValueError:
                margin = 0.0
            filled_rows.append({
                "id": str(row.get("id") or ""),
                "judul": str(row.get("judul") or ""),
                "isu_diberikan": str(row.get("isu_diberikan") or ""),
                "sumber_isu": str(row.get("sumber_isu") or "klaster"),
                "skor": skor,
                "margin": margin,
                "benar": int(raw_lbl),
            })
    return filled_rows, total_rows


def evaluate_isu_review(
    filled_rows: list[dict[str, Any]],
    score_thresholds: tuple[float, ...] = (0.35, 0.42, 0.48, 0.55, 0.65),
    margin_thresholds: tuple[float, ...] = (0.00, 0.05, 0.10),
) -> dict[str, Any]:
    n = len(filled_rows)
    if n == 0:
        return {"filled_count": 0}

    overall_correct = sum(r["benar"] for r in filled_rows)
    overall_precision = (overall_correct / n) * 100.0

    by_source: dict[str, dict[str, float]] = {}
    for src in ("rilis", "klaster"):
        sub = [r for r in filled_rows if r["sumber_isu"] == src]
        if sub:
            c = sum(r["benar"] for r in sub)
            by_source[src] = {
                "count": len(sub),
                "correct": c,
                "precision_pct": round(c / len(sub) * 100.0, 2),
            }

    grid_results = []
    for s_th in score_thresholds:
        for m_th in margin_thresholds:
            accepted = [r for r in filled_rows if r["skor"] >= s_th and r["margin"] >= m_th]
            cov_pct = (len(accepted) / n) * 100.0
            if accepted:
                prec_pct = (sum(r["benar"] for r in accepted) / len(accepted)) * 100.0
            else:
                prec_pct = 0.0
            grid_results.append({
                "score_th": s_th,
                "margin_th": m_th,
                "accepted": len(accepted),
                "coverage_pct": round(cov_pct, 1),
                "precision_pct": round(prec_pct, 1),
            })

    return {
        "filled_count": n,
        "overall_correct": overall_correct,
        "overall_precision_pct": round(overall_precision, 2),
        "by_source": by_source,
        "grid": grid_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluasi precision dan coverage dari CSV review isu")
    parser.add_argument(
        "csv_path",
        nargs="?",
        default="data/isu_review_sheet.csv",
        help="Path CSV review (default: data/isu_review_sheet.csv)",
    )
    args = parser.parse_args()

    filled, total = load_filled_review_csv(args.csv_path)
    print("=" * 72)
    print(f"EVALUASI PENUGASAN ISU (File: {args.csv_path})")
    print(f"Total Baris di CSV : {total}")
    print(f"Baris Terisi (1/0) : {len(filled)}")
    print("=" * 72)

    if not filled:
        print(
            "\n[INFO] Kolom 'benar_sama_isu' belum diisi manusia (masih kosong).\n"
            "Silakan isi kolom 'benar_sama_isu' dengan 1 (benar satu isu) atau 0 (salah tempel)\n"
            "sesuai panduan di docs/README_ISU_REVIEW.md, lalu jalankan kembali skrip ini."
        )
        return

    res = evaluate_isu_review(filled)
    print(f"\nPrecision Keseluruhan : {res['overall_precision_pct']:.2f}% ({res['overall_correct']}/{res['filled_count']})")

    print("\n--- Rincian per Sumber Isu ---")
    for src, info in res["by_source"].items():
        print(f"  - {src:<8}: Precision {info['precision_pct']:.2f}% ({info['correct']}/{info['count']} baris)")

    print("\n--- Tabel Precision & Coverage per Ambang Skor dan Margin ---")
    print(f"{'Ambang Skor':<14} | {'Ambang Margin':<14} | {'Lolos (N)':<10} | {'Coverage %':<12} | {'Precision %':<12}")
    print("-" * 72)
    for g in res["grid"]:
        print(
            f">= {g['score_th']:<11.2f} | >= {g['margin_th']:<11.2f} | "
            f"{g['accepted']:<10} | {g['coverage_pct']:>10.1f}% | {g['precision_pct']:>10.1f}%"
        )
    print("=" * 72)


if __name__ == "__main__":
    main()
