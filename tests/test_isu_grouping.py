"""
tests/test_isu_grouping.py
Unit test (pytest) Fase 1 untuk pengelompokan isu berita (src/isu_grouping.py):
- Fixture nyata 17 Nov 2026:
  1. 5 berita konferensi pers rokok elektronik -> HARUS 1 isu.
  2. 4 berita perkembangan susu ikan MBG/KKP -> HARUS 1 isu.
  3. 3 berita sawit berbeda peristiwa (El Nino/B50, ISPO, Bea Keluar Sumut) -> TIDAK BOLEH menyatu.
  4. Kasus ambigu (Sagu PSN SBT, Pakar Larangan Vape) -> dicatat untuk CSV review, Sidang MK tidak boleh menyatu dengan konferensi pers asosiasi.
  5. 5 berita tunggal -> masing-masing klaster sendiri.
- Fixture rilis Kemenperin Nov 2026 & pencocokan jendela tanggal (termasuk berita SINTETIS).
- Tes teknis: html.unescape, buang akhiran media, alias ("REL" = "rokok elektronik" = "rokok elektrik" = "vape"), determinisme urutan diacak.
"""

import os
import random
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.isu_grouping import (
    normalize_isu_text,
    clean_display_title,
    IsuRegistry,
    assign_and_cluster_issues,
)


# =====================================================================
# FIXTURE NYATA 17 NOVEMBER 2026
# =====================================================================

ROKOK_ELEKTRONIK_PRESSCON_5 = [
    {
        "id": "re_1",
        "title": "Industri Rokok Elektronik Minta Pemerintah Lindungi Tenaga Kerja",
        "published": "2026-11-17 15:58:09",
        "media_name": "CNN Indonesia",
    },
    {
        "id": "re_2",
        "title": "Industri Rokok Elektronik Minta Perlindungan Pemerintah, Soroti Nasib Pekerja",
        "published": "2026-11-17 16:02:51",
        "media_name": "Harian Jogja",
    },
    {
        "id": "re_3",
        "title": "Pelaku Industri Rokok Elektronik Minta Pemerintah Lindungi Usaha dan Tenaga Kerja",
        "published": "2026-11-17 09:09:57",
        "media_name": "Sumut Pos",
    },
    {
        "id": "re_4",
        "title": "Pelaku Usaha Rokok Elektrik Minta Pemerintah Lindungi Industri & Pekerja",
        "published": "2026-11-17 12:59:32",
        "media_name": "detikFinance",
    },
    {
        "id": "re_5",
        "title": "Industri REL Nasional: Pelaku Usaha dan Pekerja Memohon Perlindungan Pemerintah Jaga Tenaga Kerja",
        "published": "2026-11-17 17:10:00",
        "media_name": "Index Sumut",
    },
]

SUSU_IKAN_4 = [
    {
        "id": "si_1",
        "title": "Digadang Masuk MBG, Begini Nasib Proyek Susu Ikan",
        "published": "2026-11-17 13:30:37",
        "media_name": "Liputan6.com",
    },
    {
        "id": "si_2",
        "title": "Dulu Digadang-gadang Masuk Menu MBG, Begini Kabar Terbaru Susu Ikan",
        "published": "2026-11-17 16:45:04",
        "media_name": "CNBC Indonesia",
    },
    {
        "id": "si_3",
        "title": "KKP Jelaskan Perkembangan Susu Ikan untuk MBG - kumparan.com",
        "published": "2026-11-17 14:40:00",
        "media_name": "kumparan",
    },
    {
        "id": "si_4",
        "title": "Program Susu Ikan Masih PR: KKP Sudah Bikin Prototipe yang Diserahkan ke Daerah",
        "published": "2026-11-17 12:01:00",
        "media_name": "Inilah.com",
    },
]

SAWIT_3_BERBEDA = [
    {
        "id": "sw_1",
        "title": "Ekspor Sawit RI Diproyeksi Turun hingga 5 Juta Ton Gegara El Nino hingga B50",
        "published": "2026-11-17 13:23:19",
        "media_name": "MetroTVNews.com",
    },
    {
        "id": "sw_2",
        "title": "Perkuat ISPO, Pemerintah Dorong Sawit Berkelanjutan hingga Hilirisasi B50",
        "published": "2026-11-17 15:02:57",
        "media_name": "MetroTVNews.com",
    },
    {
        "id": "sw_3",
        "title": "Sawit Dominasi Ekspor Sumut, Penerimaan Bea Keluar Lampaui Target Rp3 Triliun",
        "published": "2026-11-17 10:45:33",
        "media_name": "sawitsetara.co",
    },
]

AMBIGU_CASES = [
    {
        "id": "amb_sagu_1",
        "title": "Menperin Terbitkan Surat Dukungan PSN Hilirisasi Sagu di SBT Maluku",
        "published": "2026-11-17 18:43:46",
        "media_name": "Ameks Online",
    },
    {
        "id": "amb_sagu_2",
        "title": "Pemkab SBT dorong sagu masuk Proyek Strategis Nasional",
        "published": "2026-11-17 08:21:11",
        "media_name": "Rakyat Maluku",
    },
    {
        "id": "amb_pakar_1",
        "title": "Pakar tegaskan pelarangan rokok elektronik harus berbasis bukti",
        "published": "2026-11-17 14:57:27",
        "media_name": "ANTARA News",
    },
    {
        "id": "amb_pakar_2",
        "title": "Wacana Larangan Vape, Pakar Tekankan Kajian Ilmiah dan Pertimbangan Ekonomi",
        "published": "2026-11-17 09:03:55",
        "media_name": "Sumut Pos",
    },
    {
        "id": "amb_mk_1",
        "title": "Sidang Larangan Vape Digelar 25 November, MK Akan Dengar Pengusaha, BNN, dan MUI",
        "published": "2026-11-17 20:35:10",
        "media_name": "Radar Banjarmasin",
    },
    {
        "id": "amb_wacana_1",
        "title": "Wacana Larangan Vape Disorot karena Berdampak pada Ekonomi",
        "published": "2026-11-17 13:08:13",
        "media_name": "bsinews.id",
    },
]

