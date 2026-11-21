import tempfile
from pathlib import Path
import pandas as pd
import pytest

from scripts.sync_dashboard_data import (
    rebuild_all_data_from_excels,
    merge_articles,
    merge_all_data_excel,
    rebuild_summary,
    generate_article_id,
)


def test_rebuild_from_synthetic_excels_preserves_multiday_urls():
    """Memastikan URL sama di hari berbeda dengan tone berbeda tetap terjaga 1:1 sesuai Excel."""
    with tempfile.TemporaryDirectory() as tmpdir:
        files_dir = Path(tmpdir)

        # File hari ke-1 (2026-11-01): URL A (Positif) dan URL B (Netral)
        df_d1 = pd.DataFrame([
            {
                "Tanggal": "2026-11-01 09:00:00",
                "Title": "Berita A di Hari Pertama",
                "Link Website": "https://portal.id/berita-a",
                "Media Name": "Portal A",
                "Tone": "Positif",
                "Keywords": "sawit",
            },
            {
                "Tanggal": "2026-11-01 10:00:00",
                "Title": "Berita B di Hari Pertama",
                "Link Website": "https://portal.id/berita-b",
                "Media Name": "Portal B",
                "Tone": "Netral",
                "Keywords": "kopi",
            },
        ])
        df_d1.to_excel(files_dir / "Media_Monitoring_Agro_2026-11-01.xlsx", sheet_name="Berita", index=False)

        # File hari ke-2 (2026-11-02): URL A (Negatif - tone berbeda!) dan URL C (Positif)
        df_d2 = pd.DataFrame([
            {
                "Tanggal": "2026-11-02 11:00:00",
                "Title": "Berita A Muncul Lagi di Hari Kedua",
                "Link Website": "https://portal.id/berita-a",
                "Media Name": "Portal A",
                "Tone": "Negatif",
                "Keywords": "sawit",
            },
            {
                "Tanggal": "2026-11-02 12:00:00",
                "Title": "Berita C di Hari Kedua",
                "Link Website": "https://portal.id/berita-c",
                "Media Name": "Portal C",
                "Tone": "Positif",
                "Keywords": "kakao",
            },
        ])
        df_d2.to_excel(files_dir / "Media_Monitoring_Agro_2026-11-02.xlsx", sheet_name="Berita", index=False)

        articles, summary = rebuild_all_data_from_excels(files_dir)

        # 1. Total artikel harus tepat 4 (tidak boleh terhapus)
        assert len(articles) == 4, f"Ekspektasi 4 artikel, dapat {len(articles)}"

        # 2. Periksa ID unik dan tidak duplikat
        ids = [a["id"] for a in articles]
        assert len(ids) == len(set(ids)) == 4

        # 3. Periksa keberadaan kedua rekaman URL A dengan tone aslinya masing-masing
        url_a_recs = [a for a in articles if "berita-a" in a["link"]]
        assert len(url_a_recs) == 2, "URL A harus ada 2 rekaman karena berasal dari 2 hari berbeda"

        rec_d1 = next(a for a in url_a_recs if a["date"] == "2026-11-01")
        rec_d2 = next(a for a in url_a_recs if a["date"] == "2026-11-02")
        assert rec_d1["tone"] == "Positif", f"Ekspektasi tone 1 Nov Positif, dapat {rec_d1['tone']}"
        assert rec_d2["tone"] == "Negatif", f"Ekspektasi tone 2 Nov Negatif, dapat {rec_d2['tone']}"

        # 4. Periksa agregat summary.json
        meta = summary["metadata"]
        assert meta["total_articles"] == 4
        assert meta["calendar_counts"] == {"2026-11-02": 2, "2026-11-01": 2}
        assert meta["daily_tones"]["2026-11-01"] == {"count": 2, "pos": 1, "net": 1, "neg": 0}
        assert meta["daily_tones"]["2026-11-02"] == {"count": 2, "pos": 1, "net": 0, "neg": 1}
        assert meta["tone_summary"] == {"Positif": 2, "Netral": 1, "Negatif": 1}


def test_merge_articles_idempotency_and_cross_day():
    """Memastikan merge_articles mengizinkan URL sama lintas hari tetapi memperbarui jika hari sama."""
    existing = [
        {"id": 1, "title": "Old D1", "link": "https://a.id/1", "date": "2026-11-01", "time": "08:00", "tone": "Positif"},
        {"id": 2, "title": "Old D2", "link": "https://a.id/1", "date": "2026-11-02", "time": "09:00", "tone": "Negatif"},
    ]

    # Kasus A: Tambah tanggal baru (2026-11-03) dengan URL yang sama
    new_d3 = [
        {"id": 0, "title": "New D3", "link": "https://a.id/1", "date": "2026-11-03", "time": "10:00", "tone": "Netral"}
    ]
    merged_a = merge_articles(new_d3, existing)
    assert len(merged_a) == 3, f"Harusnya 3 rekaman terjaga, dapat {len(merged_a)}"
    assert {a["date"] for a in merged_a} == {"2026-11-01", "2026-11-02", "2026-11-03"}

    # Kasus B: Re-scrape tanggal yang sama (2026-11-02) dengan perubahan judul/tone
    re_scrape_d2 = [
        {"id": 0, "title": "Updated D2", "link": "https://a.id/1", "date": "2026-11-02", "time": "09:30", "tone": "Positif"}
    ]
    merged_b = merge_articles(re_scrape_d2, existing)
    assert len(merged_b) == 2, f"Harusnya tetap 2 rekaman, dapat {len(merged_b)}"
    rec_d2 = next(a for a in merged_b if a["date"] == "2026-11-02")
    assert rec_d2["title"] == "Updated D2"
    assert rec_d2["tone"] == "Positif"


