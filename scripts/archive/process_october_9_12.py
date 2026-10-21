"""
process_october_9_12.py
Memproses filter ulang relevansi, konsistensi tone, dan pembuatan ringkasan 5W+1H berita bertone negatif
untuk dataset tanggal 9 sampai 12 Oktober 2026.
"""

import os
import sys
import json
import pandas as pd

sys.path.insert(0, "src")
from config import load_env_file
load_env_file()

from run_negative_summarizer_pipeline import process_file_pipeline


def main():
    f_in = "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-12/all_2026-10-09_sd_2026-10-12.xlsx"
    p_in = "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-12/progress.json"
    f_out = "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-12/all_2026-10-09_sd_2026-10-12_ringkasan.xlsx"

    print("=== MEMPROSES FILTER ULANG & RINGKASAN NEGATIF: 9-12 OKTOBER 2026 ===")
    res = process_file_pipeline(f_in, p_in, f_out)

    print("\n" + "=" * 80)
    print("HASIL PEMROSESAN:")
    print(f"Total artikel awal : {res['total_initial']}")
    print(f"Total artikel lolos: {res['total_filtered']}")
    print(f"Total dibuang ulang: {len(res['discarded'])}")
    for d in res['discarded']:
        print(f"  - {d['Title']} ({d['Media Name']})")

    # Hitung distribusi tone
    tone_dist = {}
    for r in res['records_with_tone']:
        t = r.get("Tone", "Netral")
        tone_dist[t] = tone_dist.get(t, 0) + 1
    print(f"Distribusi Tone baru: {tone_dist}")
    print(f"Total ringkasan negatif dibuat: {len(res['neg_summaries'])}")

    # Simpan ringkasan negatif ke file JSON sementara untuk inspeksi detail laporan
    dump_path = "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-12/ringkasan_negatif_detail.json"
    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(res['neg_summaries'], f, ensure_ascii=False, indent=2, default=str)
    print(f"Detail ringkasan negatif tersimpan di: {dump_path}")


if __name__ == "__main__":
    main()