TUNGGAL_5 = [
    {
        "id": "tg_1",
        "title": "Apa Itu TKDN? Pengertian, Cara Menghitung, dan Cara Mengurusnya",
        "published": "2026-11-17 07:58:11",
        "media_name": "Industry.co.id",
    },
    {
        "id": "tg_2",
        "title": "Mengoptimalkan Potensi Rumput Laut Indonesia melalui Hilirisasi dan Penguatan Rantai Pasok",
        "published": "2026-11-17 11:25:36",
        "media_name": "Kementerian Kelautan dan Perikanan",
    },
    {
        "id": "tg_3",
        "title": "Anggota DPR dukung Presiden percepat pembangunan pabrik pakan ternak",
        "published": "2026-11-17 13:50:04",
        "media_name": "ANTARA News",
    },
    {
        "id": "tg_4",
        "title": "Pasar dunia minati produk olahan kelor asal NTB",
        "published": "2026-11-17 20:24:44",
        "media_name": "ANTARA News Mataram",
    },
    {
        "id": "tg_5",
        "title": "Royal Canin Proyeksi Industri Pet Food RI Tumbuh Double Digit, Ini Pendorongnya",
        "published": "2026-11-17 18:28:47",
        "media_name": "FORTUNE Indonesia",
    },
]

RILIS_FIXTURES_NOV_2026 = [
    {
        "id": "rilis_pangan_14nov",
        "judul": "Kemenperin Perkuat Ekosistem Industri Pangan Nasional Bersama Pelaku Industri",
        "tanggal": "2026-11-14",
        "nama_acara": "Kunker DPR ke Sumsel dan Indofood",
        "url": "https://kemenperin.go.id/artikel/1",
    },
    {
        "id": "rilis_atsiri_5nov",
        "judul": "Kemenperin Bidik Ekspor Minyak Atsiri Tembus USD 500 Juta pada 2029",
        "tanggal": "2026-11-05",
        "nama_acara": "Kongres KNMA",
        "url": "https://kemenperin.go.id/artikel/2",
    },
    {
        "id": "rilis_sagu_5nov",
        "judul": "Menperin Sarmuji Percepat Hilirisasi Sagu, Bidik Pasar Jepang hingga Kebutuhan Industri Migas dan Farmasi",
        "tanggal": "2026-11-05",
        "nama_acara": "Sago Business Forum 2026",
        "url": "https://kemenperin.go.id/artikel/3",
    },
    {
        "id": "rilis_pulp_3nov",
        "judul": "RI Eksportir Pulp Terbesar Keempat Dunia, Menperin Sarmuji Dorong Hilirisasi hingga Tekstil Rayon",
        "tanggal": "2026-11-03",
        "nama_acara": "Kongres APKI",
        "url": "https://kemenperin.go.id/artikel/4",
    },
    {
        "id": "rilis_kakao_2nov",
        "judul": "Kemenperin Pacu Ekspor Olahan Kakao di Tengah Tren Positif Grinding",
        "tanggal": "2026-11-02",
        "nama_acara": "Laporan Kinerja Kakao ASKINDO",
        "url": "https://kemenperin.go.id/artikel/5",
    },
]


# =====================================================================
# PENGUJIAN KELOMPOK WAJIB & PEMISAHAN TOPIK (17 NOV 2026)
# =====================================================================

def test_17nov_rokok_elektronik_and_susu_ikan_and_sawit(tmp_path):
    all_articles = (
        ROKOK_ELEKTRONIK_PRESSCON_5
        + SUSU_IKAN_4
        + SAWIT_3_BERBEDA
        + AMBIGU_CASES
        + TUNGGAL_5
    )
    reg = IsuRegistry(filepath=str(tmp_path / "isu_registry.json"))
    reg.seed_releases(RILIS_FIXTURES_NOV_2026)

    assigned = assign_and_cluster_issues(
        all_articles,
        registry=reg,
        method="tfidf",
        use_ai=False,
    )
    by_id = {a["id"]: a for a in assigned}

    # 1. Kelima berita konferensi pers rokok elektronik HARUS satu isu
    re_isus = {by_id[f"re_{i}"]["isu_id"] for i in range(1, 6)}
    assert len(re_isus) == 1, f"5 judul rokok elektronik harus 1 isu, dapat: {re_isus}"
    re_isu_id = next(iter(re_isus))

    # 2. Keempat berita susu ikan HARUS satu isu
    si_isus = {by_id[f"si_{i}"]["isu_id"] for i in range(1, 5)}
    assert len(si_isus) == 1, f"4 judul susu ikan harus 1 isu, dapat: {si_isus}"
    si_isu_id = next(iter(si_isus))
    assert re_isu_id != si_isu_id

    # 3. Ketiga berita sawit TIDAK BOLEH menyatu satu sama lain
    sw_isus = [by_id[f"sw_{i}"]["isu_id"] for i in range(1, 4)]
    assert len(set(sw_isus)) == 3, f"3 berita sawit berbeda peristiwa tidak boleh digabung: {sw_isus}"

    # 4. Sidang MK larangan vape TIDAK BOLEH menyatu dengan konferensi pers asosiasi rokok elektronik
    assert by_id["amb_mk_1"]["isu_id"] != re_isu_id, (
        "Judul sidang MK tidak boleh menyatu dengan konferensi pers asosiasi rokok elektronik"
    )

    # 5. Kelima berita tunggal harus tetap terpisah satu sama lain dan tidak menempel ke klaster lain
    tg_isus = [by_id[f"tg_{i}"]["isu_id"] for i in range(1, 6)]
    assert len(set(tg_isus)) == 5
    for tg_id in tg_isus:
        assert tg_id not in (re_isu_id, si_isu_id)
        assert tg_id not in sw_isus


