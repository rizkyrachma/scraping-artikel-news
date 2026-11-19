"""
tests/test_humas_tone.py
Unit test (pytest) 100% SINTETIS untuk Indikator Sentimen Biro Humas Kemenperin:
- Mencakup semua cabang indikator: P1, P2, Ne1, Ne2, N1, N2, N3, N4, K4.
- Mencakup semua asumsi sementara: A1..A5, ASUMSI_K4_NETRAL, dan TONE_ISU_MENGIKUTI_PERISTIWA.
- Menguji pembatasan keyakinan maksimal 'sedang' bila hanya ada judul (tanpa isi).
- Menguji determinisme, parser urutan terbalik dengan 'hubungan' dan 'arah',
  fallback saat Gemini gagal/invalid, serta log_tone.jsonl.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.tone_classifier as tc
from src.isu_grouping import IsuRegistry
from src.stable import DecisionCache


def test_humas_constants_and_prompt_punctuation():
    # SINTETIS: memastikan konstanta ASUMSI SEMENTARA dan prompt bebas tanda ; serta em-dash
    assert isinstance(tc.ASUMSI_K4_NETRAL, bool)
    assert isinstance(tc.ASUMSI_A1_KONDISI_INDUSTRI_NETRAL, bool)
    assert isinstance(tc.ASUMSI_A2_DESAKAN_UMUM_PEMERINTAH_NETRAL, bool)
    assert isinstance(tc.ASUMSI_A3_KEBIJAKAN_INSTANSI_LAIN_NON_KEMENPERIN, bool)
    assert isinstance(tc.ASUMSI_A4_KATA_NEGATIF_BUKAN_PEMICU, bool)
    assert isinstance(tc.ASUMSI_A5_RAGU_PILIH_NETRAL, bool)
    assert isinstance(tc.TONE_ISU_MENGIKUTI_PERISTIWA, bool)

    for p in (
        tc.TONE_RULES,
        tc.TONE_ARTICLE_FORMAT,
        tc.TONE_SYSTEM_PROMPT,
        tc.GROUP_TONE_SUFFIX,
        tc.GROUP_TONE_PROMPT,
        tc.GABUNGAN_ISU_TONE_SUFFIX,
        tc.GABUNGAN_ISU_TONE_PROMPT,
    ):
        assert ";" not in p
        assert "—" not in p

    assert '"hubungan"' in tc.TONE_ARTICLE_FORMAT
    assert '"arah"' in tc.TONE_ARTICLE_FORMAT
    assert "id" in tc.TONE_ARTICLE_FORMAT


# SINTETIS: satu atau lebih fixture per cabang P1, P2, Ne1, Ne2, N1, N2, N3, N4, K4, serta A1..A5
SYNTHETIC_HUMAS_CASES = [
    # P1: K1 + aktivitas/pernyataan Kemenperin tanpa serangan -> Positif
    (
        "P1_aktivitas",
        "SINTETIS Kemenperin Luncurkan Pusat Inovasi Olahan Kakao di Makassar",
        "Kementerian Perindustrian meresmikan pusat inovasi kakao bersama pelaku IKM binaan untuk memperkuat daya saing agro.",
        "K1",
        "Positif",
    ),
    (
        "P1_narasumber_pejabat",
        "SINTETIS Putu Juli Ardika Dorong Modernisasi Mesin Pabrik Gula Nasional",
        "Direktur Jenderal Industri Agro Putu Juli Ardika menegaskan pentingnya peremajaan mesin giling.",
        "K1",
        "Positif",
    ),
    (
        "P1_jubir_antikorupsi",
        "SINTETIS Juru Bicara Kemenperin Tegaskan Komitmen Zona Integritas Bebas Korupsi",
        "Juru bicara Kemenperin menjelaskan program pencegahan gratifikasi di seluruh balai industri.",
        "K1",
        "Positif",
    ),
    # P2: K3 + pihak lain mendukung kebijakan/eksistensi Kemenperin -> Positif
    (
        "P2_dukung_kebijakan",
        "SINTETIS Asosiasi Manufaktur Apresiasi Kebijakan TKDN yang Terbukti Melindungi Pabrik Lokal",
        "Para pelaku industri menyatakan dukungan penuh dan memuji aturan TKDN karena mendorong investasi pabrik.",
        "K3",
        "Positif",
    ),
    # Ne1: K2 pelengkap tanpa serangan -> Netral
    (
        "Ne1_pelengkap_di_isi",
        "SINTETIS Pemprov Jawa Timur Buka Pameran UMKM Pangan Daerah",
        "Pemerintah Provinsi Jawa Timur menggelar pameran pangan selama tiga hari. Dalam pembukaan tersebut, puluhan stan kuliner tampil meriah bersama pelaku usaha lokal. Selain dinas daerah, perwakilan Kemenperin juga turut hadir meninjau area pameran bersama asosiasi.",
        "K2",
        "Netral",
    ),
    # Ne2: K3 tanpa dukungan maupun serangan -> Netral
    (
        "Ne2_topik_kebijakan_tanpa_sikap",
        "SINTETIS Pelaku Industri Mamin Bahas Rantai Pasok Bahan Baku Kemasan Nasional",
        "Diskusi asosiasi industri makanan dan minuman memetakan kebutuhan pasokan bahan baku pabrik sepanjang kuartal ketiga.",
        "K3",
        "Netral",
    ),
    # N1: K1/K2 serangan menyudutkan eksistensi/kebijakan Kemenperin -> Negatif
    (
        "N1_serangan_ke_kemenperin",
        "SINTETIS Gabungan Asosiasi Kritik Pedas Kebijakan Kemenperin yang Dinilai Menghambat Industri",
        "Asosiasi pengusaha mengkritik dan menyalahkan Kemenperin atas aturan yang dianggap membebani pabrik domestik.",
        "K1",
        "Negatif",
    ),
    (
        "N1_k2_menyudutkan",
        "SINTETIS Laporan Audit Sorot Kelalaian Tata Kelola Industri, Nama Kemenperin Disalahkan",
        "Sebagian besar laporan membahas kerugian pabrik tekstil daerah, serta menyalahkan Kemenperin sebagai pihak yang lamban.",
        "K2",
        "Negatif",
    ),
    # N2: K1/K2 isu korupsi / pelanggaran hukum / nilai moral terkait Kemenperin -> Negatif
    (
        "N2_korupsi_kemenperin",
        "SINTETIS Kejaksaan Selidiki Dugaan Korupsi dan Suap Izin di Lingkungan Kemenperin",
        "Tim penyidik melakukan penggeledahan kantor terkait dugaan gratifikasi oleh oknum pejabat Kemenperin.",
        "K1",
        "Negatif",
    ),
    # N3: K1 narasumber/institusi Kemenperin berseberangan dengan kepentingan/eksistensi Kemenperin -> Negatif
    (
        "N3_internal_berseberangan",
        "SINTETIS Sekjen Kemenperin Akui Kegagalan Program Pembinaan Industri dan Menyesalkan Lemahnya Pengawasan",
        "Dalam rapat internal terbuka, Sekjen Kemenperin mengakui kelalaian serta menyatakan aturan internal selama ini tidak efektif.",
        "K1",
        "Negatif",
    ),
    # N4: K3 pihak lain menyerang kebijakan Kemenperin -> Negatif
    (
        "N4_serang_kebijakan_kemenperin",
        "SINTETIS Koalisi Pengusaha Gugat Aturan TKDN dan Standar Industri yang Dinilai Mematikan Usaha",
        "Sejumlah pelaku usaha mengkritik dan menggugat regulasi TKDN serta aturan industri karena dianggap merugikan pabrik.",
        "K3",
        "Negatif",
    ),
    # K4: Tidak berkaitan dengan Kemenperin (ASUMSI_K4_NETRAL) -> Netral
    (
        "K4_non_kemenperin",
        "SINTETIS Turnamen Bulu Tangkis Antar Pelajar Digelar di Bandung Akhir Pekan Ini",
        "Ratusan pelajar mengikuti kejuaraan bulu tangkis tingkat kota selama dua hari berturut-turut.",
        "K4",
        "Netral",
    ),
    # A1: Kondisi industri memburuk tanpa serangan ke Kemenperin -> Netral
    (
        "A1_ekspor_turun_tanpa_serangan",
        "SINTETIS Harga Karet Global Anjlok, Sejumlah Pabrik Olahan Pangkas Produksi",
        "Penurunan permintaan global memicu penurunan ekspor serta pengurangan shift kerja karyawan pabrik.",
        "K3",
        "Netral",
    ),
    # A2: Desakan umum kepada 'pemerintah' tanpa menyebut/menyerang Kemenperin -> Netral
    (
        "A2_desakan_umum_pemerintah",
        "SINTETIS Asosiasi Industri Minuman Minta Pemerintah Beri Kelonggaran Masa Transisi Kemasan",
        "Asosiasi berharap pemerintah mempertimbangkan jadwal penyesuaian bagi pelaku usaha kecil dan menengah.",
        "K3",
        "Netral",
    ),
    # A3: Kebijakan/kritik instansi lain tanpa melibatkan Kemenperin -> Netral
    (
        "A3_kebijakan_instansi_lain",
        "SINTETIS Nelayan Kritik Kebijakan Kementerian Kelautan dan Perikanan soal Kuota Tangkap Ikan",
        "Organisasi nelayan menyoroti aturan KKP terkait izin kapal tangkap di wilayah timur tanpa menyinggung Kemenperin.",
        "K4",
        "Netral",
    ),
    # A4: Kata bernada negatif di judul tanpa serangan ke Kemenperin -> bukan pemicu Negatif
    (
        "A4_kata_negatif_di_judul",
        "SINTETIS Kemenperin Siapkan Langkah Antisipasi Hadapi Pelemahan Permintaan Tekstil",
        "Menperin menyiapkan strategi diversifikasi pasar ekspor guna menjaga utilisasi pabrik nasional.",
        "K1",
        "Positif",
    ),
    # A5: Kontras/ragu tanpa serangan/dukungan jelas -> Netral
    (
        "A5_ragu_netral",
        "SINTETIS Pengamat Bahas Dinamika Regulasi Kemasan Industri Pangan Tahun Depan",
        "Berbagai pandangan pelaku usaha dan akademisi dipaparkan tanpa kesimpulan yang mendukung atau menyerang instansi mana pun.",
        "K3",
        "Netral",
    ),
]


@pytest.mark.parametrize("case_id,title,text,exp_hub,exp_tone", SYNTHETIC_HUMAS_CASES)
def test_synthetic_humas_branches_fallback(case_id, title, text, exp_hub, exp_tone):
    detail = tc._classify_tone_fallback_detail(title=title, text=text)
    assert detail["hubungan"] == exp_hub, f"[{case_id}] hubungan expected {exp_hub}, got {detail['hubungan']} ({detail})"
    assert detail["tone"] == exp_tone, f"[{case_id}] tone expected {exp_tone}, got {detail['tone']} ({detail})"
    # Wrapper backward-compatible tetap 3-tuple
    t3, dasar3, alasan3 = tc.classify_tone_fallback(title, text)
    assert t3 == exp_tone
    assert dasar3 in ("judul", "isi")
    assert alasan3


def test_title_only_caps_confidence_to_sedang_and_determinism(tmp_path, monkeypatch):
    # SINTETIS: uji keyakinan dibatasi maksimal 'sedang' saat hanya judul tersedia & hasil deterministik
    monkeypatch.setattr(tc, "LOG_TONE_FILE", str(tmp_path / "log_tone_cap.jsonl"))
    cache = DecisionCache(filepath=str(tmp_path / "cache_cap.json"))
    monkeypatch.setattr(tc, "get_decision_cache", lambda: cache)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-sintetis")
    tc.gemini_quota_exhausted = False

    title_only_art = {
        "id": 1,
        "isu_id": "k_cap",
        "isu": "SINTETIS Menperin Resmikan Pusat Riset Agro",
        "sumber_isu": "klaster",
        "title": "SINTETIS Menperin Resmikan Pusat Riset Agro",
        "text": "",
        "link": "https://syn.test/cap1",
    }

    def fake_single(prompt, timeout=60, max_attempts=6):
        items = json.loads(prompt.rsplit("):\n", 1)[1])
        return json.dumps({
            "hasil": [{
                "id": items[0]["id"],
                "hubungan": "K1",
                "arah": "mendukung",
                "alasan": "SINTETIS Aktivitas Menperin meresmikan pusat riset.",
                "dasar": "judul",
                "keyakinan": "tinggi",
                "tone": "Positif",
            }]
        }), "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_single):
        res1 = tc.classify_tone_batch([dict(title_only_art)], use_ai=True, ensure_consistency=False)
        res2 = tc.classify_tone_batch([dict(title_only_art)], use_ai=True, ensure_consistency=False)

    assert res1[0]["tone"] == res2[0]["tone"] == "Positif"
    assert res1[0]["hubungan"] == "K1"
    assert res1[0]["arah"] == "mendukung"
    # Karena tanpa teks isi, keyakinan tidak boleh 'tinggi' (maksimal 'sedang')
    assert res1[0]["keyakinan"] in ("sedang", "rendah")
    assert res1[0]["keyakinan"] != "tinggi"


def test_parser_reversed_fields_invalid_gemini_fallback_and_logs(tmp_path, monkeypatch):
    # SINTETIS: uji parser urutan terbalik dengan field baru, respons Gemini invalid jatuh ke fallback, dan log_tone.jsonl mencatat hubungan+arah
    log_path = tmp_path / "log_tone_humas.jsonl"
    monkeypatch.setattr(tc, "LOG_TONE_FILE", str(log_path))
    cache = DecisionCache(filepath=str(tmp_path / "cache_rev.json"))
    monkeypatch.setattr(tc, "get_decision_cache", lambda: cache)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-sintetis")
    tc.gemini_quota_exhausted = False

    # 1. Uji parser grup dengan urutan terbalik + field baru hubungan & arah
    rev_group_resp = (
        "```json\n"
        '{"hasil":[{"tone":"Positif","keyakinan":"tinggi","outlier_ids":[],"alasan":"Kegiatan Kemenperin.","arah":"mendukung","hubungan":"K1","isu":"SINTETIS Agenda Kemenperin","kelompok_id":1}]}\n'
        "```"
    )
    parsed_g = tc._parse_group_tone_json(rev_group_resp)
    assert len(parsed_g) == 1
    assert parsed_g[0]["hubungan"] == "K1"
    assert parsed_g[0]["arah"] == "mendukung"
    assert parsed_g[0]["tone"] == "Positif"

    # 2. Uji per-artikel: id=1 valid urutan terbalik, id=2 JSON rusak/tone invalid jatuh ke fallback
    arts = [
        {"id": 1, "title": "SINTETIS Menperin Luncurkan Balai Agro Baru", "text": "Kementerian Perindustrian meluncurkan balai riset baru.", "link": "https://syn.test/p1", "isu_id": "k1", "sumber_isu": "klaster"},
        {"id": 2, "title": "SINTETIS Harga Gula Global Melemah Akibat Cuaca", "text": "Ekspor gula mengalami penurunan tanpa menyalahkan instansi apa pun.", "link": "https://syn.test/p2", "isu_id": "k2", "sumber_isu": "klaster"},
    ]

    def fake_mixed_valid_invalid(prompt, timeout=60, max_attempts=6):
        # id=1 valid reversed order, id=2 tone di luar kelas yang harus ditolak ke fallback
        raw = (
            '{"hasil":[\n'
            '  {"tone":"Positif","dasar":"judul","alasan":"Kegiatan Kemenperin.","arah":"mendukung","hubungan":"K1","id":1},\n'
            '  {"id":2,"hubungan":"K3","arah":"tidak ada","alasan":"Rusak","dasar":"judul","tone":"BukanToneValid"}\n'
            ']}'
        )
        return raw, "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_mixed_valid_invalid):
        res = tc.classify_tone_batch(arts, use_ai=True, ensure_consistency=False)

    assert res[0]["tone"] == "Positif"
    assert res[0]["hubungan"] == "K1"
    assert res[0]["arah"] == "mendukung"
    assert res[0]["metode"] == "AI"

    # id=2 harus jatuh ke fallback rule-based (bukan 'BukanToneValid')
    assert res[1]["tone"] == "Netral"
    assert res[1]["hubungan"] == "K3"
    assert res[1]["arah"] == "tidak ada"
    assert res[1]["metode"] == "fallback"

    logs = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(logs) == 2
    assert logs[0]["hubungan"] == "K1" and logs[0]["arah"] == "mendukung"
    assert logs[1]["hubungan"] == "K3" and logs[1]["arah"] == "tidak ada"


def test_issue_tone_k1_event_applies_to_non_k1_members_except_outlier(tmp_path, monkeypatch):
    # SINTETIS: uji TONE_ISU_MENGIKUTI_PERISTIWA pada mode fallback dan mode gabungan AI -> anggota non-K1 ikut K1, outlier dinilai sendiri
    monkeypatch.setattr(tc, "LOG_TONE_FILE", str(tmp_path / "log_tone_isu.jsonl"))
    cache = DecisionCache(filepath=str(tmp_path / "cache_isu.json"))
    monkeypatch.setattr(tc, "get_decision_cache", lambda: cache)
    reg = IsuRegistry(filepath=str(tmp_path / "reg_isu.json"))

    # Kasus A (fallback offline): 1 judul tidak menyebut Kemenperin + 1 judul menyebut Menperin
    arts_off = [
        {"id": 1, "isu_id": "k_k1_mix", "isu": "SINTETIS Dukungan Proyek Sagu", "sumber_isu": "klaster", "title": "SINTETIS Pemda Dorong Hilirisasi Sagu Daerah", "text": "Bupati mendorong sagu masuk proyek daerah.", "link": "https://syn.test/k1a"},
        {"id": 2, "isu_id": "k_k1_mix", "isu": "SINTETIS Dukungan Proyek Sagu", "sumber_isu": "klaster", "title": "SINTETIS Menperin Terbitkan Surat Dukungan Proyek Sagu Daerah", "text": "Menperin menerbitkan surat dukungan resmi proyek strategis sagu.", "link": "https://syn.test/k1b"},
    ]
    reg.issues["k_k1_mix"] = {"isu_id": "k_k1_mix", "isu": "SINTETIS Dukungan Proyek Sagu", "sumber_isu": "klaster", "member_count": 2, "member_count_at_eval": 0}
    res_off = tc.classify_tone_by_issue(arts_off, registry=reg, use_ai=False, print_mixed_report=False)
    # Karena peristiwanya K1 (kegiatan Menperin), anggota non-K1 (id=1) juga harus mendapat Positif!
    assert res_off[0]["tone"] == "Positif"
    assert res_off[1]["tone"] == "Positif"
    assert res_off[0]["hubungan"] == "K1"

    # Kasus B (AI gabungan + outlier): anggota id=3 ditandai outlier dan dinilai sendiri sebagai K3 Netral/Negatif terpisah
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-sintetis")
    tc.gemini_quota_exhausted = False
    arts_ai = [
        {"id": 10, "isu_id": "k_ai_mix", "isu": "Temp", "sumber_isu": "klaster", "title": "SINTETIS Pemda Gelar Pameran Industri Daerah", "text": "Pameran membahas program pengembangan industri daerah.", "link": "https://syn.test/a1"},
        {"id": 11, "isu_id": "k_ai_mix", "isu": "Temp", "sumber_isu": "klaster", "title": "SINTETIS Dirjen Industri Agro Hadiri dan Resmikan Pameran Industri Daerah", "text": "Dirjen Industri Agro membuka pameran pengembangan agro daerah.", "link": "https://syn.test/a2"},
        {"id": 12, "isu_id": "k_ai_mix", "isu": "Temp", "sumber_isu": "klaster", "title": "SINTETIS Koalisi Pengusaha Kritik Aturan TKDN Kemenperin", "text": "Pelaku usaha mengkritik dan menolak regulasi TKDN Kemenperin.", "link": "https://syn.test/a3"},
    ]
    reg.issues["k_ai_mix"] = {"isu_id": "k_ai_mix", "isu": "Temp", "sumber_isu": "klaster", "member_count": 3, "member_count_at_eval": 0}

    def fake_ai(prompt, timeout=60, max_attempts=6):
        if tc.GABUNGAN_ISU_TONE_SUFFIX in prompt:
            return json.dumps({
                "hasil": [{
                    "kelompok_id": 1,
                    "isu": "SINTETIS Dirjen Industri Agro Resmikan Pameran Industri Daerah",
                    "hubungan": "K1",
                    "arah": "mendukung",
                    "alasan": "Peristiwa merupakan kegiatan resmi pejabat Kemenperin.",
                    "outlier_ids": [12],
                    "keyakinan": "tinggi",
                    "tone": "Positif",
                }]
            }), "mock-gemini", ""
        items = json.loads(prompt.rsplit("):\n", 1)[1])
        return json.dumps({
            "hasil": [{
                "id": items[0]["id"],
                "hubungan": "K1",
                "arah": "menyerang",
                "alasan": "Berita mengkritik langsung aturan Kemenperin.",
                "dasar": "judul",
                "tone": "Negatif",
            }]
        }), "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_ai), patch("time.sleep"):
        res_ai = tc.classify_tone_by_issue(arts_ai, registry=reg, use_ai=True, print_mixed_report=False, combined_isu_tone=True)

    by_id = {r["id"]: r for r in res_ai}
    assert by_id[10]["tone"] == "Positif" and by_id[10]["hubungan"] == "K1"
    assert by_id[11]["tone"] == "Positif" and by_id[11]["hubungan"] == "K1"
    assert by_id[12]["is_outlier"] is True
    assert by_id[12]["tone"] == "Negatif"
    assert by_id[12]["isu_id"] != "k_ai_mix"