def test_merge_all_data_excel_composite_key():
    """Memastikan file Excel kumulatif menjaga URL yang sama jika tanggalnya berbeda."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest_xlsx = Path(tmpdir) / "Media_Monitoring_Agro_Semua_Data.xlsx"
        src_xlsx = Path(tmpdir) / "Media_Monitoring_Agro_2026-11-02.xlsx"

        # File lama memiliki data tanggal 2026-11-01
        df_old = pd.DataFrame([
            {"Tanggal": "2026-11-01", "Title": "Berita 1 Nov", "Link Website": "https://shared.id/x"},
        ])
        df_old.to_excel(dest_xlsx, sheet_name="Berita", index=False)

        # File baru memiliki data tanggal 2026-11-02 dengan URL yang sama
        df_new = pd.DataFrame([
            {"Tanggal": "2026-11-02", "Title": "Berita 2 Nov", "Link Website": "https://shared.id/x"},
        ])
        df_new.to_excel(src_xlsx, sheet_name="Berita", index=False)

        merge_all_data_excel(src_xlsx, dest_xlsx)

        df_res = pd.read_excel(dest_xlsx, sheet_name="Berita")
        assert len(df_res) == 2, f"Harusnya 2 baris (1 Nov dan 2 Nov), dapat {len(df_res)}"
        dates = set(df_res["Tanggal"].astype(str).str.slice(0, 10))
        assert dates == {"2026-11-01", "2026-11-02"}


def test_stable_article_id_deterministic_and_shuffled():
    """Memastikan ID artikel deterministik berbasis hash dan tidak bergeser saat urutan berubah."""
    import random

    articles = [
        {"title": f"Title {i}", "link": f"https://portal.id/news/{i}", "date": "2026-11-10", "time": f"08:{i:02d}"}
        for i in range(10)
    ]
    ids_initial = [generate_article_id(a["date"], a["link"], a["title"]) for a in articles]

    # Acak urutan input
    shuffled = list(articles)
    random.seed(42)
    random.shuffle(shuffled)
    ids_shuffled = [generate_article_id(a["date"], a["link"], a["title"]) for a in shuffled]

    map_initial = {a["link"]: aid for a, aid in zip(articles, ids_initial)}
    map_shuffled = {a["link"]: aid for a, aid in zip(shuffled, ids_shuffled)}
    assert map_initial == map_shuffled

    # Uji merge_articles: data lama tetap memiliki ID yang sama saat data baru ditambahkan
    merged_1 = merge_articles(articles[:5], [])
    ids_before = {a["link"]: a["id"] for a in merged_1}

    new_articles = [
        {"title": "New Date News", "link": "https://portal.id/news/new", "date": "2026-11-11", "time": "09:00"}
    ]
    merged_2 = merge_articles(new_articles, merged_1)
    ids_after = {a["link"]: a["id"] for a in merged_2 if a["link"] in ids_before}
    assert ids_before == ids_after, "ID artikel lama tidak boleh bergeser saat data baru masuk"


def test_rescrape_same_date_with_more_articles():
    """Simulasi kasus 19 Nov: Awalnya 13 artikel, di-scrape ulang menjadi 25 artikel.
    Memastikan artikel pada tanggal tersebut diperbarui menjadi 25 tanpa menduplikasi atau merusak tanggal lain.
    """
    # Tanggal 18 Nov: 10 artikel
    d18 = [
        {"title": f"D18 News {i}", "link": f"https://portal.id/d18/{i}", "date": "2026-11-18", "time": f"08:{i:02d}", "tone": "Positif"}
        for i in range(10)
    ]
    # Tanggal 19 Nov: 13 artikel awal
    d19_initial = [
        {"title": f"D19 News {i}", "link": f"https://portal.id/d19/{i}", "date": "2026-11-19", "time": f"09:{i:02d}", "tone": "Netral"}
        for i in range(13)
    ]

    initial_dataset = merge_articles(d19_initial, d18)
    assert len(initial_dataset) == 23

    # Re-scrape 19 Nov menghasilkan 25 artikel (13 diperbarui + 12 baru)
    d19_rescrape = [
        {"title": f"D19 News {i} (updated)", "link": f"https://portal.id/d19/{i}", "date": "2026-11-19", "time": f"09:{i:02d}", "tone": "Positif"}
        for i in range(13)
    ] + [
        {"title": f"D19 News Brand New {i}", "link": f"https://portal.id/d19/new_{i}", "date": "2026-11-19", "time": f"10:{i:02d}", "tone": "Negatif"}
        for i in range(13, 25)
    ]

    updated_dataset = merge_articles(d19_rescrape, initial_dataset)
    assert len(updated_dataset) == 35, f"Ekspektasi 10 (18 Nov) + 25 (19 Nov) = 35, dapat {len(updated_dataset)}"

    arts_19 = [a for a in updated_dataset if a["date"] == "2026-11-19"]
    assert len(arts_19) == 25
    assert all(a["title"].endswith("(updated)") for a in arts_19 if "/new_" not in a["link"])

    summary = rebuild_summary(updated_dataset)
    assert summary["metadata"]["total_articles"] == 35
    assert summary["metadata"]["calendar_counts"]["2026-11-19"] == 25
    assert summary["metadata"]["calendar_counts"]["2026-11-18"] == 10