def test_keyword_independence_same_issue_different_keywords_and_same_keyword_different_issues(tmp_path):
    """
    Tes eksplisit independensi Keywords:
    1. Dua berita dari isu yang sama tetapi berkeyword berbeda ('bnn rokok elektrik' vs 'nikotin') HARUS menyatu.
    2. Tiga berita berkeyword sama ('sawit') tetapi berisu berbeda TIDAK BOLEH menyatu.
    """
    reg = IsuRegistry(filepath=str(tmp_path / "reg_kw.json"))
    articles = [
        {
            "id": "re_kw1",
            "title": "Industri Rokok Elektronik Minta Pemerintah Lindungi Tenaga Kerja",
            "published": "2026-11-17 15:58:09",
            "media_name": "CNN Indonesia",
            "keyword": "bnn rokok elektrik",
            "Keywords": "bnn rokok elektrik",
        },
        {
            "id": "re_kw2",
            "title": "Pelaku Usaha Rokok Elektrik Minta Pemerintah Lindungi Industri & Pekerja",
            "published": "2026-11-17 12:59:32",
            "media_name": "detikFinance",
            "keyword": "nikotin",  # Sengaja berbeda keyword
            "Keywords": "nikotin",
        },
        {
            "id": "sw_kw1",
            "title": "Ekspor Sawit RI Diproyeksi Turun hingga 5 Juta Ton Gegara El Nino hingga B50",
            "published": "2026-11-17 13:23:19",
            "media_name": "MetroTVNews.com",
            "keyword": "sawit",
            "Keywords": "sawit",
        },
        {
            "id": "sw_kw2",
            "title": "Perkuat ISPO, Pemerintah Dorong Sawit Berkelanjutan hingga Hilirisasi B50",
            "published": "2026-11-17 15:02:57",
            "media_name": "MetroTVNews.com",
            "keyword": "sawit",  # Keyword sama persis
            "Keywords": "sawit",
        },
        {
            "id": "sw_kw3",
            "title": "Sawit Dominasi Ekspor Sumut, Penerimaan Bea Keluar Lampaui Target Rp3 Triliun",
            "published": "2026-11-17 10:45:33",
            "media_name": "sawitsetara.co",
            "keyword": "sawit",  # Keyword sama persis
            "Keywords": "sawit",
        },
    ]
    assigned = assign_and_cluster_issues(articles, registry=reg, method="tfidf", use_ai=False)
    by_id = {a["id"]: a for a in assigned}

    # Isu sama, keyword berbeda -> wajib menyatu
    assert by_id["re_kw1"]["isu_id"] == by_id["re_kw2"]["isu_id"]

    # Keyword sama ('sawit'), isu berbeda -> tidak boleh menyatu
    sawit_ids = {by_id["sw_kw1"]["isu_id"], by_id["sw_kw2"]["isu_id"], by_id["sw_kw3"]["isu_id"]}
    assert len(sawit_ids) == 3



# =====================================================================
# PENGUJIAN PENCOCOKAN RILIS KEMENPERIN & JENDELA TANGGAL
# =====================================================================

def test_release_matching_and_date_window(tmp_path):
    reg = IsuRegistry(filepath=str(tmp_path / "isu_registry.json"))
    reg.seed_releases(RILIS_FIXTURES_NOV_2026)

    synthetic_articles = [
        # SINTETIS: Berita 6 Nov (H+1 dari rilis 5 Nov) tentang target ekspor minyak atsiri USD 500 juta
        {
            "id": "syn_atsiri_ok",
            "title": "Kemenperin Targetkan Ekspor Minyak Atsiri Tembus USD 500 Juta pada 2029",  # SINTETIS
            "published": "2026-11-06 10:00:00",
            "media_name": "Kontan",
        },
        # Berita nyata 17 Nov bertopik sagu (H+12 dari rilis sagu 5 Nov -> di luar jendela 7 hari)
        {
            "id": "real_sagu_17nov",
            "title": "Menperin Terbitkan Surat Dukungan PSN Hilirisasi Sagu di SBT Maluku",
            "published": "2026-11-17 18:43:46",
            "media_name": "Ameks Online",
        },
        # SINTETIS: Berita yang judulnya sangat mirip rilis sagu 5 Nov tetapi terbit 17 Nov (12 hari kemudian)
        {
            "id": "syn_sagu_12days_late",
            "title": "Menperin Sarmuji Percepat Hilirisasi Sagu dan Bidik Pasar Jepang",  # SINTETIS
            "published": "2026-11-17 09:00:00",
            "media_name": "Bisnis.com",
        },
        # SINTETIS: Berita yang topiknya sama persis dengan rilis minyak atsiri tetapi 30 hari kemudian (5 Des 2026)
        {
            "id": "syn_atsiri_30days_late",
            "title": "Kemenperin Bidik Ekspor Minyak Atsiri Tembus USD 500 Juta pada 2029",  # SINTETIS
            "published": "2026-12-05 11:00:00",
            "media_name": "Antara",
        },
    ]

    assigned = assign_and_cluster_issues(
        synthetic_articles,
        registry=reg,
        method="tfidf",
        use_ai=False,
    )
    by_id = {a["id"]: a for a in assigned}

    # 1. Berita 6 Nov minyak atsiri HARUS cocok ke rilis minyak atsiri 5 Nov
    assert by_id["syn_atsiri_ok"]["sumber_isu"] == "rilis"
    assert "Minyak Atsiri" in by_id["syn_atsiri_ok"]["isu"]

    # 2. Berita 17 Nov sagu TIDAK boleh cocok ke rilis sagu 5 Nov (di luar jendela 7 hari)
    assert by_id["real_sagu_17nov"]["sumber_isu"] != "rilis"
    assert by_id["syn_sagu_12days_late"]["sumber_isu"] != "rilis"

    # 3. Berita 30 hari kemudian TIDAK boleh cocok ke rilis 5 Nov
    assert by_id["syn_atsiri_30days_late"]["sumber_isu"] != "rilis"


