"""
scripts/sync_dashboard_data.py
Fase 3: Sinkronisasi hasil scraping baru dari hasil_scrapping/ ke data_export/ dan web/public/.
- Memperbarui articles_all.json, summary.json, runs.json, dan menyalin Excel harian.
- Menyediakan --check-dates untuk memfilter tanggal yang belum punya data (mode skip_existing).
- Menyediakan --self-check untuk verifikasi fungsi tanpa mengubah data produksi.
"""

import argparse
import datetime
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.config import get_date_folder

DATA_EXPORT_DIR = BASE_DIR / "data_export"
FILES_EXPORT_DIR = DATA_EXPORT_DIR / "files"
WEB_DATA_DIR = BASE_DIR / "web" / "public" / "data"
WEB_FILES_DIR = BASE_DIR / "web" / "public" / "files"

HARI_INDO = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN_PENDEK = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"]
BULAN_PANJANG = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember"
]


def map_keyword_to_commodity(kw_raw: str, title: str = "") -> str:
    """Memetakan string Keywords dari Excel ke kategori komoditas standar dashboard."""
    combined = f"{kw_raw or ''} {title or ''}".lower()
    if any(k in combined for k in ("sawit", "cpo", "minyak sawit", "pome")):
        return "Kelapa Sawit & CPO"
    if any(k in combined for k in ("biodiesel", "bioethanol", "fame", "bioenergi")):
        return "Biodiesel & Bioenergi"
    if any(k in combined for k in ("tembakau", "rokok", "nikotin", "tar", "vape", "cukai")):
        return "Hasil Tembakau"
    if any(k in combined for k in ("tepung", "terigu", "tapioka", "sagu", "pati", "mocaf")):
        return "Tepung, Sagu & Pati"
    if any(k in combined for k in ("kakao", "cokelat")):
        return "Kakao & Cokelat"
    if any(k in combined for k in ("kopi", "teh")):
        return "Kopi & Teh"
    if "kelapa" in combined:
        return "Kelapa & Olahan"
    if any(k in combined for k in ("rumput laut", "alga", "spirulina")):
        return "Rumput Laut"
    if any(k in combined for k in ("mebel", "furniture", "furnitur", "kayu")):
        return "Kayu & Furnitur"
    if any(k in combined for k in ("pulp", "kertas")):
        return "Pulp & Kertas"
    if any(k in combined for k in ("gula", "tebu", "rafinasi")):
        return "Gula & Tebu"
    if "karet" in combined:
        return "Karet & Olahan"
    if "susu" in combined:
        return "Susu & Olahan"
    if "pakan" in combined:
        return "Pakan Ternak"
    if any(k in combined for k in (
        "makanan", "minuman", "mamin", "daging", "mi instan", "ikan kaleng",
        "biskuit", "beralkohol", "berpemanis", "amdk", "galon"
    )):
        return "Makanan & Minuman"
    return "Lainnya"


def format_date_indo(d_str: str, full_month: bool = False) -> str:
    try:
        dt = datetime.date.fromisoformat(d_str[:10])
        hari = HARI_INDO[dt.weekday()]
        bulan = BULAN_PANJANG[dt.month] if full_month else BULAN_PENDEK[dt.month]
        return f"{hari}, {dt.day} {bulan} {dt.year}"
    except Exception:
        return d_str


def format_short_date_indo(d_str: str) -> str:
    try:
        dt = datetime.date.fromisoformat(d_str[:10])
        return f"{dt.day} {BULAN_PENDEK[dt.month]} {dt.year}"
    except Exception:
        return d_str


def format_duration(seconds: int) -> str:
    seconds = max(1, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}m {s:02d}s"


