"""
scripts/sync_dashboard_data.py
Fase 3: Sinkronisasi hasil scraping baru dari hasil_scrapping/ ke data_export/ dan web/public/.
- Memperbarui articles_all.json, summary.json, runs.json, dan menyalin Excel harian.
- Menyediakan --check-dates untuk memfilter tanggal yang belum punya data (mode skip_existing).
- Menyediakan --self-check untuk verifikasi fungsi tanpa mengubah data produksi.
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.config import get_date_folder, is_published_yesterday, parse_to_wib
from src.export_excel import write_styled_excel

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
    seconds = max(1, seconds)
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


def _clean_cell_str(val) -> str:
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none") else s


def _norm_link(link: str) -> str:
    return (link or "").strip().rstrip("/").lower()


def generate_article_id(date_str: str, link: str, title: str = "") -> str:
    """Menghasilkan ID stabil berbasis hash SHA-256 dari (tanggal, link/title).
    Format: art_<16-char-hex>, deterministik dan tidak bergeser saat urutan data berubah.
    """
    d = (date_str or "")[:10]
    n_link = _norm_link(link)
    if not n_link:
        n_link = (title or "").strip().lower()
    raw = f"{d}::{n_link}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"art_{digest}"


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

        sp1 = _clean_cell_str(row.get("Spokesperson 1"))
        unit = _clean_cell_str(row.get("Unit Eselon")) or "-"
        kw = _clean_cell_str(row.get("Keywords"))
        rev = _clean_cell_str(row.get("Status Review"))
        isu_val = _clean_cell_str(row.get("Isu"))
        alasan_tone_val = _clean_cell_str(row.get("Alasan Tone"))
        sumber_isu_val = _clean_cell_str(
            row.get("Sumber Isu") if "Sumber Isu" in row.index else row.get("sumber_isu")
        )

        rec: dict[str, object] = {
            "id": generate_article_id(d_str, link, title),
            "title": title,
            "link": link,
            "media": media,
            "tone": tone,
            "date": d_str,
            "datetime": dt_iso,
            "time": time_str,
            "date_display": format_date_indo(d_str, full_month=True),
            "spokesperson": sp1,
            "unit": unit,
            "commodity": map_keyword_to_commodity(kw, title),
            "has_review": bool(rev),
            "review_text": rev,
            "isu": isu_val,
            "alasan_tone": alasan_tone_val,
        }
        if sumber_isu_val:
            rec["sumber_isu"] = sumber_isu_val
        records.append(rec)
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

    daily_tones = {}
    recent_days = []
    for d_str in sorted_dates:
        arts = by_date[d_str]
        pos = sum(1 for a in arts if a.get("tone") == "Positif")
        neg = sum(1 for a in arts if a.get("tone") == "Negatif")
        net = len(arts) - pos - neg
        daily_tones[d_str] = {
            "count": len(arts),
            "pos": pos,
            "net": net,
            "neg": neg,
        }
        if len(recent_days) < 14:
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
            "daily_tones": daily_tones,
        },
        "commodities": commodities,
        "spokespersons": spokespersons,
        "recent_articles": articles[:100],
        "recent_days": recent_days,
    }


def _article_composite_key(art: dict) -> tuple[str, str]:
    """Menghasilkan composite key (tanggal, link/title) agar URL yang sama di tanggal berbeda tetap terjaga."""
    d = (art.get("date") or "")[:10]
    link = _norm_link(art.get("link", ""))
    if link:
        return (d, link)
    title = (art.get("title") or "").strip().lower()
    return (d, title)


def merge_articles(new_articles: list[dict], existing_articles: list[dict]) -> list[dict]:
    """Menggabungkan artikel baru ke arsip lama dengan composite key (tanggal, link).
    Menjamin artikel dengan URL sama di hari berbeda dihitung di kedua hari (sesuai Excel harian).
    """
    new_keys = {_article_composite_key(a) for a in new_articles}
    preserved = [
        a for a in existing_articles
        if _article_composite_key(a) not in new_keys
    ]
    merged = list(new_articles) + preserved
    merged.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
    for art in merged:
        if not art.get("id"):
            art["id"] = generate_article_id(art.get("date", ""), art.get("link", ""), art.get("title", ""))
    return merged


def merge_all_data_excel(src_xlsx: Path, dest_xlsx: Path) -> None:
    """Menggabungkan sheet Berita & Ringkasan Negatif ke Media_Monitoring_Agro_Semua_Data.xlsx
    dengan composite key (Tanggal, Link Website) agar data historis multi-hari tidak hilang.
    """
    if not src_xlsx.exists():
        return
    if not dest_xlsx.exists():
        shutil.copy2(src_xlsx, dest_xlsx)
        return

    src_sheets = pd.read_excel(src_xlsx, sheet_name=None)
    dest_sheets = pd.read_excel(dest_xlsx, sheet_name=None)

    merged_sheets: dict[str, pd.DataFrame] = {}
    all_names = list(dict.fromkeys(list(dest_sheets.keys()) + list(src_sheets.keys())))
    for name in all_names:
        df_new = src_sheets.get(name, pd.DataFrame())
        df_old = dest_sheets.get(name, pd.DataFrame())
        if df_new.empty and df_old.empty:
            continue
        combined = pd.concat([df_new, df_old], ignore_index=True)
        if "Link Website" in combined.columns:
            norm_links = combined["Link Website"].fillna("").astype(str).map(_norm_link)
            has_key = norm_links != ""
            if "Tanggal" in combined.columns:
                norm_dates = combined["Tanggal"].fillna("").astype(str).str.slice(0, 10)
                composite_keys = norm_dates + "::" + norm_links
                keep_mask = (~has_key) | (~composite_keys.duplicated(keep="first"))
            else:
                keep_mask = (~has_key) | (~norm_links.duplicated(keep="first"))
            combined = combined[keep_mask].reset_index(drop=True)
        merged_sheets[name] = combined

    if not merged_sheets:
        return
    tmp_xlsx = dest_xlsx.with_suffix(".tmp.xlsx")
    df_berita = merged_sheets.get("Berita", pd.DataFrame())
    df_neg = merged_sheets.get("Ringkasan Negatif", pd.DataFrame())
    write_styled_excel(df_berita, tmp_xlsx, df_neg=df_neg, sort_desc=True)
    shutil.move(str(tmp_xlsx), str(dest_xlsx))


def rebuild_all_data_from_excels(files_dir: Path) -> tuple[list[dict], dict]:
    """Membaca seluruh file Excel harian di files_dir dan menyusun ulang articles_all dan summary.
    Setiap baris Excel harian dijamin menjadi 1 rekaman mandiri dengan ID unik integer.
    """
    daily_files = sorted([
        f for f in files_dir.glob("Media_Monitoring_Agro_*.xlsx")
        if f.name != "Media_Monitoring_Agro_Semua_Data.xlsx" and not f.name.endswith(".tmp.xlsx")
    ])
    all_articles: list[dict] = []
    for f in daily_files:
        d_str = f.name.replace("Media_Monitoring_Agro_", "").replace(".xlsx", "")
        arts = read_excel_articles(f, fallback_date=d_str)
        all_articles.extend(arts)

    all_articles.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
    for art in all_articles:
        if not art.get("id"):
            art["id"] = generate_article_id(art.get("date", ""), art.get("link", ""), art.get("title", ""))

    summary_data = rebuild_summary(all_articles)
    return all_articles, summary_data


def build_run_stats(new_articles: list[dict], folder: Path) -> dict | None:
    if not new_articles:
        return None
    stats: dict = {
        "final": len(new_articles),
        "perlu_review": sum(1 for a in new_articles if a.get("has_review")),
        "tanpa_spokesperson": sum(1 for a in new_articles if not (a.get("spokesperson") or "").strip()),
    }
    prog_json = load_json(folder / "progress.json", {})
    reports = prog_json.get("batch_reports") or []
    if reports:
        mentah = sum(int(r.get("total_initial", 0) or 0) for r in reports)
        dropped_tgl = sum(int(r.get("total_date_dropped", 0) or 0) for r in reports)
        unik_raw = sum(int(r.get("total_final_valid", 0) or 0) for r in reports)
        prog_unf = load_json(folder / "progress_unfiltered.json", {})
        unik = len(prog_unf.get("articles") or []) or unik_raw
        stats.update({
            "mentah": mentah,
            "filter_tgl": max(0, mentah - dropped_tgl),
            "unik": unik,
            "noise_dibuang_pct": round(((mentah - len(new_articles)) / mentah) * 100) if mentah > 0 else 0,
        })
    return stats


def export_split_daily_excel(src_xlsx: Path, ds: str, dest_xlsx: Path) -> bool:
    """Menyaring baris multi-hari berdasarkan Tanggal == ds untuk file Excel harian dengan styling lengkap."""
    sheets = pd.read_excel(src_xlsx, sheet_name=None)
    filtered: dict[str, pd.DataFrame] = {}
    for s_name, df in sheets.items():
        if "Tanggal" in df.columns and not df.empty:
            wib_dates = df["Tanggal"].apply(parse_to_wib)
            tgl_str = pd.to_datetime(wib_dates, errors="coerce").dt.strftime("%Y-%m-%d").fillna(
                df["Tanggal"].astype(str).str.slice(0, 10)
            )
            sub = df[tgl_str == ds].reset_index(drop=True)
            if not sub.empty:
                filtered[s_name] = sub
        elif not df.empty and "Berita" in filtered:
            filtered[s_name] = df
    if "Berita" not in filtered or filtered["Berita"].empty:
        return False
    df_neg = filtered.get("Ringkasan Negatif", pd.DataFrame())
    write_styled_excel(filtered["Berita"], dest_xlsx, df_neg=df_neg, sort_desc=True)
    return True


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
    run_stats: dict | None = None
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
            # Salin file Excel per tanggal (pisahkan per tanggal jika multi-hari)
            curr = d1
            while curr <= d2:
                ds = curr.isoformat()
                dest_name = f"Media_Monitoring_Agro_{ds}.xlsx"
                dest_path = FILES_EXPORT_DIR / dest_name
                copied = True
                if d1 == d2:
                    shutil.copy2(src_xlsx, dest_path)
                else:
                    copied = export_split_daily_excel(src_xlsx, ds, dest_path)
                if copied and WEB_FILES_DIR.exists():
                    shutil.copy2(dest_path, WEB_FILES_DIR / dest_name)
                curr += datetime.timedelta(days=1)

            # Gabungkan ke file Semua_Data tanpa menimpa data historis
            all_data_dest = FILES_EXPORT_DIR / "Media_Monitoring_Agro_Semua_Data.xlsx"
            merge_all_data_excel(src_xlsx, all_data_dest)
            if WEB_FILES_DIR.exists():
                shutil.copy2(all_data_dest, WEB_FILES_DIR / "Media_Monitoring_Agro_Semua_Data.xlsx")

            run_stats = build_run_stats(new_articles, folder)

    # Merge ke articles_all.json jika ada artikel baru
    if new_articles:
        existing_articles = load_json(DATA_EXPORT_DIR / "articles_all.json", [])
        merged = merge_articles(new_articles, existing_articles)

        summary_data = rebuild_summary(merged)
        with open(DATA_EXPORT_DIR / "articles_all.json", "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)
        with open(DATA_EXPORT_DIR / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # Catat ke runs.json
    runs = load_json(DATA_EXPORT_DIR / "runs.json", [])
    run_entry: dict[str, object] = {
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
    if run_stats:
        run_entry["stats"] = run_stats
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
    import tempfile

    assert map_keyword_to_commodity("kelapa sawit, cpo") == "Kelapa Sawit & CPO"
    assert map_keyword_to_commodity("rokok ilegal") == "Hasil Tembakau"
    assert map_keyword_to_commodity("makanan dan minuman") == "Makanan & Minuman"
    assert format_duration(278) == "4m 38s"
    assert format_short_date_indo("2026-11-05") == "5 Nov 2026"
    assert check_unscraped_dates("2026-11-05", "2026-11-05", skip_existing=True) == []
    assert check_unscraped_dates("2026-11-05", "2026-11-05", skip_existing=False) == ["2026-11-05"]

    # Verifikasi merge_articles menjaga query string & tidak menghapus arsip historis duplikat
    existing = [
        {"title": "A", "link": "https://site.id/news?id=1", "date": "2026-11-04", "time": "08:00"},
        {"title": "B", "link": "https://site.id/news?id=2", "date": "2026-11-04", "time": "09:00"},
        {"title": "B-dup", "link": "https://site.id/news?id=2", "date": "2026-11-03", "time": "10:00"},
    ]
    baru = [{"title": "C", "link": "https://site.id/news?id=3", "date": "2026-11-08", "time": "12:00"}]
    merged = merge_articles(baru, existing)
    assert len(merged) == 4, f"Harusnya 4 artikel terjaga, dapat {len(merged)}"

    # Verifikasi URL sama di tanggal berbeda dihitung di kedua tanggal (composite key date + link)
    baru_lintas_hari = [{"title": "B-hari-lain", "link": "https://site.id/news?id=2", "date": "2026-11-05", "time": "11:00"}]
    merged_lintas = merge_articles(baru_lintas_hari, existing)
    assert len(merged_lintas) == 4, f"Harusnya 4 artikel (id=2 di 3 Nov, 4 Nov, dan 5 Nov), dapat {len(merged_lintas)}"
    # Verifikasi ID stabil dan unik
    ids = [a["id"] for a in merged_lintas]
    assert len(ids) == len(set(ids)) == 4, "Setiap artikel harus punya ID unik"
    assert all(isinstance(i, str) and i.startswith("art_") for i in ids), "ID harus berupa string hash art_*"
    assert generate_article_id("2026-11-04", "https://site.id/news?id=1") == generate_article_id("2026-11-04", "https://site.id/news?id=1")

    # Verifikasi URL sama di tanggal yang sama diperbarui (idempotent)
    baru_update_sama = [{"title": "B-re-scrape", "link": "https://site.id/news?id=2", "date": "2026-11-04", "time": "09:30"}]
    merged_update = merge_articles(baru_update_sama, existing)
    assert len(merged_update) == 3, f"Harusnya tetap 3 artikel (11-04 diperbarui, 11-03 terjaga), dapat {len(merged_update)}"
    assert any(a["title"] == "B-re-scrape" for a in merged_update)

    # Verifikasi merge_all_data_excel tidak menimpa data lama & menjaga URL multi-hari jika tanggal berbeda
    with tempfile.TemporaryDirectory() as tmpd:
        p_old = Path(tmpd) / "old.xlsx"
        p_new = Path(tmpd) / "new.xlsx"
        pd.DataFrame([
            {"Tanggal": "2026-11-03", "Title": "Lama 1", "Link Website": "https://a.id/1"},
            {"Tanggal": "2026-11-04", "Title": "Lama 2", "Link Website": "https://a.id/2"},
        ]).to_excel(p_old, sheet_name="Berita", index=False)
        pd.DataFrame([
            {"Tanggal": "2026-11-05", "Title": "Baru 1 (URL sama hari beda)", "Link Website": "https://a.id/2"},
        ]).to_excel(p_new, sheet_name="Berita", index=False)
        merge_all_data_excel(p_new, p_old)
        df_res = pd.read_excel(p_old, sheet_name="Berita")
        assert len(df_res) == 3, f"Harusnya 3 baris Excel (URL https://a.id/2 ada di 4 Nov dan 5 Nov), dapat {len(df_res)}"
        import openpyxl
        wb_chk = openpyxl.load_workbook(p_old)
        ws_chk = wb_chk["Berita"]
        assert ws_chk["A1"].font.bold is True, "Header harus bold"
        assert ws_chk.freeze_panes == "A2", "Freeze panes harus A2"
        assert ws_chk["C2"].hyperlink is not None and ws_chk["C2"].hyperlink.target.startswith("https://"), "Link Website harus berupa hyperlink aktif"
        wb_chk.close()

        with open(Path(tmpd) / "progress.json", "w", encoding="utf-8") as f:
            json.dump({"batch_reports": [{"total_initial": 100, "total_date_dropped": 40, "total_final_valid": 20}]}, f)
        rs = build_run_stats([{"has_review": True, "spokesperson": ""}, {"has_review": False, "spokesperson": "Budi"}], Path(tmpd))
        assert rs and rs["mentah"] == 100 and rs["filter_tgl"] == 60 and rs["unik"] == 20 and rs["final"] == 2 and rs["perlu_review"] == 1 and rs["tanpa_spokesperson"] == 1 and rs["noise_dibuang_pct"] == 98

        # Verifikasi split harian tidak menyatukan tanggal berbeda
        p_multi = Path(tmpd) / "multi.xlsx"
        p_d6 = Path(tmpd) / "d6.xlsx"
        pd.DataFrame([
            {"Tanggal": "2026-11-06 10:00:00", "Title": "Berita 6 Nov"},
            {"Tanggal": "2026-11-07 11:00:00", "Title": "Berita 7 Nov"},
        ]).to_excel(p_multi, sheet_name="Berita", index=False)
        assert export_split_daily_excel(p_multi, "2026-11-06", p_d6)
        assert len(pd.read_excel(p_d6, sheet_name="Berita")) == 1

    # Verifikasi konversi timezone RSS GMT/UTC ke WIB (tidak mundur H-1)
    assert str(parse_to_wib("Sat, 07 Nov 2026 23:02:51 GMT")) == "2026-11-08 06:02:51"
    assert str(parse_to_wib("2026-11-08 08:00:00")) == "2026-11-08 08:00:00"
    assert is_published_yesterday("Sat, 07 Nov 2026 23:02:51 GMT", datetime.date(2026, 11, 8))
    assert not is_published_yesterday("Sat, 07 Nov 2026 23:02:51 GMT", datetime.date(2026, 11, 7))

    print("[Self-Check] OK: Semua fungsi sync_dashboard_data terverifikasi.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sinkronisasi data hasil scraping ke dashboard")
    parser.add_argument("--self-check", action="store_true", help="Jalankan self-check tanpa ubah file")
    parser.add_argument("--rebuild-all", action="store_true", help="Susun ulang data dari seluruh Excel harian")
    parser.add_argument("--output-dir", type=str, default="", help="Direktori output khusus untuk --rebuild-all (misal sandbox)")
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

    if args.rebuild_all:
        target_dir = Path(args.output_dir) if args.output_dir else DATA_EXPORT_DIR
        target_files_dir = target_dir / "files" if (target_dir / "files").exists() else FILES_EXPORT_DIR
        articles, summary = rebuild_all_data_from_excels(target_files_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_dir / "articles_all.json", "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False)
        with open(target_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"[Rebuild] Berhasil menyusun ulang {len(articles)} artikel ke {target_dir}")
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