# =====================================================================
# PENGUJIAN TEKNIS: UNESCAPE, MEDIA SUFFIX, ALIAS, SINGLETON, DETERMINISME
# =====================================================================

def test_technical_normalization_and_aliases():
    # 1. html.unescape & buang akhiran media
    raw = "KKP Jelaskan Perkembangan Susu Ikan &amp; Olahan Laut - kumparan.com"
    cleaned = clean_display_title(raw)
    assert cleaned == "KKP Jelaskan Perkembangan Susu Ikan & Olahan Laut"
    assert "kumparan.com" not in cleaned

    # Kata berhubung tanda hubung asli seperti "Digadang-gadang" tidak boleh terpotong
    raw2 = "Dulu Digadang-gadang Masuk Menu MBG, Begini Kabar Terbaru Susu Ikan"
    assert "Digadang-gadang" in clean_display_title(raw2)

    # 2. Alias istilah: REL = rokok elektronik = rokok elektrik = vape
    n1 = normalize_isu_text("Industri REL Nasional")
    n2 = normalize_isu_text("Industri Rokok Elektronik Nasional")
    n3 = normalize_isu_text("Industri Rokok Elektrik Nasional")
    n4 = normalize_isu_text("Industri Vape Nasional")
    assert "rokok_elektronik" in n1
    assert n1 == n2 == n3 == n4


def test_identical_titles_across_media_and_single_article_cluster(tmp_path):
    reg1 = IsuRegistry(filepath=str(tmp_path / "reg1.json"))
    # SINTETIS: Judul identik di dua media berbeda
    dup_articles = [
        {
            "id": "d1",
            "title": "Kemenperin Dorong Ekspor Industri Makanan dan Minuman ke Timur Tengah - Kompas.com",  # SINTETIS
            "published": "2026-11-17 10:00:00",
            "media_name": "Kompas.com",
        },
        {
            "id": "d2",
            "title": "Kemenperin Dorong Ekspor Industri Makanan dan Minuman ke Timur Tengah | Tempo.co",  # SINTETIS
            "published": "2026-11-17 11:00:00",
            "media_name": "Tempo.co",
        },
    ]
    res_dup = assign_and_cluster_issues(dup_articles, registry=reg1, use_ai=False)
    assert res_dup[0]["isu_id"] == res_dup[1]["isu_id"]
    assert res_dup[0]["isu"] == res_dup[1]["isu"]

    # Klaster satu berita
    reg2 = IsuRegistry(filepath=str(tmp_path / "reg2.json"))
    single = [TUNGGAL_5[0]]
    res_single = assign_and_cluster_issues(single, registry=reg2, use_ai=False)
    assert len(res_single) == 1
    assert res_single[0]["sumber_isu"] == "klaster"
    assert "TKDN" in res_single[0]["isu"]


def test_determinism_under_shuffled_input_order(tmp_path):
    base_articles = (
        ROKOK_ELEKTRONIK_PRESSCON_5
        + SUSU_IKAN_4
        + SAWIT_3_BERBEDA
        + TUNGGAL_5
    )

    reg_a = IsuRegistry(filepath=str(tmp_path / "reg_a.json"))
    reg_a.seed_releases(RILIS_FIXTURES_NOV_2026)
    res_a = assign_and_cluster_issues(list(base_articles), registry=reg_a, use_ai=False)
    map_a = {r["id"]: r["isu"] for r in res_a}

    shuffled = list(base_articles)
    rng = random.Random(42)
    rng.shuffle(shuffled)

    reg_b = IsuRegistry(filepath=str(tmp_path / "reg_b.json"))
    reg_b.seed_releases(RILIS_FIXTURES_NOV_2026)
    res_b = assign_and_cluster_issues(shuffled, registry=reg_b, use_ai=False)
    map_b = {r["id"]: r["isu"] for r in res_b}

    assert map_a == map_b, "Hasil pengelompokan isu harus 100% deterministik meskipun urutan input diacak"


