"""
eval_tone.py
Skrip evaluasi performa klasifikasi tone (Positif, Netral, Negatif):
- Mode Blind + Key (utama): membaca data/label_tone_blind.csv (label manusia) dan
  data/label_tone_key.csv (prediksi model) berdasar kolom id.
- Mode Golden Set (kompatibilitas): membaca satu CSV (kolom: title, label_benar).
- Menghasilkan Confusion Matrix 3x3, Akurasi Global, Precision, Recall, F1 per kelas,
  Recall Negatif terpisah, dan pembanding baseline "selalu Netral".
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
DEFAULT_BLIND_PATH = Path("data/label_tone_blind.csv")
DEFAULT_KEY_PATH = Path("data/label_tone_key.csv")


def _norm_tone(val: str | None) -> str:
    s = (val or "").strip().capitalize()
    return s if s in CLASSES else ""


def load_blind_and_key(
    blind_path: str | Path = DEFAULT_BLIND_PATH,
    key_path: str | Path = DEFAULT_KEY_PATH,
) -> tuple[list[dict], list[dict], dict]:
    """
    Membaca file blind (label manusia) dan file key (output model), dicocokkan lewat kolom id.
    Hanya baris dengan tone_manusia terisi valid yang masuk ke evaluasi.
    """
    bp = Path(blind_path)
    kp = Path(key_path)
    if not bp.exists():
        raise FileNotFoundError(f"File blind tidak ditemukan: {bp}")
    if not kp.exists():
        raise FileNotFoundError(f"File key tidak ditemukan: {kp}")

    key_by_id: dict[str, dict] = {}
    with open(kp, mode="r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rid = (row.get("id") or "").strip()
            if rid:
                key_by_id[rid] = {
                    "id": rid,
                    "tone": _norm_tone(row.get("tone_model")) or "Netral",
                    "kategori_K_model": (row.get("kategori_K_model") or "").strip().upper(),
                    "alasan": (row.get("alasan_tone") or "").strip(),
                }

    records: list[dict] = []
    predictions: list[dict] = []
    total_blind = 0
    unlabeled = 0
    invalid_labels = 0
    missing_in_key = 0

    with open(bp, mode="r", encoding="utf-8-sig") as f:
        for row_idx, row in enumerate(csv.DictReader(f), start=2):
            rid = (row.get("id") or "").strip()
            judul = (row.get("judul") or row.get("title") or "").strip()
            if not rid and not judul:
                continue
            total_blind += 1
            raw_human = (row.get("tone_manusia") or "").strip()
            if not raw_human:
                unlabeled += 1
                continue
            human_tone = _norm_tone(raw_human)
            if not human_tone:
                invalid_labels += 1
                print(f"[Warning] Baris {row_idx} (id={rid}): tone_manusia '{raw_human}' tidak valid, dilewati.", file=sys.stderr)
                continue
            if rid not in key_by_id:
                missing_in_key += 1
                print(f"[Warning] Baris {row_idx}: id '{rid}' tidak ditemukan di {kp}, dilewati.", file=sys.stderr)
                continue

            records.append({
                "id": rid,
                "title": judul,
                "label_benar": human_tone,
                "kategori_K": (row.get("kategori_K") or "").strip().upper(),
            })
            predictions.append(key_by_id[rid])

    meta = {
        "total_blind_rows": total_blind,
        "labeled_rows": len(records),
        "unlabeled_rows": unlabeled,
        "invalid_labels": invalid_labels,
        "missing_in_key": missing_in_key,
    }
    return records, predictions, meta


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

    # Analisis bias negatif & metrik ringkas
    actual_neg = actual_counts["Negatif"]
    pred_neg = pred_counts["Negatif"]
    pct_actual_neg = (actual_neg / total * 100.0) if total > 0 else 0.0
    pct_pred_neg = (pred_neg / total * 100.0) if total > 0 else 0.0
    neg_ratio = (pred_neg / actual_neg) if actual_neg > 0 else (0.0 if pred_neg == 0 else float("inf"))
    macro_f1 = sum(class_metrics[c]["f1"] for c in CLASSES) / len(CLASSES)
    recall_negatif = class_metrics["Negatif"]["recall"]

    # Baseline "selalu Netral" pada himpunan yang sama
    neutral_correct = actual_counts["Netral"]
    neutral_acc = (neutral_correct / total * 100.0) if total > 0 else 0.0
    neutral_prec = neutral_acc
    neutral_rec = 100.0 if neutral_correct > 0 else 0.0
    neutral_f1 = (2 * neutral_prec * neutral_rec / (neutral_prec + neutral_rec)) if (neutral_prec + neutral_rec) > 0 else 0.0
    baseline_always_neutral = {
        "correct": neutral_correct,
        "accuracy": neutral_acc,
        "macro_f1": neutral_f1 / len(CLASSES),
        "recall_negatif": 0.0,
        "netral_f1": neutral_f1,
    }

    # Kesesuaian kategori K (bila manusia & key sama-sama mengisi K1-K4)
    k_pairs = [
        (r.get("kategori_K", ""), p.get("kategori_K_model", ""))
        for r, p in zip(records, predictions)
        if r.get("kategori_K") and p.get("kategori_K_model")
    ]
    k_match = sum(1 for a, b in k_pairs if a == b)

    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "recall_negatif": recall_negatif,
        "confusion_matrix": cm,
        "class_metrics": class_metrics,
        "baseline_always_neutral": baseline_always_neutral,
        "k_evaluated": len(k_pairs),
        "k_correct": k_match,
        "k_accuracy": (k_match / len(k_pairs) * 100.0) if k_pairs else None,
        "pct_actual_neg": pct_actual_neg,
        "pct_pred_neg": pct_pred_neg,
        "neg_ratio": neg_ratio,
        "misclassified": misclassified,
    }


def print_evaluation_report(results: dict, mode_label: str = "Fallback Rule-Based", blind_meta: dict | None = None):
    total = results.get("total", 0)
    if total == 0:
        if blind_meta is not None:
            print("=" * 75)
            print(f"LAPORAN EVALUASI TONE CLASSIFIER ({mode_label})")
            print(
                f"Belum ada label manusia terisi (0/{blind_meta['total_blind_rows']} baris). "
                "Isi kolom 'tone_manusia' pada data/label_tone_blind.csv terlebih dahulu."
            )
            print("=" * 75)
        else:
            print("Tidak ada data untuk dievaluasi.")
        return

    cm = results["confusion_matrix"]
    cm_metrics = results["class_metrics"]
    base = results["baseline_always_neutral"]

    print("=" * 75)
    print(f"LAPORAN EVALUASI TONE CLASSIFIER ({mode_label})")
    if blind_meta is not None:
        print(f"Baris Berlabel      : {total}/{blind_meta['total_blind_rows']} baris (belum dilabel: {blind_meta['unlabeled_rows']})")
    else:
        print(f"Total Dataset       : {total} artikel")
    print(f"Akurasi Global      : {results['accuracy']:.2f}% ({results['correct']}/{total} benar)")
    print(f"Macro F1 (3 kelas)  : {results['macro_f1']:.2f}%")
    print(f"Recall Negatif      : {results['recall_negatif']:.2f}% (aktual Negatif: {cm_metrics['Negatif']['support']})")
    if results.get("k_evaluated"):
        print(f"Akurasi Kategori K  : {results['k_accuracy']:.2f}% ({results['k_correct']}/{results['k_evaluated']})")
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

    print("\n[3] RECALL NEGATIF & BASELINE 'SELALU NETRAL'")
    print("-" * 75)
    print(f"Recall Negatif (Model)           : {results['recall_negatif']:.2f}% (aktual={cm_metrics['Negatif']['support']}, prediksi={cm_metrics['Negatif']['predicted_count']})")
    print(f"Baseline Selalu Netral - Akurasi : {base['accuracy']:.2f}% ({base['correct']}/{total}) | selisih model: {results['accuracy'] - base['accuracy']:+.2f} pp")
    print(f"Baseline Selalu Netral - MacroF1 : {base['macro_f1']:.2f}% | selisih model: {results['macro_f1'] - base['macro_f1']:+.2f} pp")
    print(f"Baseline Selalu Netral - RecNeg  : {base['recall_negatif']:.2f}%")
    print(f"Persentase Sebenarnya Negatif    : {results['pct_actual_neg']:.1f}%")
    print(f"Persentase Prediksi Negatif      : {results['pct_pred_neg']:.1f}%")
    print(f"Rasio Prediksi vs Sebenarnya     : {results['neg_ratio']:.2f}x", end="")
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
        print("\n[4] DAFTAR SALAH PREDIKSI: 0 artikel")
    print("=" * 75 + "\n")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Evaluasi Tone Classifier (Blind+Key atau Golden Set)")
    parser.add_argument("csv_path", nargs="?", default=None, help="Path file CSV golden set (mode legacy)")
    parser.add_argument("--blind", default=None, help="Path file blind berlabel manusia (default: data/label_tone_blind.csv)")
    parser.add_argument("--key", default=None, help="Path file key prediksi model (default: data/label_tone_key.csv)")
    parser.add_argument("--use-ai", action="store_true", help="Gunakan Gemini API (khusus mode golden set legacy)")
    args = parser.parse_args(argv)

    use_blind_mode = (
        args.blind is not None
        or args.key is not None
        or (args.csv_path is None and DEFAULT_BLIND_PATH.exists() and DEFAULT_KEY_PATH.exists())
    )

    if use_blind_mode:
        blind_path = Path(args.blind) if args.blind else DEFAULT_BLIND_PATH
        key_path = Path(args.key) if args.key else DEFAULT_KEY_PATH
        records, predictions, meta = load_blind_and_key(blind_path, key_path)
        results = evaluate_predictions(records, predictions)
        print_evaluation_report(
            results,
            mode_label=f"Blind vs Key ({blind_path.name} vs {key_path.name})",
            blind_meta=meta,
        )
        return

    csv_path = args.csv_path or "data/golden_tone_dataset.csv"
    records = load_golden_set(csv_path)

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
