"""
src/verify_reporter.py
Modul pelaporan hasil verifikasi decode dan ekstraksi (Poin A Benchmark) untuk 19 batch.
Menghasilkan tabel ringkasan Markdown, CSV, dan metrik agregasi B1-B7 vs B8-B19.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path


def _aggregate_batch_slice(batch_reports: list[dict], start_b: int, end_b: int) -> dict:
    selected = [b for b in batch_reports if start_b <= int(b.get("batch_num", 0)) <= end_b]
    tot_gnews = 0
    dec_ok = 0
    rej = 0
    pre = 0
    fb_meta = 0
    fb_search = 0
    dec_fail = 0
    ext_ok = 0
    ext_tot = 0
    serp = 0
    exa = 0
    sorry = 0
    duration = 0.0

    for b in selected:
        ds = b.get("decode_stats") or {}
        tot_gnews += int(ds.get("gnews_total", 0) or 0)
        dec_ok += int(ds.get("decode_ok", 0) or 0)
        rej += int(ds.get("rejected_target", 0) or 0)
        pre += int(ds.get("pre_filtered", 0) or 0)
        fb_meta += int(ds.get("fallback_meta", 0) or 0)
        fb_search += int(ds.get("fallback_search", 0) or 0)
        dec_fail += int(ds.get("decode_fail", 0) or 0)
        ext_ok += int(ds.get("extract_ok", 0) or 0)
        ext_tot += int(ds.get("extract_total", 0) or 0)
        serp += int(b.get("serper_calls", 0) or 0)
        exa += int(b.get("exa_calls", 0) or 0)
        sorry += int(b.get("sorry_index_count", 0) or 0)
        duration += float(b.get("duration_sec", 0.0) or 0.0)

    denom = max(0, tot_gnews - rej - pre)
    fail_rate = (dec_fail / denom * 100.0) if denom > 0 else 0.0
    ext_rate = (ext_ok / ext_tot * 100.0) if ext_tot > 0 else 0.0

    return {
        "batch_range": f"B{start_b}-B{end_b}",
        "batch_count": len(selected),
        "total_gnews": tot_gnews,
        "decode_ok": dec_ok,
        "rejected": rej,
        "pre_filtered": pre,
        "fallback_meta": fb_meta,
        "fallback_search": fb_search,
        "decode_fail": dec_fail,
        "eval_denom": denom,
        "fail_rate_pct": round(fail_rate, 1),
        "extract_ok": ext_ok,
        "extract_total": ext_tot,
        "extract_rate_pct": round(ext_rate, 1),
        "serper_calls": serp,
        "exa_calls": exa,
        "sorry_index_count": sorry,
        "duration_sec": round(duration, 1),
    }


def generate_verification_report(batch_reports: list[dict], output_dir: str | Path | None = None) -> dict:
    """
    Menghasilkan tabel metrik per batch dan perbandingan B1-7 vs B8-19.
    Menyimpan file markdown dan CSV jika output_dir diberikan.
    """
    summary_b1_7 = _aggregate_batch_slice(batch_reports, 1, 7)
    summary_b8_19 = _aggregate_batch_slice(batch_reports, 8, 19)
    summary_all = _aggregate_batch_slice(batch_reports, 1, 999)

    target_passed = (summary_b8_19["fail_rate_pct"] < 40.0) if summary_b8_19["batch_count"] > 0 else False

    # Buat tabel baris per batch
    rows = []
    for b in batch_reports:
        b_num = int(b.get("batch_num", 0))
        ds = b.get("decode_stats") or {}
        g_tot = int(ds.get("gnews_total", 0) or 0)
        d_ok = int(ds.get("decode_ok", 0) or 0)
        rej = int(ds.get("rejected_target", 0) or 0)
        pre = int(ds.get("pre_filtered", 0) or 0)
        fb_m = int(ds.get("fallback_meta", 0) or 0)
        fb_s = int(ds.get("fallback_search", 0) or 0)
        d_fail = int(ds.get("decode_fail", 0) or 0)
        denom = max(0, g_tot - rej - pre)
        f_pct = (d_fail / denom * 100.0) if denom > 0 else 0.0

        e_ok = int(ds.get("extract_ok", 0) or 0)
        e_tot = int(ds.get("extract_total", 0) or 0)
        e_pct = (e_ok / e_tot * 100.0) if e_tot > 0 else 0.0

        serp = int(b.get("serper_calls", 0) or 0)
        exa = int(b.get("exa_calls", 0) or 0)
        sorry = int(b.get("sorry_index_count", 0) or 0)
        cb_st = str(b.get("circuit_breaker_state", "CLOSED") or "CLOSED")
        dur = float(b.get("duration_sec", 0.0) or 0.0)

        rows.append({
            "Batch": f"B{b_num}",
            "Total GNews": g_tot,
            "Decode OK": d_ok,
            "Rejected": rej,
            "PreFiltered": pre,
            "Fallback Meta": fb_m,
            "Fallback Search": fb_s,
            "Gagal": d_fail,
            "Fail %": f"{f_pct:.1f}%",
            "ExtractOK": f"{e_ok}/{e_tot} ({e_pct:.0f}%)",
            "Serper": serp,
            "Exa": exa,
            "Sorry/Index": sorry,
            "CB Status": cb_st,
            "Durasi (s)": f"{dur:.1f}",
        })

    # Render Markdown
    md_buf = io.StringIO()
    md_buf.write("# Hasil Verifikasi Poin A: Benchmark Decode Google News (19 Batch)\n\n")
    status_label = "✅ LOLOS (< 40%)" if target_passed else "❌ BELUM LOLOS (>= 40%)"
    md_buf.write(f"**Status Target Batch 8-19:** {status_label} (Failure Rate: **{summary_b8_19['fail_rate_pct']}%**)\n\n")

    md_buf.write("### Perbandingan Agregat (B1-B7 vs B8-B19)\n\n")
    md_buf.write("| Segment | Batches | Total GNews | Decode OK | Rejected | PreFiltered | Gagal | Failure Rate % | ExtractOK Rate % | Serper Calls | Exa Calls | Sorry/Index | Durasi Total |\n")
    md_buf.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for s in (summary_b1_7, summary_b8_19, summary_all):
        md_buf.write(
            f"| **{s['batch_range']}** | {s['batch_count']} | {s['total_gnews']} | {s['decode_ok']} | {s['rejected']} | "
            f"{s['pre_filtered']} | {s['decode_fail']} | **{s['fail_rate_pct']}%** | {s['extract_rate_pct']}% | "
            f"{s['serper_calls']} | {s['exa_calls']} | {s['sorry_index_count']} | {s['duration_sec']:.1f}s |\n"
        )
    md_buf.write("\n> *Catatan:* Failure Rate dihitung dengan rumus: `Gagal / (Total GNews - Rejected - PreFiltered)`. Item `Rejected` (non-artikel / job portal) dan `PreFiltered` tidak dihitung sebagai kegagalan decoder.\n\n")

    md_buf.write("### Tabel Rincian per Batch\n\n")
    headers = ["Batch", "Total GNews", "Decode OK", "Rejected", "PreFiltered", "Fallback Meta", "Fallback Search", "Gagal", "Fail %", "ExtractOK", "Serper", "Exa", "Sorry/Index", "CB Status", "Durasi (s)"]
    md_buf.write("| " + " | ".join(headers) + " |\n")
    md_buf.write("| " + " | ".join(["---"] * len(headers)) + " |\n")
    for r in rows:
        md_buf.write("| " + " | ".join(str(r[h]) for h in headers) + " |\n")
    md_buf.write("\n")

    md_text = md_buf.getvalue()

    # Render CSV
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=headers)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    csv_text = csv_buf.getvalue()

    # Simpan file jika direktori ditentukan
    if output_dir:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        (out_p / "verification_point_a_report.md").write_text(md_text, encoding="utf-8")
        (out_p / "verification_point_a_metrics.csv").write_text(csv_text, encoding="utf-8")

    # Tulis ke GitHub Step Summary jika dijalankan di GitHub Actions
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        try:
            with open(gh_summary, "a", encoding="utf-8") as f:
                f.write(md_text)
        except Exception:
            pass

    return {
        "table_md": md_text,
        "table_csv": csv_text,
        "summary_b1_b7": summary_b1_7,
        "summary_b8_b19": summary_b8_19,
        "summary_all": summary_all,
        "target_passed": target_passed,
        "rows": rows,
    }