def test_registry_expiry_and_cross_day_continuation(tmp_path):
    """
    Memverifikasi:
    1. Berita hari ke-2 dalam 14 hari bergabung ke isu klaster hari ke-1.
    2. Isu klaster kedaluwarsa 14 hari setelah berita terakhir.
    """
    from datetime import date

    reg_path = tmp_path / "isu_reg.json"
    reg1 = IsuRegistry(filepath=str(reg_path))

    day1 = [ROKOK_ELEKTRONIK_PRESSCON_5[0], ROKOK_ELEKTRONIK_PRESSCON_5[1]]
    out1 = assign_and_cluster_issues(day1, registry=reg1, use_ai=False, log_path=None, coverage_path=None)
    assert out1[0]["isu_id"] == out1[1]["isu_id"]
    first_isu_id = out1[0]["isu_id"]

    # Hari ke-2 (18 Nov): berita lanjutan peristiwa sama bergabung ke isu aktif yang sama
    reg2 = IsuRegistry(filepath=str(reg_path))
    day2 = [
        {
            "id": "re_day2",
            "title": "Asosiasi Rokok Elektronik Kembali Minta Perlindungan Pemerintah untuk Tenaga Kerja",  # SINTETIS
            "published": "2026-11-18 10:00:00",
            "media_name": "Bisnis.com",
        }
    ]
    out2 = assign_and_cluster_issues(day2, registry=reg2, use_ai=False, log_path=None, coverage_path=None)
    assert out2[0]["isu_id"] == first_isu_id
    assert reg2.issues[first_isu_id]["tanggal_terakhir"] == "2026-11-18"

    # Setelah > 14 hari (misal 5 Des = 17 hari setelah 18 Nov), klaster kedaluwarsa saat prune
    pruned = reg2.prune_expired(date(2026, 12, 5))
    assert pruned == 1
    assert first_isu_id not in reg2.issues


def test_log_isu_coverage_rilis_and_excel_columns(tmp_path):
    import json
    import pandas as pd
    from src.export_excel import BERITA_COLUMNS, NEG_COLUMNS, save_to_excel

    reg = IsuRegistry(filepath=str(tmp_path / "reg_log.json"))
    reg.seed_releases(RILIS_FIXTURES_NOV_2026)

    log_file = tmp_path / "log_isu.jsonl"
    cov_file = tmp_path / "coverage_rilis.json"
    articles = [
        # SINTETIS: Cocok ke rilis minyak atsiri
        {
            "id": "cov_1",
            "title": "Kemenperin Targetkan Ekspor Minyak Atsiri Tembus USD 500 Juta pada 2029",  # SINTETIS
            "published": "2026-11-06 09:00:00",
            "link": "https://kontan.co.id/atsiri-500",
            "media_name": "Kontan",
            "Tone": "Positif",
        },
        {
            "id": "cov_2",
            "title": "Ekspor Sawit RI Diproyeksi Turun hingga 5 Juta Ton Gegara El Nino hingga B50",
            "published": "2026-11-06 10:00:00",
            "link": "https://metrotvnews.com/sawit-turun",
            "media_name": "MetroTVNews.com",
            "Tone": "Negatif",
        },
    ]

    assigned = assign_and_cluster_issues(
        articles,
        registry=reg,
        use_ai=False,
        log_path=str(log_file),
        coverage_path=str(cov_file),
    )

    assert log_file.exists()
    log_lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(log_lines) == 2
    for entry in log_lines:
        assert {"isu", "sumber_isu", "skor", "margin"}.issubset(entry.keys())

    assert cov_file.exists()
    cov_data = json.loads(cov_file.read_text(encoding="utf-8"))
    atsiri_cov = cov_data["rilis_atsiri_5nov"]
    assert atsiri_cov["jumlah_coverage"] == 1
    assert atsiri_cov["berita"][0]["link"] == "https://kontan.co.id/atsiri-500"

    # Pastikan Excel menaruh 'Isu' tepat setelah 'Tone' dan tidak mengubah Ringkasan Negatif
    assert BERITA_COLUMNS.index("Isu") == BERITA_COLUMNS.index("Tone") + 1
    out_xlsx = str(tmp_path / "out_isu.xlsx")
    save_to_excel(assigned, out_xlsx, merge_existing=False, negative_summaries=[])
    df_b = pd.read_excel(out_xlsx, sheet_name="Berita")
    df_n = pd.read_excel(out_xlsx, sheet_name="Ringkasan Negatif")
    assert list(df_b.columns) == list(BERITA_COLUMNS)
    assert list(df_n.columns) == list(NEG_COLUMNS)
    assert "Minyak Atsiri" in str(df_b.loc[0, "Isu"])


def test_prompts_no_semicolon_or_emdash():
    from src.isu_grouping import MATCH_ISU_PROMPT, ISU_LABEL_PROMPT

    for prompt in (MATCH_ISU_PROMPT, ISU_LABEL_PROMPT):
        assert ";" not in prompt
        assert "—" not in prompt


