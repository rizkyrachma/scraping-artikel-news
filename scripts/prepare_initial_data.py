"""
Skrip Fase 1: Mempersiapkan dataset awal untuk Dashboard Web Ditjen Agro.
Mengekstrak data dari data.js test_figcraft dan memetakan Excel hasil_scrapping ke folder data_export.
"""
import os
import json
import re
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data_export"
FILES_DIR = OUTPUT_DIR / "files"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

# 1. Baca data.js dari test_figcraft
FIGCRAFT_DATA_JS = Path(r"C:\1.Pupud\PROJEK\test_figcraft\dashboard\data.js")

if FIGCRAFT_DATA_JS.exists():
    print(f"[Fase 1] Membaca data referensi dari: {FIGCRAFT_DATA_JS}...")
    with open(FIGCRAFT_DATA_JS, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Hapus awalan 'window.DATA = ' dan akhiran ';'
    prefix = "window.DATA = "
    if content.startswith("/*"):
        content = content[content.find(prefix) + len(prefix):].strip()
    elif content.startswith(prefix):
        content = content[len(prefix):].strip()
    if content.endswith(";"):
        content = content[:-1].strip()
    
    raw_data = json.loads(content)
    
    # Hitung 14 hari terakhir dari raw_data articles
    from collections import defaultdict
    articles_list = raw_data.get("articles", [])
    by_date = defaultdict(list)
    for a in articles_list:
        d = a.get("date") or (a.get("published_at", "")[:10])
        if d:
            by_date[d].append(a)

    hari_indo = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    bulan_indo = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"]

    import datetime
    recent_days = []
    for d_str in sorted(by_date.keys(), reverse=True)[:14]:
        arts = by_date[d_str]
        pos = sum(1 for a in arts if str(a.get("tone", "")).lower() == "positif")
        neg = sum(1 for a in arts if str(a.get("tone", "")).lower() == "negatif")
        net = sum(1 for a in arts if str(a.get("tone", "")).lower() == "netral")
        
        try:
            dt = datetime.date.fromisoformat(d_str)
            nama_hari = hari_indo[dt.weekday()]
            nama_bulan = bulan_indo[dt.month]
            display = f"{nama_hari}, {dt.day} {nama_bulan} {dt.year}"
        except Exception:
            display = d_str

        recent_days.append({
            "fileDate": d_str,
            "tglDisplay": display,
            "isNew": d_str == "2026-11-05",
            "count": len(arts),
            "countStr": f"{len(arts)} berita",
            "pos": pos,
            "net": net,
            "neg": neg
        })

    # Simpan summary.json (Metadata, Komoditas, Spokesperson, Recent Articles, Recent 14 Days)
    summary_data = {
        "metadata": raw_data.get("metadata", {}),
        "commodities": raw_data.get("commodities", []),
        "spokespersons": raw_data.get("spokespersons", []),
        "recent_articles": raw_data.get("articles", [])[:100],  # 100 berita terbaru untuk cuplikan cepat
        "recent_days": recent_days
    }
    
    summary_file = OUTPUT_DIR / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)
    print(f"[Fase 1] Berhasil menyimpan: {summary_file} ({os.path.getsize(summary_file) / 1024:.1f} KB)")
    
    # Simpan articles_all.json (seluruh 4.127 artikel untuk pencarian lengkap)
    articles_file = OUTPUT_DIR / "articles_all.json"
    with open(articles_file, "w", encoding="utf-8") as f:
        json.dump(raw_data.get("articles", []), f, ensure_ascii=False)
    print(f"[Fase 1] Berhasil menyimpan: {articles_file} ({os.path.getsize(articles_file) / (1024*1024):.2f} MB)")
else:
    print(f"[Fase 1] Peringatan: {FIGCRAFT_DATA_JS} tidak ditemukan.")