def load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def check_unscraped_dates(start_str: str, end_str: str, skip_existing: bool) -> list[str]:
    """Mengembalikan daftar tanggal YYYY-MM-DD yang perlu di-scrape."""
    d1 = datetime.date.fromisoformat(start_str)
    d2 = datetime.date.fromisoformat(end_str)
    if d2 < d1:
        d1, d2 = d2, d1
    # Batas pengaman maksimal 31 hari sesuai kesepakatan
    if (d2 - d1).days > 30:
        d2 = d1 + datetime.timedelta(days=30)

    summary = load_json(DATA_EXPORT_DIR / "summary.json", {})
    cal_counts = summary.get("metadata", {}).get("calendar_counts", {})

    dates = []
    curr = d1
    while curr <= d2:
        ds = curr.isoformat()
        has_file = (FILES_EXPORT_DIR / f"Media_Monitoring_Agro_{ds}.xlsx").exists()
        has_count = cal_counts.get(ds, 0) > 0
        if not skip_existing or not (has_file or has_count):
            dates.append(ds)
        curr += datetime.timedelta(days=1)
    return dates


def read_excel_articles(excel_path: Path, fallback_date: str) -> list[dict]:
    """Membaca baris artikel dari file Excel hasil main.py ke struktur articles_all.json."""
    if not excel_path.exists():
        return []
    df = pd.read_excel(excel_path)
    if df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        raw_tgl = row.get("Tanggal")
        if pd.isna(raw_tgl):
            d_str = fallback_date
            dt_iso = f"{fallback_date}T08:00:00"
            time_str = "08:00"
        elif isinstance(raw_tgl, (datetime.datetime, pd.Timestamp)):
            d_str = raw_tgl.strftime("%Y-%m-%d")
            dt_iso = raw_tgl.strftime("%Y-%m-%dT%H:%M:%S")
            time_str = raw_tgl.strftime("%H:%M")
        else:
            s_val = str(raw_tgl).strip()
            d_str = s_val[:10] if len(s_val) >= 10 else fallback_date
            dt_iso = f"{d_str}T08:00:00"
            time_str = "08:00"

        title = str(row.get("Title") or "").strip()
        link = str(row.get("Link Website") or "").strip()
        if not title or not link:
            continue

        media = str(row.get("Media Name") or "Media").strip()
        tone = str(row.get("Tone") or "Netral").strip().capitalize()
        if tone not in ("Positif", "Netral", "Negatif"):
            tone = "Netral"

        sp1 = "" if pd.isna(row.get("Spokesperson 1")) else str(row.get("Spokesperson 1")).strip()
        unit = "-" if pd.isna(row.get("Unit Eselon")) else str(row.get("Unit Eselon")).strip()
        kw = "" if pd.isna(row.get("Keywords")) else str(row.get("Keywords")).strip()
        rev = "" if pd.isna(row.get("Status Review")) else str(row.get("Status Review")).strip()

        records.append({
            "id": 0,
            "title": title,
            "link": link,
            "media": media,
            "tone": tone,
            "date": d_str,
            "datetime": dt_iso,
            "time": time_str,
            "date_display": format_date_indo(d_str, full_month=True),
            "spokesperson": sp1,
            "unit": unit or "-",
            "commodity": map_keyword_to_commodity(kw, title),
            "has_review": bool(rev),
            "review_text": rev,
        })
    return records