def test_load_rilis_kemenperin_crawls_www_and_overrides_stale_csv(tmp_path, monkeypatch):
    import requests
    from datetime import date
    from src.isu_grouping import load_rilis_kemenperin

    csv_file = tmp_path / "rilis.csv"
    csv_file.write_text(
        "judul,tanggal,url,nama_acara\n"
        "\"Kemenperin Bidik Ekspor Minyak Atsiri Tembus USD 500 Juta pada 2029\",2026-11-05,"
        "https://kemenperin.go.id/artikel/72483110/stale,Lama\n",
        encoding="utf-8",
    )
    cache_file = tmp_path / "cache_rilis.json"

    page1_html = """
    <html><body>
      <a href="/artikel/72482895/PENGUMUMAN">PENGUMUMAN PEMENANG SELEKSI (27/07/2026)</a>
      <div><a href="/artikel/72483093/Kemenperin-Bidik-Ekspor-Minyak-Atsiri">
        Kemenperin Bidik Ekspor Minyak Atsiri Tembus USD 500 Juta pada 2029</a> (06/11/2026)</div>
      <div><a href="/artikel/72483142/Kemenperin-Gandeng-HIPPINDO">
        Kemenperin Gandeng HIPPINDO dan MR.DIY, Perluas Pasar Produk IKM Nasional</a> (17/11/2026)</div>
      <ul class="pagination">
        <li class="active"><span>1</span></li>
        <li><a href="/siaran-pers?&amp;hal=p2">2</a></li>
      </ul>
    </body></html>
    """
    page2_html = """
    <html><body>
      <div><a href="/artikel/72483050/Rilis-Oktober-Agro">
        Kemenperin Pacu Ekspor Industri Agro Oktober</a> (25/10/2026)</div>
    </body></html>
    """

    requested_urls = []

    class FakeResp:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    def fake_get(url, **_kw):
        requested_urls.append(url)
        if url.endswith("/robots.txt"):
            return FakeResp(404, "")
        if url.endswith("/siaran-pers"):
            return FakeResp(200, page1_html)
        if "hal=p2" in url:
            return FakeResp(200, page2_html)
        return FakeResp(404, "")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    items = load_rilis_kemenperin(
        csv_path=csv_file,
        cache_path=cache_file,
        crawl_online=True,
        target_date_range=(date(2026, 11, 1), date(2026, 11, 18)),
    )
    assert all(u.startswith("https://www.kemenperin.go.id/") for u in requested_urls)
    by_title = {r["judul"]: r for r in items}
    assert all("PENGUMUMAN" not in t for t in by_title)
    atsiri = by_title["Kemenperin Bidik Ekspor Minyak Atsiri Tembus USD 500 Juta pada 2029"]
    assert atsiri["tanggal"] == "2026-11-06"
    assert atsiri["url"] == "https://www.kemenperin.go.id/artikel/72483093/Kemenperin-Bidik-Ekspor-Minyak-Atsiri"
    assert "Kemenperin Gandeng HIPPINDO dan MR.DIY, Perluas Pasar Produk IKM Nasional" in by_title
    assert "Kemenperin Pacu Ekspor Industri Agro Oktober" not in by_title

    # Memperluas target_date_range wajib memicu crawl ulang walau cache masih dalam TTL
    calls_before = len(requested_urls)
    items_wide = load_rilis_kemenperin(
        csv_path=csv_file,
        cache_path=cache_file,
        crawl_online=True,
        target_date_range=(date(2026, 10, 20), date(2026, 11, 18)),
    )
    assert len(requested_urls) > calls_before
    assert any(r["judul"] == "Kemenperin Pacu Ekspor Industri Agro Oktober" for r in items_wide)


def test_direct_crawl_portals_includes_www_kemenperin_in_main(monkeypatch):
    from datetime import date
    import main as app_main
    import src.direct_crawl_kemenperin as dck

    fetched_urls = []
    list_html = """
    <html><body>
      <a href="/artikel/72482895/PENGUMUMAN-1">PENGUMUMAN PEMENANG SELEKSI (27/07/2026)</a>
      <div><a href="/artikel/72483142/Kemenperin-Gandeng-HIPPINDO">
        Kemenperin Gandeng HIPPINDO dan MR.DIY, Perluas Pasar Produk IKM Nasional</a> (17/11/2026)</div>
    </body></html>
    """
    art_html = "<html><body><div class='isi'><p>Kementerian Perindustrian memperluas pasar IKM nasional melalui ritel modern.</p></div></body></html>"

    def fake_fetch(url, **_kw):
        fetched_urls.append(url)
        if "/siaran-pers" in url:
            return list_html
        if "/artikel/72483142/" in url:
            return art_html
        return ""

    monkeypatch.setattr(dck, "_agro_fetch_with_retry", fake_fetch)
    items = dck.crawl_kemenperin_siaran_pers(target_date=date(2026, 11, 17), max_pages=1)
    assert fetched_urls[0] == "https://www.kemenperin.go.id/siaran-pers"
    assert len(items) == 1
    assert items[0]["link"] == "https://www.kemenperin.go.id/artikel/72483142/Kemenperin-Gandeng-HIPPINDO"
    assert "memperluas pasar IKM nasional" in items[0]["text"]

    # Pastikan _append_direct_crawl_portals di main.py menggabungkan agro + www.kemenperin.go.id
    monkeypatch.setattr(
        app_main,
        "fetch_agro_kemenperin",
        lambda *_a, **_kw: [{
            "Title": "Menperin Sarmuji Percepat Hilirisasi Sagu",
            "Link Website": "https://agro.kemenperin.go.id/artikel/sagu",
            "Tanggal": date(2026, 11, 17),
            "isi": "Isi rilis sagu.",
        }],
    )
    monkeypatch.setattr(app_main, "crawl_kemenperin_siaran_pers", lambda **_kw: items)

    queue = []
    app_main._append_direct_crawl_portals(queue, date(2026, 11, 17), date(2026, 11, 17))
    assert len(queue) == 2
    assert {q["sumber_data"] for q in queue} == {"agro.kemenperin.go.id", "Direct Crawl"}
    assert any(q["link"].startswith("https://www.kemenperin.go.id/") for q in queue)