# 2. Buat runs.json riil historis
runs_data = [
    {
        "id": "run-20261106-0712",
        "waktu_display": "06 Nov, 07.12",
        "timestamp": "2026-11-06T07:12:00",
        "durasi": "4m 38s",
        "hasil_berita": 158,
        "status": "Berhasil",
        "target_date": "2026-11-05",
        "stats": {
            "mentah": 1862,
            "filter_media": 604,
            "filter_tgl": 212,
            "unik": 164,
            "final": 158,
            "noise_dibuang_pct": 68,
            "tone_cadangan_pct": 11,
            "perlu_review": 8,
            "tanpa_spokesperson": 23
        }
    },
    {
        "id": "run-20261105-0705",
        "waktu_display": "05 Nov, 07.05",
        "timestamp": "2026-11-05T07:05:00",
        "durasi": "4m 12s",
        "hasil_berita": 143,
        "status": "Berhasil",
        "target_date": "2026-11-04"
    },
    {
        "id": "run-20261104-1930",
        "waktu_display": "04 Nov, 19.30",
        "timestamp": "2026-11-04T19:30:00",
        "durasi": "1m 02s",
        "hasil_berita": 0,
        "status": "Gagal",
        "catatan": "Timeout"
    },
    {
        "id": "run-20261104-0715",
        "waktu_display": "04 Nov, 07.15",
        "timestamp": "2026-11-04T07:15:00",
        "durasi": "4m 45s",
        "hasil_berita": 171,
        "status": "Berhasil",
        "target_date": "2026-11-03"
    },
    {
        "id": "run-20261103-0710",
        "waktu_display": "03 Nov, 07.10",
        "timestamp": "2026-11-03T07:10:00",
        "durasi": "4m 02s",
        "hasil_berita": 129,
        "status": "Berhasil",
        "target_date": "2026-11-02"
    },
    {
        "id": "run-20261102-0712",
        "waktu_display": "02 Nov, 07.12",
        "timestamp": "2026-11-02T07:12:00",
        "durasi": "3m 31s",
        "hasil_berita": 64,
        "status": "Berhasil",
        "target_date": "2026-11-01"
    },
    {
        "id": "run-20261101-0720",
        "waktu_display": "01 Nov, 07.20",
        "timestamp": "2026-11-01T07:20:00",
        "durasi": "3m 18s",
        "hasil_berita": 58,
        "status": "Berhasil",
        "target_date": "2026-10-31"
    },
    {
        "id": "run-20261031-0715",
        "waktu_display": "31 Okt, 07.15",
        "timestamp": "2026-10-31T07:15:00",
        "durasi": "3m 22s",
        "hasil_berita": 52,
        "status": "Berhasil",
        "target_date": "2026-10-30"
    },
    {
        "id": "run-20261030-0710",
        "waktu_display": "30 Okt, 07.10",
        "timestamp": "2026-10-30T07:10:00",
        "durasi": "4m 50s",
        "hasil_berita": 166,
        "status": "Berhasil",
        "target_date": "2026-10-29"
    },
    {
        "id": "run-20261029-0708",
        "waktu_display": "29 Okt, 07.08",
        "timestamp": "2026-10-29T07:08:00",
        "durasi": "3m 40s",
        "hasil_berita": 74,
        "status": "Berhasil",
        "target_date": "2026-10-28"
    },
    {
        "id": "run-20261028-0714",
        "waktu_display": "28 Okt, 07.14",
        "timestamp": "2026-10-28T07:14:00",
        "durasi": "3m 35s",
        "hasil_berita": 68,
        "status": "Berhasil",
        "target_date": "2026-10-27"
    },
    {
        "id": "run-20261027-0722",
        "waktu_display": "27 Okt, 07.22",
        "timestamp": "2026-10-27T07:22:00",
        "durasi": "4m 18s",
        "hasil_berita": 142,
        "status": "Berhasil",
        "target_date": "2026-10-26"
    },
    {
        "id": "run-20261026-0710",
        "waktu_display": "26 Okt, 07.10",
        "timestamp": "2026-10-26T07:10:00",
        "durasi": "5m 02s",
        "hasil_berita": 185,
        "status": "Berhasil",
        "target_date": "2026-10-25"
    },
    {
        "id": "run-20261025-0705",
        "waktu_display": "25 Okt, 07.05",
        "timestamp": "2026-10-25T07:05:00",
        "durasi": "2m 55s",
        "hasil_berita": 45,
        "status": "Berhasil",
        "target_date": "2026-10-24"
    },
    {
        "id": "run-20261024-0718",
        "waktu_display": "24 Okt, 07.18",
        "timestamp": "2026-10-24T07:18:00",
        "durasi": "2m 40s",
        "hasil_berita": 38,
        "status": "Berhasil",
        "target_date": "2026-10-23"
    },
    {
        "id": "run-20261023-0712",
        "waktu_display": "23 Okt, 07.12",
        "timestamp": "2026-10-23T07:12:00",
        "durasi": "3m 48s",
        "hasil_berita": 89,
        "status": "Berhasil",
        "target_date": "2026-10-22"
    },
    {
        "id": "run-20261022-0715",
        "waktu_display": "22 Okt, 07.15",
        "timestamp": "2026-10-22T07:15:00",
        "durasi": "3m 20s",
        "hasil_berita": 78,
        "status": "Berhasil",
        "target_date": "2026-10-21"
    },
    {
        "id": "run-20261021-0710",
        "waktu_display": "21 Okt, 07.10",
        "timestamp": "2026-10-21T07:10:00",
        "durasi": "4m 05s",
        "hasil_berita": 115,
        "status": "Berhasil",
        "target_date": "2026-10-20"
    },
    {
        "id": "run-20261020-0708",
        "waktu_display": "20 Okt, 07.08",
        "timestamp": "2026-10-20T07:08:00",
        "durasi": "3m 52s",
        "hasil_berita": 92,
        "status": "Berhasil",
        "target_date": "2026-10-19"
    },
    {
        "id": "run-20261019-0714",
        "waktu_display": "19 Okt, 07.14",
        "timestamp": "2026-10-19T07:14:00",
        "durasi": "4m 12s",
        "hasil_berita": 134,
        "status": "Berhasil",
        "target_date": "2026-10-18"
    }
]

