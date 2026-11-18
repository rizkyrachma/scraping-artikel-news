"""
tests/test_isu_tone.py
Unit test (pytest) Fase 2: Satu Tone per Isu (src/tone_classifier.py + src/isu_grouping.py):
- Memverifikasi pemisahan TONE_RULES dan GROUP_TONE_PROMPT (tanpa titik koma & em dash).
- Memverifikasi batas 8 judul beragam + 2 cuplikan 400 karakter & batch max 4 isu per panggilan AI.
- Memverifikasi isu berukuran 1 dan outlier_ids memakai alur per artikel lama.
- Memverifikasi fallback 'fallback-mayoritas' dan kondisi seri -> Netral.
- Memverifikasi pewarisan tone lintas hari (tanpa API) & re-evaluasi setelah >= 3 anggota baru.
- Memverifikasi laporan 'berita kembar beda tone' (17 Nov rokok elektronik 4 Negatif + 1 Positif -> bersatu).
- Memverifikasi DecisionCache (hash sorted canonical URLs + version) & log_tone.jsonl (isu_id, sumber_isu, keyakinan).
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.tone_classifier as tc
from src.isu_grouping import IsuRegistry, assign_and_cluster_issues
from src.stable import DecisionCache


def test_prompts_split_and_punctuation_rules():
    assert tc.TONE_RULES in tc.TONE_SYSTEM_PROMPT
    assert tc.TONE_RULES in tc.GROUP_TONE_PROMPT
    assert tc.TONE_RULES in tc.GABUNGAN_ISU_TONE_PROMPT
    assert tc.TONE_PROMPT_VERSION == "v2026-11-18-d"

    for p in (
        tc.TONE_RULES,
        tc.TONE_ARTICLE_FORMAT,
        tc.GROUP_TONE_SUFFIX,
        tc.GROUP_TONE_PROMPT,
        tc.GABUNGAN_ISU_TONE_SUFFIX,
        tc.GABUNGAN_ISU_TONE_PROMPT,
    ):
        assert ";" not in p
        assert "—" not in p


def test_diverse_member_limit_and_400_char_snippets():
    members = [
        {"id": i, "title": f"Judul Isu Sawit Variasi {i} dengan Kata Unik {i * 11}", "text": (f"Teks pembuka berita {i} sawit " * 30)}
        for i in range(1, 15)
    ]
    sel, snips = tc._select_diverse_members(members, max_n=8)
    assert len(sel) == 8
    assert len(snips) == 2
    assert all(len(s) <= 400 for s in snips)


def test_fallback_majority_and_tie_breaker_and_mixed_report(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "LOG_TONE_FILE", str(tmp_path / "log_tone.jsonl"))
    cache = DecisionCache(filepath=str(tmp_path / "cache_dec.json"))
    monkeypatch.setattr(tc, "get_decision_cache", lambda: cache)

    # Kasus 1: 5 berita rokok elektronik (baseline per artikel: 4 Negatif, 1 Positif) -> mayoritas Negatif
    arts_re = [
        {"id": 1, "title": "Industri Rokok Elektronik Minta Pemerintah Lindungi Tenaga Kerja", "media_name": "CNN Indonesia", "Tone": "Negatif", "published": "2026-11-17 15:58:09"},
        {"id": 2, "title": "Industri Rokok Elektronik Minta Perlindungan Pemerintah, Soroti Nasib Pekerja", "media_name": "Harian Jogja", "Tone": "Negatif", "published": "2026-11-17 16:02:51"},
        {"id": 3, "title": "Pelaku Industri Rokok Elektronik Minta Pemerintah Lindungi Usaha dan Tenaga Kerja", "media_name": "Sumut Pos", "Tone": "Negatif", "published": "2026-11-17 09:09:57"},
        {"id": 4, "title": "Pelaku Usaha Rokok Elektrik Minta Pemerintah Lindungi Industri & Pekerja", "media_name": "detikFinance", "Tone": "Negatif", "published": "2026-11-17 12:59:32"},
        {"id": 5, "title": "Industri REL Nasional: Pelaku Usaha dan Pekerja Memohon Perlindungan Pemerintah Jaga Tenaga Kerja", "media_name": "Index Sumut", "Tone": "Positif", "published": "2026-11-17 17:10:00"},
    ]
    reg = IsuRegistry(filepath=str(tmp_path / "reg.json"))
    grouped = assign_and_cluster_issues(arts_re, registry=reg, use_ai=False, log_path=None, coverage_path=None)
    assert len({g["isu_id"] for g in grouped}) == 1

    # Mock fallback vote yang menghasilkan 2 Positif, 1 Netral -> tes tie & majority langsung
    res = tc.classify_tone_by_issue(grouped, registry=reg, use_ai=False, print_mixed_report=True)
    assert len(res) == 5
    # Semua 5 harus seragam tone-nya (satu isu = satu tone) and metode = fallback-mayoritas
    tones = {r["tone"] for r in res}
    assert len(tones) == 1
    assert all(r["metode"] == "fallback-mayoritas" for r in res)

    # Verifikasi laporan berita kembar beda tone menangkap konflik baseline 4 Negatif + 1 Positif
    old_map = {a["id"]: a["Tone"] for a in arts_re}
    res_map = {r["id"]: r for r in res}
    mixed = tc.build_mixed_tone_report(grouped, old_map, res_map)
    assert len(mixed) == 1
    assert mixed[0]["tone_lama_dist"] == {"Negatif": 4, "Positif": 1}

    # Verifikasi log_tone.jsonl mencatat isu_id, sumber_isu, keyakinan
    log_lines = [json.loads(line) for line in (tmp_path / "log_tone.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(log_lines) == 5
    for le in log_lines:
        assert le.get("isu_id")
        assert le.get("sumber_isu") == "klaster"
        assert le.get("keyakinan") in ("tinggi", "sedang", "rendah")

    # Kasus 2: Tes seri (draw) jatuh ke Netral di _majority_fallback_vote
    draw_members = [
        {"id": "d1", "title": "Menperin Resmikan Pabrik Baru", "text": ""},  # K1 tanpa serangan -> Positif
        {"id": "d2", "title": "Kebijakan Kemenperin Dikritik dan Dinilai Merugikan Industri", "text": ""},  # N1 -> Negatif
    ]
    t_draw, key_draw, _ = tc._majority_fallback_vote(draw_members)
    assert t_draw == "Netral"
    assert key_draw == "rendah"


def test_ai_batch_4_outliers_and_cross_day_inheritance_and_reeval(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "LOG_TONE_FILE", str(tmp_path / "log_tone_ai.jsonl"))
    cache = DecisionCache(filepath=str(tmp_path / "cache_dec_ai.json"))
    monkeypatch.setattr(tc, "get_decision_cache", lambda: cache)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-test")
    tc.gemini_quota_exhausted = False

    reg_path = tmp_path / "isu_reg_ai.json"
    reg = IsuRegistry(filepath=str(reg_path))

    # Siapkan 5 isu berukuran >= 2 (harus terpecah menjadi 2 batch AI: 4 + 1) + 1 isu ukuran 1
    day1_arts = [
        # Isu A (size 3, punya 1 outlier id=3)
        {"id": 1, "isu_id": "isu_A", "isu": "Isu A", "sumber_isu": "klaster", "title": "Pabrik Sawit A Ekspansi", "link": "https://x.com/a1"},
        {"id": 2, "isu_id": "isu_A", "isu": "Isu A", "sumber_isu": "klaster", "title": "Pabrik Sawit A Tambah Kapasitas", "link": "https://x.com/a2"},
        {"id": 3, "isu_id": "isu_A", "isu": "Isu A", "sumber_isu": "klaster", "title": "Pabrik Tekstil B Tutup Pabrik dan PHK", "link": "https://x.com/a3"},
        # Isu B..E (masing-masing size 2)
        {"id": 4, "isu_id": "isu_B", "isu": "Isu B", "sumber_isu": "klaster", "title": "Berita B1", "link": "https://x.com/b1"},
        {"id": 5, "isu_id": "isu_B", "isu": "Isu B", "sumber_isu": "klaster", "title": "Berita B2", "link": "https://x.com/b2"},
        {"id": 6, "isu_id": "isu_C", "isu": "Isu C", "sumber_isu": "klaster", "title": "Berita C1", "link": "https://x.com/c1"},
        {"id": 7, "isu_id": "isu_C", "isu": "Isu C", "sumber_isu": "klaster", "title": "Berita C2", "link": "https://x.com/c2"},
        {"id": 8, "isu_id": "isu_D", "isu": "Isu D", "sumber_isu": "klaster", "title": "Berita D1", "link": "https://x.com/d1"},
        {"id": 9, "isu_id": "isu_D", "isu": "Isu D", "sumber_isu": "klaster", "title": "Berita D2", "link": "https://x.com/d2"},
        {"id": 10, "isu_id": "isu_E", "isu": "Isu E", "sumber_isu": "klaster", "title": "Berita E1", "link": "https://x.com/e1"},
        {"id": 11, "isu_id": "isu_E", "isu": "Isu E", "sumber_isu": "klaster", "title": "Berita E2", "link": "https://x.com/e2"},
        # Isu F (size 1 -> wajib pakai alur per artikel lama)
        {"id": 12, "isu_id": "isu_F", "isu": "Isu F", "sumber_isu": "klaster", "title": "Menperin Resmikan Pabrik Baru", "link": "https://x.com/f1"},
    ]
    for a in day1_arts:
        reg.issues[a["isu_id"]] = {
            "isu_id": a["isu_id"],
            "isu": a["isu"],
            "sumber_isu": "klaster",
            "tanggal_awal": "2026-11-17",
            "tanggal_terakhir": "2026-11-17",
            "member_count": sum(1 for x in day1_arts if x["isu_id"] == a["isu_id"]),
            "member_count_at_eval": 0,
            "sample_titles": [x["title"] for x in day1_arts if x["isu_id"] == a["isu_id"]],
        }

    group_calls = []
    single_calls = []

    def fake_generate(prompt, timeout=60, max_attempts=6):
        if '"kelompok_id":' in prompt or "Berikut daftar isu" in prompt:
            # Parse batch payload
            m_arr = prompt.rsplit("):\n", 1)[1]
            items = json.loads(m_arr)
            group_calls.append(len(items))
            hasil = []
            for it in items:
                outs = [b["id"] for b in it["berita"] if b["id"] == 3]
                hasil.append({
                    "kelompok_id": it["kelompok_id"],
                    "alasan": f"Alasan grup {it['isu']}",
                    "outlier_ids": outs,
                    "keyakinan": "tinggi",
                    "tone": "Positif",
                })
            return json.dumps({"hasil": hasil}), "mock-gemini", ""
        else:
            single_calls.append(prompt)
            # Single-article format: kembalikan Negatif untuk tutup pabrik (id 3) dan Positif untuk id 12
            m_arr = prompt.rsplit("):\n", 1)[1]
            items = json.loads(m_arr)
            hasil = []
            for it in items:
                tn = "Negatif" if "Tutup Pabrik" in it["title"] else "Positif"
                hasil.append({"id": it["id"], "fokus": "B" if tn == "Negatif" else "C", "alasan": "Test single", "dasar": "judul", "tone": tn})
            return json.dumps({"hasil": hasil}), "mock-gemini", ""

    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_generate), patch("time.sleep"):
        res1 = tc.classify_tone_by_issue(
            day1_arts, registry=reg, use_ai=True, reeval_member_delta=3, print_mixed_report=False, combined_isu_tone=False
        )

    # Batch grup AI harus maksimal 4 isu per panggilan -> 5 isu = [4, 1]
    assert group_calls == [4, 1], f"Expected batch sizes [4, 1], got {group_calls}"
    # Single article calls: untuk size-1 (id=12) dan outlier (id=3)
    by_id = {r["id"]: r for r in res1}
    assert by_id[1]["tone"] == "Positif"
    assert by_id[2]["tone"] == "Positif"
    assert by_id[3]["tone"] == "Negatif" and by_id[3].get("is_outlier") is True
    assert by_id[12]["tone"] == "Positif"
    assert reg.issues["isu_B"]["tone"] == "Positif"
    assert reg.issues["isu_B"]["member_count_at_eval"] == 2
    assert reg.issues["isu_B"]["evaluated_at"]

    # Hari ke-2: 1 berita bergabung ke isu_B (total anggota 3, delta = 1 < 3) -> HARUS warisi tanpa API call!
    group_calls.clear()
    single_calls.clear()
    reg.issues["isu_B"]["member_count"] = 3
    day2_arts = [
        {"id": 21, "isu_id": "isu_B", "isu": "Isu B", "sumber_isu": "klaster", "title": "Berita B3 Lanjutan", "link": "https://x.com/b3"},
    ]
    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_generate), patch("time.sleep"):
        res2 = tc.classify_tone_by_issue(
            day2_arts, registry=reg, use_ai=True, reeval_member_delta=3, print_mixed_report=False, combined_isu_tone=False
        )

    assert len(group_calls) == 0 and len(single_calls) == 0
    assert res2[0]["tone"] == "Positif"
    assert res2[0]["metode"] == "inherited-isu"

    # Hari ke-3: Isu B sudah mendapat 3 anggota baru (member_count = 5, eval_at = 2 -> delta = 3 >= 3) -> WAJIB re-evaluasi API!
    reg.issues["isu_B"]["member_count"] = 5
    day3_arts = [
        {"id": 31, "isu_id": "isu_B", "isu": "Isu B", "sumber_isu": "klaster", "title": "Berita B5 Re-Evaluasi", "link": "https://x.com/b5"},
    ]
    with patch.object(tc._MODEL_POOL, "generate_deterministic", side_effect=fake_generate), patch("time.sleep"):
        res3 = tc.classify_tone_by_issue(
            day3_arts, registry=reg, use_ai=True, reeval_member_delta=3, print_mixed_report=False, combined_isu_tone=False
        )

    assert len(group_calls) == 1
    assert reg.issues["isu_B"]["member_count_at_eval"] == 5
    assert res3[0]["tone"] == "Positif"
    assert res3[0]["metode"] == "AI-isu"