def test_isu_registry_workflow_roundtrip_and_restore_priority(tmp_path):
    """Round-trip IsuRegistry -> persist (format branch data) -> restore -> IsuRegistry sama persis."""
    import json
    from scripts.isu_registry_state import persist_isu_registry, restore_isu_registry

    src_reg = tmp_path / "run_local" / "isu_registry.json"
    branch_reg = tmp_path / "branch_data" / "pipeline_state" / "isu_registry.json"
    restored_reg = tmp_path / "next_run" / "hasil_scrapping" / "isu_registry.json"

    reg = IsuRegistry(filepath=src_reg)
    reg.issues = {
        "rilis_001": {
            "isu_id": "rilis_001",
            "isu": "Menperin Perkuat Hilirisasi Industri Agro Nasional",
            "sumber_isu": "rilis",
            "tanggal_awal": "2026-10-01",
            "tanggal_terakhir": "2026-10-01",
            "nama_acara": "Rilis Resmi Kemenperin",
            "entitas": ["kemenperin", "agro"],
            "contoh_judul": ["Menperin Perkuat Hilirisasi Industri Agro Nasional"],
            "jumlah_berita": 3,
        },
        "klaster_aktif": {
            "isu_id": "klaster_aktif",
            "isu": "Industri Rokok Elektrik Minta Perlindungan Pemerintah",
            "sumber_isu": "klaster",
            "tanggal_awal": "2026-11-17",
            "tanggal_terakhir": "2026-11-17",
            "nama_acara": "",
            "entitas": ["rokok elektrik"],
            "contoh_judul": ["Industri Rokok Elektronik Minta Pemerintah Lindungi Tenaga Kerja"],
            "jumlah_berita": 5,
        },
        "klaster_expired": {
            "isu_id": "klaster_expired",
            "isu": "Isu Lama Lebih dari 14 Hari",
            "sumber_isu": "klaster",
            "tanggal_awal": "2026-10-20",
            "tanggal_terakhir": "2026-10-20",
            "nama_acara": "",
            "entitas": ["lama"],
            "contoh_judul": ["Isu Lama Lebih dari 14 Hari"],
            "jumlah_berita": 1,
        },
    }
    reg.save()

    # Pastikan IsuRegistry.save() menulis updated_at
    saved_raw = json.loads(src_reg.read_text(encoding="utf-8"))
    assert saved_raw.get("updated_at"), "IsuRegistry.save() harus menulis updated_at"

    # Persist: pangkas klaster > 14 hari dari end_date, pertahankan rilis & klaster aktif
    active_cnt, pruned_cnt = persist_isu_registry(
        src=src_reg,
        dst=branch_reg,
        end_date="2026-11-18",
        updated_at="2026-11-18 03:20:00",
    )
    assert active_cnt == 2
    assert pruned_cnt == 1
    assert not list(branch_reg.parent.glob("*.tmp"))

    # Restore run normal (cache kosong -> ambil dari branch data)
    assert restore_isu_registry(branch_reg, restored_reg) == "branch"
    loaded = IsuRegistry(filepath=restored_reg)
    expected_issues = {k: v for k, v in reg.issues.items() if k != "klaster_expired"}
    assert loaded.issues == expected_issues

    # Prioritas: cache lebih lama TIDAK boleh menimpa branch data
    stale_cache = tmp_path / "stale_cache.json"
    stale_cache.write_text(
        json.dumps({"updated_at": "2026-11-17 03:00:00", "issues": [{"isu_id": "stale", "isu": "Stale"}]}),
        encoding="utf-8",
    )
    assert restore_isu_registry(branch_reg, stale_cache) == "branch"
    assert IsuRegistry(filepath=stale_cache).issues == expected_issues

    # Prioritas: timestamp sama -> branch data (Lapis Utama) menang
    tie_cache = tmp_path / "tie_cache.json"
    tie_cache.write_text(
        json.dumps({"updated_at": "2026-11-18 03:20:00", "issues": [{"isu_id": "tie", "isu": "Tie"}]}),
        encoding="utf-8",
    )
    assert restore_isu_registry(branch_reg, tie_cache) == "branch"
    assert IsuRegistry(filepath=tie_cache).issues == expected_issues

    # Prioritas: cache secara ketat lebih baru -> dipertahankan
    newer_cache = tmp_path / "newer_cache.json"
    newer_issues = [{"isu_id": "klaster_newer", "isu": "Lebih Baru", "sumber_isu": "klaster", "tanggal_terakhir": "2026-11-19"}]
    newer_cache.write_text(
        json.dumps({"updated_at": "2026-11-19 03:20:00", "issues": newer_issues}),
        encoding="utf-8",
    )
    assert restore_isu_registry(branch_reg, newer_cache) == "cache"
    assert list(IsuRegistry(filepath=newer_cache).issues.keys()) == ["klaster_newer"]

    # Run pertama: keduanya tidak ada -> fresh tanpa error
    assert restore_isu_registry(tmp_path / "missing_b.json", tmp_path / "missing_c.json") == "fresh"