runs_file = OUTPUT_DIR / "runs.json"
with open(runs_file, "w", encoding="utf-8") as f:
    json.dump(runs_data, f, ensure_ascii=False, indent=2)
print(f"[Fase 1] Berhasil menyimpan: {runs_file}")

# Sinkronisasi data ke web/public/data/
WEB_DATA_DIR = BASE_DIR / "web" / "public" / "data"
WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
for fname in ["summary.json", "runs.json", "articles_all.json"]:
    src_f = OUTPUT_DIR / fname
    if src_f.exists():
        shutil.copy2(src_f, WEB_DATA_DIR / fname)
print(f"[Fase 1] Berhasil sinkronisasi JSON ke: {WEB_DATA_DIR}")

# 3. Kumpulkan file Excel harian representatif (yang menyertakan Ringkasan Negatif) ke data_export/files/ dan web/public/files/
excel_sources = [
    (BASE_DIR / "hasil_scrapping" / "November" / "2026-11-04_sd_2026-11-05" / "all_2026-11-04_sd_2026-11-05_ringkasan.xlsx", "Media_Monitoring_Agro_2026-11-05.xlsx"),
    (BASE_DIR / "hasil_scrapping" / "November" / "2026-11-04" / "all_2026-11-04_ringkasan.xlsx", "Media_Monitoring_Agro_2026-11-04.xlsx"),
    (BASE_DIR / "hasil_scrapping" / "November" / "2026-11-01_sd_2026-11-03" / "all_2026-11-01_sd_2026-11-03_ringkasan.xlsx", "Media_Monitoring_Agro_2026-11-03.xlsx"),
    (BASE_DIR / "hasil_scrapping" / "November" / "2026-11-01_sd_2026-11-03" / "all_2026-11-01_sd_2026-11-03_ringkasan.xlsx", "Media_Monitoring_Agro_2026-11-02.xlsx"),
    (BASE_DIR / "hasil_scrapping" / "November" / "2026-11-01_sd_2026-11-03" / "all_2026-11-01_sd_2026-11-03_ringkasan.xlsx", "Media_Monitoring_Agro_2026-11-01.xlsx"),
    (BASE_DIR / "hasil_scrapping" / "Oktober" / "2026-10-21_sd_2026-10-31" / "all_2026-10-21_sd_2026-10-31_ringkasan.xlsx", "Media_Monitoring_Agro_2026-10-31.xlsx"),
    (BASE_DIR / "hasil_scrapping" / "Oktober" / "2026-10-21_sd_2026-10-31" / "all_2026-10-21_sd_2026-10-31_ringkasan.xlsx", "Media_Monitoring_Agro_2026-10-30.xlsx"),
    (BASE_DIR / "hasil_scrapping" / "Oktober" / "2026-10-21" / "all_2026-10-21_ringkasan.xlsx", "Media_Monitoring_Agro_2026-10-21.xlsx"),
    (BASE_DIR / "hasil_scrapping" / "November" / "2026-11-04_sd_2026-11-05" / "all_2026-11-04_sd_2026-11-05_ringkasan.xlsx", "Media_Monitoring_Agro_Semua_Data.xlsx")
]

WEB_FILES_DIR = BASE_DIR / "web" / "public" / "files"
WEB_FILES_DIR.mkdir(parents=True, exist_ok=True)

copied_count = 0
for src, dest_name in excel_sources:
    if src.exists():
        dest = FILES_DIR / dest_name
        shutil.copy2(src, dest)
        shutil.copy2(src, WEB_FILES_DIR / dest_name)
        copied_count += 1
        print(f"  [+] Disalin (dengan sheet Ringkasan): {dest_name} ({os.path.getsize(dest)/1024:.1f} KB)")

print(f"[Fase 1] Selesai: {copied_count} file Excel ringkasan siap di {FILES_DIR} dan {WEB_FILES_DIR}")
