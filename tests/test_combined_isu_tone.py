"""
tests/test_combined_isu_tone.py
Unit test (pytest, 100% data SINTETIS & mock JSON) untuk GABUNGAN_ISU_TONE_PROMPT:
1. Prompt GABUNGAN_ISU_TONE_PROMPT memakai TONE_RULES utuh tanpa ; atau em-dash.
2. Routing: klaster multi-berita -> GABUNGAN_ISU_TONE_PROMPT, rilis -> GROUP_TONE_PROMPT,
   ukuran 1 -> alur per artikel lama.
3. Respons JSON valid, urutan field terbalik, pembungkus markdown.
4. Edge case: field "isu" kosong -> hanya klaster gagal tersebut yang fallback ke jalur lama.
5. Edge case: "tone" di luar {Positif, Netral, Negatif} -> ternormalisasi aman ke Netral.
6. Edge case: "outlier_ids" berisi id yang tidak ada -> diabaikan aman tanpa crash,
   sedangkan outlier valid dipecah menjadi klaster tunggal & dinilai per artikel.
7. Kegagalan parsial dalam 1 batch -> klaster lain tetap memakai hasil gabungan,
   hanya klaster gagal yang fallback ke ISU_LABEL_PROMPT / rep + GROUP_TONE_PROMPT / fallback-mayoritas.
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.isu_grouping as ig
import src.tone_classifier as tc
from src.isu_grouping import IsuRegistry
from src.stable import DecisionCache


def _setup_env(tmp_path, monkeypatch, name="test"):
    monkeypatch.setattr(tc, "LOG_TONE_FILE", str(tmp_path / f"log_tone_{name}.jsonl"))
    cache = DecisionCache(filepath=str(tmp_path / f"cache_{name}.json"))
    monkeypatch.setattr(tc, "get_decision_cache", lambda: cache)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-sintetis")
    tc.gemini_quota_exhausted = False
    tc.reset_api_call_count()
    reg = IsuRegistry(filepath=str(tmp_path / f"reg_{name}.json"))
    return cache, reg


def _seed_reg(reg: IsuRegistry, articles: list[dict]):
    by_isu = {}
    for a in articles:
        by_isu.setdefault(a["isu_id"], []).append(a)
    for iid, ms in by_isu.items():
        reg.issues[iid] = {
            "isu_id": iid,
            "isu": ms[0]["isu"],
            "sumber_isu": ms[0]["sumber_isu"],
            "tanggal_awal": "2026-11-17",
            "tanggal_terakhir": "2026-11-17",
            "member_count": len(ms),
            "member_count_at_eval": 0,
            "sample_titles": [m["title"] for m in ms],
            "matched_articles": [{"id": m["id"], "link": m["link"], "title": m["title"]} for m in ms],
        }


def test_combined_prompt_format_and_routing_valid_and_cache(tmp_path, monkeypatch):
    # SINTETIS: uji routing klaster vs rilis vs singleton + respons gabungan valid + cache hit
    assert tc.GABUNGAN_ISU_TONE_PROMPT.startswith(tc.TONE_RULES)
    assert ";" not in tc.GABUNGAN_ISU_TONE_SUFFIX
    assert "—" not in tc.GABUNGAN_ISU_TONE_SUFFIX

    _cache, reg = _setup_env(tmp_path, monkeypatch, "valid")

    arts = [
        # Klaster multi-berita (harus masuk GABUNGAN_ISU_TONE_PROMPT)
        {"id": 1, "isu_id": "klaster_syn_1", "isu": "Temp Nama Sawit SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Ekspor Sawit Nasional Naik 12 Persen", "text": "Produksi CPO mendorong devisa negara.", "link": "https://syn.test/k1"},
        {"id": 2, "isu_id": "klaster_syn_1", "isu": "Temp Nama Sawit SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Pengiriman CPO Indonesia Meningkat Tajam", "text": "Kinerja ekspor agro mencatat rekor.", "link": "https://syn.test/k2"},
        # Rilis multi-berita (harus masuk GROUP_TONE_PROMPT & mempertahankan judul rilis)
        {"id": 3, "isu_id": "rilis_syn_1", "isu": "SINTETIS Kemenperin Dorong Hilirisasi Sagu", "sumber_isu": "rilis", "title": "SINTETIS Kemenperin Percepat Hilirisasi Sagu Maluku", "link": "https://syn.test/r1"},
        {"id": 4, "isu_id": "rilis_syn_1", "isu": "SINTETIS Kemenperin Dorong Hilirisasi Sagu", "sumber_isu": "rilis", "title": "SINTETIS Pemerintah Bangun Pabrik Pengolahan Sagu", "link": "https://syn.test/r2"},
        # Singleton (harus masuk TONE_SYSTEM_PROMPT lama)
        {"id": 5, "isu_id": "klaster_syn_s1", "isu": "SINTETIS Menperin Resmikan Pabrik Kakao", "sumber_isu": "klaster", "title": "SINTETIS Menperin Resmikan Pabrik Kakao", "link": "https://syn.test/s1"},
    ]
    _seed_reg(reg, arts)

    calls = {"combined": 0, "group": 0, "single": 0, "isu_label": 0}

    def fake_tone_model(prompt, timeout=60, max_attempts=6):
        if tc.GABUNGAN_ISU_TONE_SUFFIX in prompt:
            calls["combined"] += 1
            items = json.loads(prompt.rsplit("):\n", 1)[1])
            # Pastikan payload gabungan tidak memaksa 'isu' awal dari sentroid
            assert "isu" not in items[0]
            assert items[0]["berita"][0]["id"] in (1, 2)
            return json.dumps({
                "hasil": [{
                    "kelompok_id": items[0]["kelompok_id"],
                    "isu": "SINTETIS Ekspor Sawit Nasional Meningkat Signifikan",
                    "alasan": "Ekspor CPO naik mendorong kinerja industri agro.",
                    "outlier_ids": [],
                    "keyakinan": "tinggi",
                    "tone": "Positif",
                }]
            }), "mock-gemini", ""
        elif tc.GROUP_TONE_SUFFIX in prompt:
            calls["group"] += 1
            items = json.loads(prompt.rsplit("):\n", 1)[1])
            assert items[0]["sumber_isu"] == "rilis"
            return json.dumps({
                "hasil": [{
                    "kelompok_id": items[0]["kelompok_id"],
                    "alasan": "Langkah pemerintah memperluas hilirisasi sagu.",
                    "outlier_ids": [],
                    "keyakinan": "tinggi",
                    "tone": "Positif",
                }]
            }), "mock-gemini", ""
        else:
            calls["single"] += 1
            items = json.loads(prompt.rsplit("):\n", 1)[1])
            return json.dumps({
                "hasil": [{"id": it["id"], "fokus": "A", "alasan": "Peresmian pabrik", "dasar": "judul", "tone": "Positif"} for it in items]
            }), "mock-gemini", ""

    def fake_isu_model(prompt, timeout=60, max_attempts=4):
        calls["isu_label"] += 1
        return "", "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_tone_model), \
         patch.object(ig._ISU_MODEL_POOL, "generate_deterministic", side_effect=fake_isu_model), \
         patch("time.sleep"):
        res = tc.classify_tone_by_issue(arts, registry=reg, use_ai=True, print_mixed_report=False, combined_isu_tone=True)
        assert calls == {"combined": 1, "group": 1, "single": 1, "isu_label": 0}

        by_id = {r["id"]: r for r in res}
        assert by_id[1]["isu"] == "SINTETIS Ekspor Sawit Nasional Meningkat Signifikan"
        assert by_id[2]["isu"] == "SINTETIS Ekspor Sawit Nasional Meningkat Signifikan"
        assert by_id[1]["tone"] == "Positif"
        assert reg.issues["klaster_syn_1"]["isu"] == "SINTETIS Ekspor Sawit Nasional Meningkat Signifikan"
        assert by_id[3]["isu"] == "SINTETIS Kemenperin Dorong Hilirisasi Sagu"
        assert by_id[5]["tone"] == "Positif"

        # Jalankan ulang pada input sama -> semua cache hit (0 API call tambahan)
        calls_before = dict(calls)
        res2 = tc.classify_tone_by_issue(arts, registry=reg, use_ai=True, print_mixed_report=False, combined_isu_tone=True)
        assert calls == calls_before
        assert [r["tone"] for r in res2] == [r["tone"] for r in res]


def test_parser_reversed_markdown_invalid_tone_and_bogus_outliers(tmp_path, monkeypatch):
    # SINTETIS: field terbalik, markdown fence, tone di luar 3 kelas, dan outlier_ids fiktif + valid
    _cache, reg = _setup_env(tmp_path, monkeypatch, "edge")

    arts = [
        {"id": 10, "isu_id": "klaster_edge_1", "isu": "Temp Edge SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Harga Karet Stabil di Pasar Dunia", "link": "https://syn.test/e1"},
        {"id": 11, "isu_id": "klaster_edge_1", "isu": "Temp Edge SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Pasokan Karet Alam Nasional Terjaga", "link": "https://syn.test/e2"},
        {"id": 12, "isu_id": "klaster_edge_1", "isu": "Temp Edge SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Pabrik Ban Tutup Pabrik dan PHK Karyawan", "link": "https://syn.test/e3"},
    ]
    _seed_reg(reg, arts)

    def fake_tone_model(prompt, timeout=60, max_attempts=6):
        if tc.GABUNGAN_ISU_TONE_SUFFIX in prompt:
            # Markdown wrapped + reversed field order + invalid tone "Campuran" + bogus outlier id 9999 alongside valid outlier 12
            broken_order_md = (
                "Berikut hasil klasifikasi:\n"
                "```json\n"
                '{"hasil":[{"tone":"Campuran","keyakinan":"sedang","outlier_ids":[9999,"tidak_ada",12],"alasan":"Dinamika pasokan karet stabil.","isu":"SINTETIS Stabilitas Harga dan Pasokan Karet Nasional","kelompok_id":1}]}\n'
                "```\nTerima kasih."
            )
            return broken_order_md, "mock-gemini", ""
        else:
            # Outlier id=12 dinilai ulang lewat alur per artikel lama
            items = json.loads(prompt.rsplit("):\n", 1)[1])
            return json.dumps({
                "hasil": [{"id": it["id"], "fokus": "B", "alasan": "Penutupan pabrik ban", "dasar": "judul", "tone": "Negatif"} for it in items]
            }), "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_tone_model), patch("time.sleep"):
        res = tc.classify_tone_by_issue(arts, registry=reg, use_ai=True, print_mixed_report=False, combined_isu_tone=True)

    by_id = {r["id"]: r for r in res}
    # Anggota utama 10 & 11: tone 'Campuran' dinormalisasi ke 'Netral', nama isu diperbarui
    assert by_id[10]["tone"] == "Netral"
    assert by_id[11]["tone"] == "Netral"
    assert by_id[10]["isu"] == "SINTETIS Stabilitas Harga dan Pasokan Karet Nasional"
    # Outlier valid id=12 dipecah ke klaster tunggal & dinilai ulang -> Negatif, id fiktif 9999 tidak bikin crash
    assert by_id[12]["is_outlier"] is True
    assert by_id[12]["tone"] == "Negatif"
    assert by_id[12]["isu_id"] != "klaster_edge_1"
    assert by_id[12]["isu_id"] in reg.issues


def test_partial_batch_failure_and_empty_isu_only_failed_clusters_fallback(tmp_path, monkeypatch):
    # SINTETIS: 1 batch isi 3 klaster ->
    # kelompok 1 valid, kelompok 2 'isu' kosong, kelompok 3 JSON terpotong gagal parse.
    # Hanya kelompok 2 dan 3 yang boleh fallback ke jalur lama (ISU_LABEL_PROMPT / rep + GROUP_TONE_PROMPT)!
    _cache, reg = _setup_env(tmp_path, monkeypatch, "partial")

    arts = [
        {"id": 101, "isu_id": "k_p1", "isu": "Temp P1 SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Ekspor Kopi Tembus Rekor", "link": "https://syn.test/p1a"},
        {"id": 102, "isu_id": "k_p1", "isu": "Temp P1 SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Pengiriman Kopi Nasional Naik", "link": "https://syn.test/p1b"},
        {"id": 201, "isu_id": "k_p2", "isu": "Temp P2 SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Pemerintah Kaji Tata Niaga Gula", "link": "https://syn.test/p2a"},
        {"id": 202, "isu_id": "k_p2", "isu": "Temp P2 SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Kemenperin Evaluasi Pasokan Gula", "link": "https://syn.test/p2b"},
        {"id": 301, "isu_id": "k_p3", "isu": "Temp P3 SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Pabrik Tekstil Pangkas Produksi", "link": "https://syn.test/p3a"},
        {"id": 302, "isu_id": "k_p3", "isu": "Temp P3 SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Industri Tekstil Rumahkan Karyawan", "link": "https://syn.test/p3b"},
    ]
    _seed_reg(reg, arts)

    trace_calls = {"combined": 0, "isu_label_kids": [], "group_tone_issues": []}

    def fake_tone_model(prompt, timeout=60, max_attempts=6):
        if tc.GABUNGAN_ISU_TONE_SUFFIX in prompt:
            trace_calls["combined"] += 1
            # Kelompok 1 valid JSON, kelompok 2 punya "isu": "", kelompok 3 terpotong (JSON invalid)
            raw = (
                '{"hasil":[\n'
                '  {"kelompok_id":1,"isu":"SINTETIS Ekspor Kopi Nasional Meningkat","alasan":"Ekspor kopi mencetak rekor.","outlier_ids":[],"keyakinan":"tinggi","tone":"Positif"},\n'
                '  {"kelompok_id":2,"isu":"   ","alasan":"Kajian pasokan gula.","outlier_ids":[],"keyakinan":"sedang","tone":"Netral"},\n'
                '  {"kelompok_id":3,"isu":"SINTETIS Tekstil Terpotong\n'
                ']}'
            )
            return raw, "mock-gemini", ""
        elif tc.GROUP_TONE_SUFFIX in prompt:
            items = json.loads(prompt.rsplit("):\n", 1)[1])
            trace_calls["group_tone_issues"] = [it["isu"] for it in items]
            hasil = []
            for it in items:
                tn = "Negatif" if "Tekstil" in it["isu"] else "Netral"
                hasil.append({
                    "kelompok_id": it["kelompok_id"],
                    "alasan": f"Fallback grup untuk {it['isu']}",
                    "outlier_ids": [],
                    "keyakinan": "sedang",
                    "tone": tn,
                })
            return json.dumps({"hasil": hasil}), "mock-gemini", ""
        return "", "mock-gemini", ""

    def fake_isu_model(prompt, timeout=60, max_attempts=4):
        items = json.loads(prompt.split("Input:\n", 1)[1])
        trace_calls["isu_label_kids"] = [it["kelompok_id"] for it in items]
        hasil = []
        for it in items:
            first_title = it["berita"][0]["judul"]
            lbl = "SINTETIS Label Fallback Gula" if "Gula" in first_title else "SINTETIS Label Fallback Tekstil"
            hasil.append({"kelompok_id": it["kelompok_id"], "isu": lbl, "outlier_ids": []})
        return json.dumps({"hasil": hasil}), "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_tone_model), \
         patch.object(ig._ISU_MODEL_POOL, "generate_deterministic", side_effect=fake_isu_model), \
         patch("time.sleep"):
        res = tc.classify_tone_by_issue(arts, registry=reg, use_ai=True, print_mixed_report=False, combined_isu_tone=True)

    # Hanya klaster 2 (isu kosong) dan klaster 3 (gagal parse) yang fallback! Klaster 1 TIDAK diulang!
    assert trace_calls["combined"] == 1
    assert len(trace_calls["isu_label_kids"]) == 2
    assert len(trace_calls["group_tone_issues"]) == 2
    assert "SINTETIS Ekspor Kopi Nasional Meningkat" not in trace_calls["group_tone_issues"]

    by_id = {r["id"]: r for r in res}
    assert by_id[101]["isu"] == "SINTETIS Ekspor Kopi Nasional Meningkat"
    assert by_id[101]["tone"] == "Positif"
    assert by_id[201]["isu"] == "SINTETIS Label Fallback Gula"
    assert by_id[201]["tone"] == "Netral"
    assert by_id[301]["isu"] == "SINTETIS Label Fallback Tekstil"
    assert by_id[301]["tone"] == "Negatif"


def test_failed_cluster_fallback_to_rep_title_and_majority(tmp_path, monkeypatch):
    # SINTETIS: 1 klaster valid di gabungan, 1 klaster JSON gagal total + fallback ISU_LABEL_PROMPT & GROUP_TONE_PROMPT juga gagal -> rep + fallback-mayoritas
    _cache, reg = _setup_env(tmp_path, monkeypatch, "majfb")

    arts = [
        {"id": 1, "isu_id": "k_ok", "isu": "Temp OK SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Ekspor Kakao Melonjak 15 Persen", "link": "https://syn.test/m1a"},
        {"id": 2, "isu_id": "k_ok", "isu": "Temp OK SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Permintaan Kakao Nasional Meningkat", "link": "https://syn.test/m1b"},
        {"id": 3, "isu_id": "k_fb", "isu": "Temp Representatif Pabrik Tutup SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Pabrik Tekstil Tutup Pabrik dan Pailit", "link": "https://syn.test/m2a"},
        {"id": 4, "isu_id": "k_fb", "isu": "Temp Representatif Pabrik Tutup SINTETIS", "sumber_isu": "klaster", "title": "SINTETIS Industri Tekstil Tutup Pabrik Akibat Rugi", "link": "https://syn.test/m2b"},
    ]
    _seed_reg(reg, arts)

    def fake_tone_model(prompt, timeout=60, max_attempts=6):
        if tc.GABUNGAN_ISU_TONE_SUFFIX in prompt:
            items = json.loads(prompt.rsplit("):\n", 1)[1])
            ok_item = next(it for it in items if "Kakao" in it["berita"][0]["judul"])
            # Klaster Kakao valid, klaster Tekstil sengaja hilang / gagal parse
            return json.dumps({
                "hasil": [{
                    "kelompok_id": ok_item["kelompok_id"],
                    "isu": "SINTETIS Ekspor Kakao Nasional Melonjak",
                    "alasan": "Ekspor kakao meningkat.",
                    "outlier_ids": [],
                    "keyakinan": "tinggi",
                    "tone": "Positif",
                }]
            }), "mock-gemini", ""
        elif tc.GROUP_TONE_SUFFIX in prompt:
            # GROUP_TONE_PROMPT gagal / respons kosong -> memicu fallback-mayoritas
            return "", "mock-gemini", "simulated parse fail"
        return "", "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_tone_model), \
         patch.object(ig._ISU_MODEL_POOL, "generate_deterministic", return_value=("", "mock-gemini", "fail")), \
         patch("time.sleep"):
        res = tc.classify_tone_by_issue(arts, registry=reg, use_ai=True, print_mixed_report=False, combined_isu_tone=True)

    by_id = {r["id"]: r for r in res}
    assert by_id[1]["isu"] == "SINTETIS Ekspor Kakao Nasional Melonjak"
    assert by_id[1]["tone"] == "Positif"
    assert by_id[1]["metode"] == "AI-isu"
    assert by_id[3]["isu"] in (
        "SINTETIS Pabrik Tekstil Tutup Pabrik dan Pailit",
        "SINTETIS Industri Tekstil Tutup Pabrik Akibat Rugi",
    )
    # Di indikator Biro Humas (A1), pabrik tutup/rugi tanpa serangan ke Kemenperin -> Netral
    assert by_id[3]["tone"] == "Netral"
    assert by_id[3]["metode"] == "fallback-mayoritas"


def test_main_classify_with_issue_grouping_updates_isu_and_log(tmp_path, monkeypatch):
    # SINTETIS: uji main._classify_with_issue_grouping menunda ISU_LABEL_PROMPT & menulis log_isu.jsonl sesudah nama isu + outlier selesai
    import main as app_main

    _cache, _ = _setup_env(tmp_path, monkeypatch, "mainflow")
    log_isu_file = tmp_path / "log_isu_main.jsonl"
    reg_file = tmp_path / "reg_main.json"
    monkeypatch.setattr(app_main, "DEFAULT_LOG_ISU_PATH", str(log_isu_file))
    monkeypatch.setattr(app_main, "IsuRegistry", lambda: IsuRegistry(filepath=str(reg_file)))
    monkeypatch.setattr(app_main, "load_rilis_kemenperin", lambda **_kw: [])

    seen_flags = {}
    orig_assign = ig.assign_and_cluster_issues

    def tracked_assign(*args, **kwargs):
        seen_flags["label_with_llm"] = kwargs.get("label_with_llm")
        seen_flags["log_path"] = kwargs.get("log_path")
        kwargs["coverage_path"] = None
        return orig_assign(*args, **kwargs)

    monkeypatch.setattr(app_main, "assign_and_cluster_issues", tracked_assign)

    arts = [
        {"title": "SINTETIS Ekspor CPO Sawit Naik Tajam", "published": "2026-11-17 10:00:00", "link": "https://syn.test/g1", "media_name": "Media A"},
        {"title": "SINTETIS Ekspor CPO Sawit Melonjak Tinggi", "published": "2026-11-17 11:00:00", "link": "https://syn.test/g2", "media_name": "Media B"},
    ]

    def fake_tone_model(prompt, timeout=60, max_attempts=6):
        items = json.loads(prompt.rsplit("):\n", 1)[1])
        return json.dumps({
            "hasil": [{
                "kelompok_id": items[0]["kelompok_id"],
                "isu": "SINTETIS Nama Isu Final Dari Prompt Gabungan",
                "alasan": "Ekspor CPO naik.",
                "outlier_ids": [],
                "keyakinan": "tinggi",
                "tone": "Positif",
            }]
        }), "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_tone_model), \
         patch.object(ig._ISU_MODEL_POOL, "generate_deterministic", side_effect=AssertionError("ISU_LABEL_PROMPT tidak boleh dipanggil di mode gabungan")), \
         patch("time.sleep"):
        tone_map = app_main._classify_with_issue_grouping(arts, use_ai=True, combined_isu_tone=True)

    assert seen_flags == {"label_with_llm": False, "log_path": None}
    assert tone_map == {1: "Positif", 2: "Positif"}
    assert arts[0]["Isu"] == "SINTETIS Nama Isu Final Dari Prompt Gabungan"
    assert arts[1]["Isu"] == "SINTETIS Nama Isu Final Dari Prompt Gabungan"
    assert arts[0]["Alasan Tone"] == "Ekspor CPO naik."
    assert arts[1]["Alasan Tone"] == "Ekspor CPO naik."
    log_entries = [json.loads(line) for line in log_isu_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(log_entries) == 2
    assert all(le["isu"] == "SINTETIS Nama Isu Final Dari Prompt Gabungan" for le in log_entries)


def test_alasan_tone_exported_to_excel_without_relevance_collision(tmp_path):
    # SINTETIS: pastikan kolom 'Alasan Tone' tertulis sesudah 'Isu', tidak tertukar dengan 'alasan' relevansi, dan ikut tersinkron di cache
    import pandas as pd
    from src.export_excel import BERITA_COLUMNS, save_to_excel
    from src.stable import _apply_decision_cache_to_record

    out_xlsx = tmp_path / "alasan_tone_syn.xlsx"
    records = [
        {
            "Tanggal": "2026-11-17 09:00:00",
            "Title": "SINTETIS Menperin Resmikan Pabrik Sagu Modern",
            "Link Website": "https://syn.test/al1",
            "Media Name": "Media A",
            "Tone": "Positif",
            "Isu": "SINTETIS Peresmian Pabrik Sagu Kemenperin",
            "Alasan Tone": "Berita aktivitas resmi Menperin terkait industri agro (indikator P1).",
            "Status Review": "RELEVAN",
            "Keywords": "sagu",
            "Sumber Data": "RSS",
        },
        {
            # Tidak ada Tone maupun Alasan Tone, hanya 'alasan' relevansi: fallback harus mengisi Alasan Tone Humas, bukan 'alasan' relevansi
            "Tanggal": "2026-11-17 10:00:00",
            "Title": "SINTETIS Serikat Pekerja Kritik Kebijakan Impor Kemenperin",
            "Link Website": "https://syn.test/al2",
            "Media Name": "Media B",
            "alasan": "ALASAN RELEVANSI BUKAN TONE",
            "Status Review": "RELEVAN",
            "Keywords": "kemenperin",
            "Sumber Data": "RSS",
        },
    ]
    save_to_excel(records, str(out_xlsx), merge_existing=False, negative_summaries=[])

    df_b = pd.read_excel(out_xlsx, sheet_name="Berita")
    assert list(df_b.columns) == list(BERITA_COLUMNS)
    assert BERITA_COLUMNS.index("Alasan Tone") == BERITA_COLUMNS.index("Isu") + 1
    assert df_b.loc[0, "Alasan Tone"] == "Berita aktivitas resmi Menperin terkait industri agro (indikator P1)."
    assert df_b.loc[1, "Tone"] == "Negatif"
    alasan_fb = str(df_b.loc[1, "Alasan Tone"])
    assert alasan_fb != ""
    assert "ALASAN RELEVANSI BUKAN TONE" not in alasan_fb

    cached = {
        "tone": {
            "tone": "Negatif",
            "alasan": "Klaim pihak luar menyerang kebijakan Kemenperin (indikator N2).",
        }
    }
    updated, kept, used_cache = _apply_decision_cache_to_record(
        {"Link Website": "https://syn.test/al2", "Tone": "Netral", "Alasan Tone": ""},
        cached,
    )
    assert kept and used_cache
    assert updated["Tone"] == "Negatif"
    assert updated["Alasan Tone"] == "Klaim pihak luar menyerang kebijakan Kemenperin (indikator N2)."