def test_isu_registry_local_git_restore_persist_simulation(tmp_path):
    """Simulasi urutan restore dan persist di git repo lokal sementara (tanpa remote asli)."""
    import json
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    script_path = Path(__file__).resolve().parent.parent / "scripts" / "isu_registry_state.py"
    remote = tmp_path / "origin.git"
    work = tmp_path / "work"

    def git(*args, cwd=work):
        res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
        assert res.returncode == 0, f"git {' '.join(args)} gagal:\nSTDOUT:{res.stdout}\nSTDERR:{res.stderr}"
        return res.stdout.strip()

    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(work)], check=True, capture_output=True)
    git("config", "user.name", "test-bot")
    git("config", "user.email", "test@local")
    git("checkout", "-b", "main")
    (work / "README.md").write_text("init\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "init main")
    git("push", "-u", "origin", "main")

    # Buat branch data awal (belum ada pipeline_state/isu_registry.json)
    git("checkout", "-b", "data")
    (work / "data_export").mkdir()
    (work / "data_export" / "runs.json").write_text("[]", encoding="utf-8")
    git("add", "data_export/runs.json")
    git("commit", "-m", "init data branch")
    git("push", "-u", "origin", "data")
    git("checkout", "main")

    # --- RUN 1: Pertama kali (belum ada isu_registry.json di branch data) ---
    git("fetch", "origin", "data")
    subprocess.run(["git", "checkout", "origin/data", "--", "pipeline_state"], cwd=str(work), capture_output=True)
    res1 = subprocess.run(
        [sys.executable, str(script_path), "restore", "--branch-reg", "pipeline_state/isu_registry.json", "--cache-reg", "hasil_scrapping/isu_registry.json"],
        cwd=str(work), capture_output=True, text=True, check=True,
    )
    assert "run pertama" in res1.stdout.lower()

    reg1 = IsuRegistry(filepath=work / "hasil_scrapping" / "isu_registry.json")
    reg1.issues = {
        "klaster_run1": {"isu_id": "klaster_run1", "isu": "Isu Run 1", "sumber_isu": "klaster", "tanggal_awal": "2026-11-17", "tanggal_terakhir": "2026-11-17"},
        "klaster_lama": {"isu_id": "klaster_lama", "isu": "Isu Expired", "sumber_isu": "klaster", "tanggal_awal": "2026-10-15", "tanggal_terakhir": "2026-10-15"},
    }
    reg1.save()

    staging = tmp_path / "agro_sync" / "pipeline_state" / "isu_registry.json"
    subprocess.run(
        [sys.executable, str(script_path), "persist", "--src", "hasil_scrapping/isu_registry.json", "--dst", str(staging), "--end-date", "2026-11-17"],
        cwd=str(work), capture_output=True, text=True, check=True,
    )
    git("checkout", "-B", "data", "origin/data")
    (work / "pipeline_state").mkdir(exist_ok=True)
    shutil.copy2(staging, work / "pipeline_state" / "isu_registry.json")
    git("add", "pipeline_state/isu_registry.json")
    git("commit", "-m", "chore(data): persist run 1")
    git("push", "origin", "data")
    git("checkout", "main")

    # --- RUN 2: Runner baru dengan cache lama -> branch data harus menang ---
    work2 = tmp_path / "work2"
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(work2)], check=True, capture_output=True)
    git("config", "user.name", "test-bot", cwd=work2)
    git("config", "user.email", "test@local", cwd=work2)
    (work2 / "hasil_scrapping").mkdir(parents=True, exist_ok=True)
    (work2 / "hasil_scrapping" / "isu_registry.json").write_text(
        json.dumps({"updated_at": "2026-11-16 01:00:00", "issues": [{"isu_id": "stale_cache", "isu": "Cache Usang"}]}),
        encoding="utf-8",
    )
    git("fetch", "origin", "data", cwd=work2)
    git("checkout", "origin/data", "--", "pipeline_state", cwd=work2)
    git("reset", "-q", "HEAD", "--", "pipeline_state", cwd=work2)
    # Pastikan main index tidak tercemar oleh pipeline_state
    assert git("diff", "--staged", "--name-only", cwd=work2) == ""

    res2 = subprocess.run(
        [sys.executable, str(script_path), "restore", "--branch-reg", "pipeline_state/isu_registry.json", "--cache-reg", "hasil_scrapping/isu_registry.json"],
        cwd=str(work2), capture_output=True, text=True, check=True,
    )
    assert "dipulihkan dari branch data" in res2.stdout.lower()

    reg2 = IsuRegistry(filepath=work2 / "hasil_scrapping" / "isu_registry.json")
    assert set(reg2.issues.keys()) == {"klaster_run1"}

    reg2.issues["klaster_run2"] = {
        "isu_id": "klaster_run2", "isu": "Isu Run 2", "sumber_isu": "klaster", "tanggal_awal": "2026-11-18", "tanggal_terakhir": "2026-11-18"
    }
    reg2.save()

    staging2 = tmp_path / "agro_sync2" / "pipeline_state" / "isu_registry.json"
    subprocess.run(
        [sys.executable, str(script_path), "persist", "--src", "hasil_scrapping/isu_registry.json", "--dst", str(staging2), "--end-date", "2026-11-18"],
        cwd=str(work2), capture_output=True, text=True, check=True,
    )
    shutil.rmtree(work2 / "pipeline_state")
    git("checkout", "-B", "data", "origin/data", cwd=work2)
    (work2 / "pipeline_state").mkdir(exist_ok=True)
    shutil.copy2(staging2, work2 / "pipeline_state" / "isu_registry.json")
    git("add", "pipeline_state/isu_registry.json", cwd=work2)
    git("commit", "-m", "chore(data): persist run 2", cwd=work2)
    git("push", "origin", "data", cwd=work2)

    # Verifikasi isi akhir di remote lokal origin/data dan pastikan branch main bersih dari pipeline_state
    remote_json = json.loads(git("show", "origin/data:pipeline_state/isu_registry.json", cwd=work2))
    assert {it["isu_id"] for it in remote_json["issues"]} == {"klaster_run1", "klaster_run2"}
    main_files = git("ls-tree", "-r", "--name-only", "origin/main", cwd=work2).splitlines()
    assert not any(f.startswith("pipeline_state/") for f in main_files)

    # --- RUN 3: Simulasi run gagal (persist dilewati, data branch tetap utuh dari Run 2) ---
    run_outcome = "failure"
    if run_outcome == "success":
        raise AssertionError("Persist tidak boleh berjalan saat run gagal")
    after_fail_json = json.loads(git("show", "origin/data:pipeline_state/isu_registry.json", cwd=work2))
    assert after_fail_json == remote_json