def rebuild_summary(articles: list[dict]) -> dict:
    """Menghitung ulang summary.json dari seluruh daftar artikel."""
    by_date = defaultdict(list)
    tone_summary = {"Positif": 0, "Netral": 0, "Negatif": 0}
    comm_counts = defaultdict(int)
    sp_counts = defaultdict(int)

    for a in articles:
        d = (a.get("date") or "")[:10]
        if d:
            by_date[d].append(a)
        t = a.get("tone", "Netral")
        tone_summary[t] = tone_summary.get(t, 0) + 1
        c = a.get("commodity") or "Lainnya"
        comm_counts[c] += 1
        sp = (a.get("spokesperson") or "").strip()
        if sp and sp != "-":
            for part in [p.strip() for p in sp.split(",") if p.strip()]:
                sp_counts[part] += 1

    sorted_dates = sorted(by_date.keys(), reverse=True)
    latest_date = sorted_dates[0] if sorted_dates else datetime.date.today().isoformat()
    earliest_date = sorted_dates[-1] if sorted_dates else latest_date

    calendar_counts = {d: len(by_date[d]) for d in sorted_dates}

    recent_days = []
    for d_str in sorted_dates[:14]:
        arts = by_date[d_str]
        pos = sum(1 for a in arts if a.get("tone") == "Positif")
        neg = sum(1 for a in arts if a.get("tone") == "Negatif")
        net = len(arts) - pos - neg
        recent_days.append({
            "fileDate": d_str,
            "tglDisplay": format_date_indo(d_str, full_month=False),
            "isNew": d_str == latest_date,
            "count": len(arts),
            "countStr": f"{len(arts)} berita",
            "pos": pos,
            "net": net,
            "neg": neg,
        })

    commodities = [
        {"name": name, "count": cnt}
        for name, cnt in sorted(comm_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    spokespersons = [
        {"name": name, "count": cnt}
        for name, cnt in sorted(sp_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "metadata": {
            "last_updated": latest_date,
            "last_updated_display": format_date_indo(latest_date, full_month=True),
            "earliest_date": earliest_date,
            "total_articles": len(articles),
            "tone_summary": tone_summary,
            "calendar_counts": calendar_counts,
        },
        "commodities": commodities,
        "spokespersons": spokespersons,
        "recent_articles": articles[:100],
        "recent_days": recent_days,
    }


def sync_after_run(
    start_date: str,
    end_date: str,
    status: str,
    duration_sec: int,
    trigger: str,
    note: str = "",
    log_url: str = "",
) -> int:
    """Menyinkronkan hasil run ke data_export/ dan web/public/."""
    DATA_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    FILES_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    wib = datetime.timezone(datetime.timedelta(hours=7))
    now_wib = datetime.datetime.now(wib)
    waktu_display = f"{now_wib.day:02d} {BULAN_PENDEK[now_wib.month]}, {now_wib.strftime('%H.%M')}"
    run_id = f"run-{now_wib.strftime('%Y%m%d-%H%M%S')}"

    if start_date == end_date:
        rentang_str = format_short_date_indo(start_date)
    else:
        rentang_str = f"{format_short_date_indo(start_date)} – {format_short_date_indo(end_date)}"

    new_articles: list[dict] = []
    if status == "Berhasil":
        d1 = datetime.date.fromisoformat(start_date)
        d2 = datetime.date.fromisoformat(end_date)
        folder = Path(get_date_folder((d1, d2)))
        date_str = start_date if start_date == end_date else f"{start_date}_sd_{end_date}"
        ringkasan_xlsx = folder / f"all_{date_str}_ringkasan.xlsx"
        plain_xlsx = folder / f"all_{date_str}.xlsx"
        src_xlsx = ringkasan_xlsx if ringkasan_xlsx.exists() else plain_xlsx

        if src_xlsx.exists():
            new_articles = read_excel_articles(src_xlsx, fallback_date=end_date)
            # Salin file Excel per tanggal
            curr = d1
            while curr <= d2:
                ds = curr.isoformat()
                dest_name = f"Media_Monitoring_Agro_{ds}.xlsx"
                shutil.copy2(src_xlsx, FILES_EXPORT_DIR / dest_name)
                if WEB_FILES_DIR.exists():
                    shutil.copy2(src_xlsx, WEB_FILES_DIR / dest_name)
                curr += datetime.timedelta(days=1)

            # Perbarui juga file gabungan terbaru
            shutil.copy2(src_xlsx, FILES_EXPORT_DIR / "Media_Monitoring_Agro_Semua_Data.xlsx")
            if WEB_FILES_DIR.exists():
                shutil.copy2(src_xlsx, WEB_FILES_DIR / "Media_Monitoring_Agro_Semua_Data.xlsx")

    # Merge ke articles_all.json jika ada artikel baru
    if new_articles:
        existing_articles = load_json(DATA_EXPORT_DIR / "articles_all.json", [])
        seen_links = set()
        merged = []
        # Artikel baru ditaruh di depan, lalu diurutkan terbaru
        for art in new_articles + existing_articles:
            clean_link = (art.get("link") or "").split("?")[0].rstrip("/").lower()
            if clean_link and clean_link not in seen_links:
                seen_links.add(clean_link)
                merged.append(art)

        merged.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
        for idx, art in enumerate(merged, start=1):
            art["id"] = idx

        summary_data = rebuild_summary(merged)
        with open(DATA_EXPORT_DIR / "articles_all.json", "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)
        with open(DATA_EXPORT_DIR / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # Catat ke runs.json
    runs = load_json(DATA_EXPORT_DIR / "runs.json", [])
    run_entry = {
        "id": run_id,
        "waktu_display": waktu_display,
        "timestamp": now_wib.strftime("%Y-%m-%dT%H:%M:%S"),
        "durasi": format_duration(duration_sec),
        "hasil_berita": len(new_articles),
        "status": status,
        "target_date": end_date if start_date == end_date else f"{start_date}_sd_{end_date}",
        "pemicu": trigger,
        "rentang_data": rentang_str if status == "Berhasil" else "-",
    }
    if note:
        run_entry["catatan"] = note
    if log_url:
        run_entry["log_url"] = log_url

    runs = [run_entry] + runs[:29]  # Simpan maksimal 30 run terakhir
    with open(DATA_EXPORT_DIR / "runs.json", "w", encoding="utf-8") as f:
        json.dump(runs, f, ensure_ascii=False, indent=2)

    # Sinkronkan ke web/public/data jika ada
    if WEB_DATA_DIR.exists():
        for fname in ("summary.json", "runs.json", "articles_all.json"):
            src_f = DATA_EXPORT_DIR / fname
            if src_f.exists():
                shutil.copy2(src_f, WEB_DATA_DIR / fname)

    print(f"[Sync] Status={status}, Artikel baru={len(new_articles)}, Durasi={run_entry['durasi']}")
    return len(new_articles)


def run_self_check():
    """Self-check non-destruktif untuk memastikan seluruh fungsi pemetaan dan kalkulasi valid."""
    assert map_keyword_to_commodity("kelapa sawit, cpo") == "Kelapa Sawit & CPO"
    assert map_keyword_to_commodity("rokok ilegal") == "Hasil Tembakau"
    assert map_keyword_to_commodity("makanan dan minuman") == "Makanan & Minuman"
    assert format_duration(278) == "4m 38s"
    assert format_short_date_indo("2026-11-05") == "5 Nov 2026"
    # Tanggal 2026-11-05 sudah ada di summary.json -> harus dilewati jika skip_existing=True
    assert check_unscraped_dates("2026-11-05", "2026-11-05", skip_existing=True) == []
    assert check_unscraped_dates("2026-11-05", "2026-11-05", skip_existing=False) == ["2026-11-05"]
    print("[Self-Check] OK: Semua fungsi sync_dashboard_data terverifikasi.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sinkronisasi data hasil scraping ke dashboard")
    parser.add_argument("--self-check", action="store_true", help="Jalankan self-check tanpa ubah file")
    parser.add_argument("--check-dates", action="store_true", help="Cetak rentang tanggal yang perlu di-scrape")
    parser.add_argument("--start-date", type=str, default="", help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default="", help="YYYY-MM-DD")
    parser.add_argument("--skip-existing", type=str, default="true", help="true/false")
    parser.add_argument("--status", type=str, default="Berhasil", choices=["Berhasil", "Gagal"])
    parser.add_argument("--duration", type=int, default=60, help="Durasi dalam detik")
    parser.add_argument("--trigger", type=str, default="Terjadwal", choices=["Terjadwal", "Manual"])
    parser.add_argument("--note", type=str, default="", help="Catatan jika gagal")
    parser.add_argument("--log-url", type=str, default="", help="URL log GitHub Actions")

    args = parser.parse_args()

    if args.self_check:
        run_self_check()
        sys.exit(0)

    wib = datetime.timezone(datetime.timedelta(hours=7))
    yesterday_wib = (datetime.datetime.now(wib).date() - datetime.timedelta(days=1)).isoformat()
    s_date = args.start_date.strip() or yesterday_wib
    e_date = args.end_date.strip() or s_date
    skip_flag = args.skip_existing.strip().lower() in ("true", "1", "yes", "lewati")

    if args.check_dates:
        needed = check_unscraped_dates(s_date, e_date, skip_existing=skip_flag)
        if not needed:
            print("SKIP")
        else:
            print(f"{needed[0]}:{needed[-1]}")
        sys.exit(0)

    sync_after_run(
        start_date=s_date,
        end_date=e_date,
        status=args.status,
        duration_sec=args.duration,
        trigger=args.trigger,
        note=args.note,
        log_url=args.log_url,
    )
