"""
eval_tone.py
Skrip evaluasi performa klasifikasi tone (Positif, Netral, Negatif):
- Membaca golden set CSV (kolom: title, label_benar).
- Menghasilkan Confusion Matrix 3x3, Akurasi Global, Precision, Recall, dan F1 per kelas.
- Menghitung persentase prediksi Negatif vs persentase Negatif sebenarnya (bias check).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

# Pastikan root workspace ada di sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.tone_classifier import classify_tone_batch, classify_tone_fallback

CLASSES = ["Positif", "Netral", "Negatif"]


def load_golden_set(csv_path: str | Path) -> list[dict]:
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"File golden set tidak ditemukan: {p}")

    records = []
    with open(p, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"File {p} kosong.")

        # Temukan nama kolom yang cocok (toleransi huruf besar/kecil)
        fnames = {fn.strip().lower(): fn for fn in reader.fieldnames}
        t_col = fnames.get("title") or fnames.get("judul")
        l_col = fnames.get("label_benar") or fnames.get("label") or fnames.get("tone_benar") or fnames.get("actual")

        if not t_col or not l_col:
            raise ValueError(
                f"Kolom wajib 'title' dan 'label_benar' tidak lengkap di {p}. "
                f"Kolom terbaca: {reader.fieldnames}"
            )

        for row_idx, row in enumerate(reader, start=2):
            title = (row.get(t_col) or "").strip()
            label = (row.get(l_col) or "").strip().capitalize()
            if not title:
                continue
            if label not in CLASSES:
                print(f"[Warning] Baris {row_idx}: label '{label}' tidak dikenal, dilewati.", file=sys.stderr)
                continue
            records.append({
                "id": len(records) + 1,
                "title": title,
                "label_benar": label,
            })

    return records


def evaluate_predictions(records: list[dict], predictions: list[dict]) -> dict:
    total = len(records)
    if total == 0:
        return {"total": 0}

    # Confusion matrix: cm[actual][predicted]
    cm = {c_act: {c_pred: 0 for c_pred in CLASSES} for c_act in CLASSES}
    correct = 0
    pred_counts = defaultdict(int)
    actual_counts = defaultdict(int)
    misclassified = []

    for rec, pred in zip(records, predictions):
        act = rec["label_benar"]
        pr = str(pred.get("tone") or "Netral").capitalize()
        if pr not in CLASSES:
            pr = "Netral"

        cm[act][pr] += 1
        actual_counts[act] += 1
        pred_counts[pr] += 1

        if act == pr:
            correct += 1
        else:
            misclassified.append({
                "title": rec["title"],
                "actual": act,
                "predicted": pr,
                "alasan": pred.get("alasan", "-"),
                "dasar": pred.get("dasar", "-"),
            })

    accuracy = (correct / total * 100.0) if total > 0 else 0.0

    # Per-class metrics
    class_metrics = {}
    for c in CLASSES:
        tp = cm[c][c]
        fp = sum(cm[other][c] for other in CLASSES if other != c)
        fn = sum(cm[c][other] for other in CLASSES if other != c)

        prec = (tp / (tp + fp) * 100.0) if (tp + fp) > 0 else 0.0
        rec = (tp / (tp + fn) * 100.0) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

        class_metrics[c] = {
            "support": actual_counts[c],
            "predicted_count": pred_counts[c],
            "precision": prec,
            "recall": rec,
            "f1": f1,
        }

    # Analisis bias negatif
    actual_neg = actual_counts["Negatif"]
    pred_neg = pred_counts["Negatif"]
    pct_actual_neg = (actual_neg / total * 100.0) if total > 0 else 0.0
    pct_pred_neg = (pred_neg / total * 100.0) if total > 0 else 0.0
    neg_ratio = (pred_neg / actual_neg) if actual_neg > 0 else (0.0 if pred_neg == 0 else float("inf"))

    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "confusion_matrix": cm,
        "class_metrics": class_metrics,
        "pct_actual_neg": pct_actual_neg,
        "pct_pred_neg": pct_pred_neg,
        "neg_ratio": neg_ratio,
        "misclassified": misclassified,
    }


def print_evaluation_report(results: dict, mode_label: str = "Fallback Rule-Based"):
    total = results["total"]
    if total == 0:
        print("Tidak ada data untuk dievaluasi.")
        return

    cm = results["confusion_matrix"]
    cm_metrics = results["class_metrics"]

    print("=" * 75)
    print(f"LAPORAN EVALUASI TONE CLASSIFIER ({mode_label})")
    print(f"Total Dataset Golden: {total} artikel")
    print(f"Akurasi Global      : {results['accuracy']:.2f}% ({results['correct']}/{total} benar)")
    print("=" * 75)

    print("\n[1] CONFUSION MATRIX (Baris = Aktual / Kolom = Prediksi)")
    print("-" * 55)
    header = f"{'Aktual \\ Pred':<15} | {'Positif':<8} | {'Netral':<8} | {'Negatif':<8} | {'Total':<6}"
    print(header)
    print("-" * 55)
    for act in CLASSES:
        row_str = f"{act:<15} | " + " | ".join(f"{cm[act][p]:<8}" for p in CLASSES)
        row_tot = sum(cm[act][p] for p in CLASSES)
        row_str += f" | {row_tot:<6}"
        print(row_str)
    print("-" * 55)

    print("\n[2] METRIK PER KELAS")
    print("-" * 75)
    print(f"{'Kelas':<10} | {'Aktual (N)':<12} | {'Prediksi (N)':<12} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10}")
    print("-" * 75)
    for c in CLASSES:
        m = cm_metrics[c]
        print(
            f"{c:<10} | {m['support']:<12} | {m['predicted_count']:<12} | "
            f"{m['precision']:>9.1f}% | {m['recall']:>9.1f}% | {m['f1']:>9.1f}%"
        )
    print("-" * 75)

    print("\n[3] ANALISIS BIAS NEGATIF")
    print("-" * 75)
    print(f"Persentase Sebenarnya Negatif : {results['pct_actual_neg']:.1f}%")
    print(f"Persentase Prediksi Negatif   : {results['pct_pred_neg']:.1f}%")
    print(f"Rasio Prediksi vs Sebenarnya  : {results['neg_ratio']:.2f}x", end="")
    if 0.9 <= results["neg_ratio"] <= 1.1:
        print(" (Ideal / Seimbang)")
    elif results["neg_ratio"] > 1.1:
        print(" (Peringatan: Cenderung Over-predicting Negatif)")
    else:
        print(" (Peringatan: Cenderung Under-predicting Negatif)")
    print("-" * 75)

    mis = results["misclassified"]
    if mis:
        print(f"\n[4] DAFTAR SALAH PREDIKSI ({len(mis)} artikel):")
        print("-" * 75)
        for idx, m in enumerate(mis, start=1):
            print(f"{idx}. Judul    : {m['title']}")
            print(f"   Aktual   : {m['actual']} -> Prediksi: {m['predicted']}")
            print(f"   Alasan   : {m['alasan']}")
            print("-" * 75)
    else:
        print("\n[4] DAFTAR SALAH PREDIKSI: 0 artikel (100% Sempurna pada Golden Set)")
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Evaluasi Tone Classifier terhadap Golden Set")
    parser.add_argument("csv_path", nargs="?", default="data/golden_tone_dataset.csv", help="Path file CSV golden set")
    parser.add_argument("--use-ai", action="store_true", help="Gunakan Gemini API (memerlukan GEMINI_API_KEY)")
    args = parser.parse_args()

    records = load_golden_set(args.csv_path)

    if args.use_ai:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            print("[Warning] GEMINI_API_KEY tidak ditemukan di environment. Beralih ke fallback.", file=sys.stderr)
            use_ai_flag = False
            mode_label = "Fallback Rule-Based (API Key Tidak Ada)"
        else:
            use_ai_flag = True
            mode_label = "Gemini AI API (Batch Classifier)"
    else:
        use_ai_flag = False
        mode_label = "Fallback Rule-Based"

    # Prediksi
    if use_ai_flag:
        predictions = classify_tone_batch(records, use_ai=True, ensure_consistency=False)
    else:
        predictions = []
        for r in records:
            tone, dasar, alasan = classify_tone_fallback(r["title"], "")
            predictions.append({
                "id": r["id"],
                "tone": tone,
                "dasar": dasar,
                "alasan": alasan,
                "metode": "fallback",
            })

    results = evaluate_predictions(records, predictions)
    print_evaluation_report(results, mode_label=mode_label)


if __name__ == "__main__":
    main()
