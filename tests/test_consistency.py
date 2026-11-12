"""
tests/test_consistency.py
Unit tests untuk memverifikasi keandalan dekoder tahan rate limit, cache, circuit breaker,
determinisme, filter non-berita, dan konsistensi Ringkasan Negatif.
Jalankan: python tests/test_consistency.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from src.extract_content import (
    AdaptiveDecodeController,
    DecodeCache,
    DecodeNegativeCache,
    fallback_url_from_metadata,
    is_valid_decoded_url,
    normalize_google_news_url,
    resolve_article_with_fallback,
)
import src.extract_content as extract_content_mod
from src.fetch_news import _extract_rss_metadata_urls, dedup_by_link
from src.stable import (
    DateSnapshotStore,
    DecisionCache,
    canonical_url,
    union_articles_by_canonical_url,
)
from src.auto_recheck import AutoRecheckPipeline, apply_ragu_rubric, check_deterministic_rules
from src.direct_crawl_agro import fetch_with_retry
from src.export_excel import save_to_excel
from src.gemini_pool import GeminiModelPool, _is_eligible_text_model
from src.negative_summarizer import (
    _call_gemini_summary_batch,
    summarize_negative_articles,
    validate_and_repair_negative_summaries,
)
from src.relevance_filter import classify_non_news_evergreen, is_likely_relevant
import src.negative_summarizer as neg_sum_mod
import main as pipeline_main


class TestPointADecoderAndCircuitBreaker(unittest.TestCase):
    def test_decode_cache_persists_valid_urls_and_never_caches_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "cache_decode.json")
            cache = DecodeCache(filepath=cache_path)

            gnews_rss = "https://news.google.com/rss/articles/CBMiTEST123?oc=5"
            gnews_art = "https://news.google.com/articles/CBMiTEST123?hl=id&gl=ID"
            gnews_read = "https://news.google.com/read/CBMiTEST123"
            target_url = "https://ekonomi.bisnis.com/read/20261111/12/199999/industri-sawit-tumbuh"

            self.assertEqual(normalize_google_news_url(gnews_rss), normalize_google_news_url(gnews_art))
            self.assertEqual(normalize_google_news_url(gnews_rss), normalize_google_news_url(gnews_read))

            # Jangan pernah menyimpan kegagalan, homepage polos, atau link Google
            self.assertFalse(cache.set(gnews_rss, ""))
            self.assertFalse(cache.set(gnews_rss, gnews_art))
            self.assertFalse(cache.set(gnews_rss, "https://ekonomi.bisnis.com"))
            self.assertFalse(cache.set(gnews_rss, "https://ekonomi.bisnis.com/"))

            # Simpan URL artikel valid -> persisten di disk
            self.assertTrue(cache.set(gnews_rss, target_url))
            cache.save(force=True)
            self.assertTrue(os.path.exists(cache_path))

            reloaded = DecodeCache(filepath=cache_path)
            self.assertEqual(reloaded.size(), 1)
            self.assertEqual(reloaded.get(gnews_art), target_url)
            self.assertEqual(reloaded.get(gnews_read), target_url)

    def test_circuit_breaker_and_adaptive_concurrency(self):
        now = [100.0]
        sleeps = []

        def fake_time():
            return now[0]

        def fake_sleep(secs):
            sleeps.append(secs)
            now[0] += secs

        ctrl = AdaptiveDecodeController(
            window_size=20,
            failure_threshold=0.50,
            min_samples=5,
            base_interval=0.4,
            max_interval=4.0,
            backoff_base=1.0,
            backoff_max=8.0,
            circuit_pause=12.0,
            circuit_cooldown=60.0,
            base_workers=6,
            min_workers=1,
            time_fn=fake_time,
            sleep_fn=fake_sleep,
            jitter_fn=lambda a, b: 1.0,
        )

        # Awal sehat
        self.assertEqual(ctrl.state(), "CLOSED")
        self.assertEqual(ctrl.recommended_workers(6), 6)

        # Exponential backoff tanpa jitter acak
        self.assertAlmostEqual(ctrl.compute_backoff(0), 1.0)
        self.assertAlmostEqual(ctrl.compute_backoff(1), 2.0)
        self.assertAlmostEqual(ctrl.compute_backoff(2), 4.0)
        self.assertAlmostEqual(ctrl.compute_backoff(5), 8.0)

        # 3 sukses lalu kegagalan berturut-turut hingga >= 50% pada rolling window
        for _ in range(3):
            ctrl.record_success()
        self.assertEqual(ctrl.recommended_workers(6), 6)

        # Tambah 3 gagal -> 3/6 = 50% >= threshold -> trip circuit breaker
        tripped_flags = [ctrl.record_failure() for _ in range(3)]
        self.assertTrue(any(tripped_flags))
        self.assertEqual(ctrl.state(), "OPEN")
        self.assertEqual(ctrl.recommended_workers(6), 1)
        self.assertIn(12.0, sleeps)

        # Saat OPEN, request ke Google dilewati agar langsung pakai fallback
        allowed, mode = ctrl.acquire_google_slot()
        self.assertFalse(allowed)
        self.assertEqual(mode, "circuit_open")

        # Setelah cooldown lewat -> transisi ke HALF_OPEN dan izinkan 1 probe saja
        now[0] += 61.0
        self.assertEqual(ctrl.state(), "HALF_OPEN")
        allowed1, mode1 = ctrl.acquire_google_slot()
        self.assertTrue(allowed1)
        self.assertEqual(mode1, "half_open_probe")

        # Probe kedua paralel ditolak sampai hasil probe pertama masuk
        allowed2, mode2 = ctrl.acquire_google_slot()
        self.assertFalse(allowed2)
        self.assertEqual(mode2, "circuit_open")

        # Probe pertama gagal -> kembali OPEN (trip #2)
        ctrl.record_failure()
        self.assertEqual(ctrl.state(), "OPEN")
        self.assertEqual(ctrl.snapshot()["circuit_trips"], 2)

        # Cooldown kedua lewat -> probe sukses -> pulih ke CLOSED
        now[0] += 61.0
        allowed3, mode3 = ctrl.acquire_google_slot()
        self.assertTrue(allowed3)
        self.assertEqual(mode3, "half_open_probe")
        ctrl.record_success()
        self.assertEqual(ctrl.state(), "CLOSED")

    def test_layered_fallback_metadata_and_search_without_root_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DecodeCache(filepath=os.path.join(tmpdir, "cache.json"))
            ctrl = AdaptiveDecodeController(circuit_pause=0.0, sleep_fn=lambda _: None)
            # Paksa circuit breaker OPEN (>= min_samples default 10) agar langsung menguji Layer 2 & Layer 3
            for _ in range(10):
                ctrl.record_failure()
            self.assertEqual(ctrl.state(), "OPEN")

            # Layer 2 harus menolak root homepage source_url dan mengambil URL artikel di rss_metadata_urls
            item_meta = {
                "title": "Ekspor CPO Naik",
                "link": "https://news.google.com/rss/articles/CBMiMETA999?oc=5",
                "source_url": "https://ekonomi.bisnis.com",
                "rss_metadata_urls": [
                    "https://news.google.com/articles/IGNORE",
                    "https://ekonomi.bisnis.com/read/20261111/99/12345/ekspor-cpo-naik",
                ],
            }
            self.assertEqual(
                fallback_url_from_metadata(item_meta),
                "https://ekonomi.bisnis.com/read/20261111/99/12345/ekspor-cpo-naik",
            )
            res_meta = resolve_article_with_fallback(
                item_meta,
                allow_search_fallback=True,
                cache=cache,
                controller=ctrl,
                search_fallback_fn=lambda _: (None, "", ""),
            )
            self.assertTrue(res_meta["resolved"])
            self.assertEqual(res_meta["method"], "fallback_meta")
            self.assertEqual(
                cache.get(item_meta["link"]),
                "https://ekonomi.bisnis.com/read/20261111/99/12345/ekspor-cpo-naik",
            )

            # Layer 3 (mocked Exa/Serper) berjalan saat metadata hanya punya root domain
            item_search = {
                "title": "Biodiesel Fleksibel Jelang IPOC 2026",
                "link": "https://news.google.com/rss/articles/CBMiSEARCH888?oc=5",
                "source_url": "https://gapki.id",
                "media_name": "GAPKI",
            }
            self.assertIsNone(fallback_url_from_metadata(item_search))
            res_search = resolve_article_with_fallback(
                item_search,
                allow_search_fallback=True,
                cache=cache,
                controller=ctrl,
                search_fallback_fn=lambda _it: (
                    "https://gapki.id/news/2026/11/10/biodiesel-fleksibel-jelang-ipoc-2026/",
                    "fallback_serper",
                    "",
                ),
            )
            self.assertTrue(res_search["resolved"])
            self.assertEqual(res_search["method"], "fallback_serper")
            self.assertEqual(
                cache.get(item_search["link"]),
                "https://gapki.id/news/2026/11/10/biodiesel-fleksibel-jelang-ipoc-2026/",
            )

            # Jika semua lapis gagal -> tidak tersimpan ke cache dan siap antre retry
            item_fail = {
                "title": "Berita Tidak Ditemukan",
                "link": "https://news.google.com/rss/articles/CBMiFAIL777?oc=5",
                "source_url": "https://gapki.id",
            }
            res_fail = resolve_article_with_fallback(
                item_fail,
                allow_search_fallback=True,
                cache=cache,
                controller=ctrl,
                search_fallback_fn=lambda _it: (None, "", ""),
            )
            self.assertFalse(res_fail["resolved"])
            self.assertIsNone(cache.get(item_fail["link"]))

    def test_min_samples_ten_blocks_early_open_and_cache_hits_not_counted(self):
        ctrl = AdaptiveDecodeController(
            window_size=20,
            failure_threshold=0.50,
            circuit_pause=0.0,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(ctrl.min_samples, 10)

        # 3 gagal dari 3 request TIDAK boleh memicu circuit breaker OPEN
        for _ in range(3):
            tripped = ctrl.record_failure()
            self.assertFalse(tripped)
        self.assertEqual(ctrl.state(), "CLOSED")
        self.assertEqual(ctrl.snapshot()["circuit_trips"], 0)

        # Request yang dilayani cache tidak boleh masuk rolling window
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DecodeCache(filepath=os.path.join(tmpdir, "cache.json"))
            neg_cache = DecodeNegativeCache(filepath=os.path.join(tmpdir, "neg.json"))
            gurl = "https://news.google.com/rss/articles/CBMiCACHED1?oc=5"
            cache.set(gurl, "https://ekonomi.bisnis.com/read/20261111/1/999/sawit")
            for _ in range(10):
                res = resolve_article_with_fallback(
                    {"title": "Sawit Stabil", "link": gurl},
                    cache=cache,
                    neg_cache=neg_cache,
                    controller=ctrl,
                )
                self.assertEqual(res["method"], "cache")
            self.assertEqual(ctrl.snapshot()["rolling_window_size"], 3)

        # L4 retry dengan allow_circuit_trip=False juga tidak boleh memicu OPEN meski sampel kecil
        ctrl_l4 = AdaptiveDecodeController(circuit_pause=0.0, sleep_fn=lambda _: None)
        ctrl_l4.reset_for_retry_pass()
        for _ in range(12):
            self.assertFalse(ctrl_l4.record_failure(allow_trip=False))
        self.assertEqual(ctrl_l4.state(), "CLOSED")
        self.assertEqual(ctrl_l4.snapshot()["circuit_trips"], 0)

        # Kasus 12 gagal dari 20 request (8 sukses + 12 gagal = 60% >= 50%) HARUS OPEN
        ctrl_20 = AdaptiveDecodeController(window_size=20, failure_threshold=0.50, min_samples=10, circuit_pause=0.0, sleep_fn=lambda _: None)
        for _ in range(8):
            ctrl_20.record_success()
        tripped_list = [ctrl_20.record_failure() for _ in range(12)]
        self.assertTrue(any(tripped_list))
        self.assertEqual(ctrl_20.state(), "OPEN")

    def test_negative_cache_ttl_and_rejected_target_save_search_quota(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DecodeCache(filepath=os.path.join(tmpdir, "cache.json"))
            neg_cache = DecodeNegativeCache(
                filepath=os.path.join(tmpdir, "neg_cache.json"),
                ttl_seconds=6 * 3600,
                time_fn=lambda: now[0],
            )
            ctrl = AdaptiveDecodeController(circuit_pause=0.0, sleep_fn=lambda _: None)
            search_calls = [0]

            def fake_search(_it):
                search_calls[0] += 1
                return (None, "", "")

            orig_decoder = extract_content_mod._decoder_fn
            try:
                extract_content_mod._decoder_fn = lambda _u: {"status": False, "message": "429"}
                dead_item = {
                    "title": "Berita Gagal Permanen Untuk Uji Negative Cache",
                    "link": "https://news.google.com/rss/articles/CBMiDEAD1?oc=5",
                    "source_url": "https://ekonomi.bisnis.com",
                }
                r1 = resolve_article_with_fallback(
                    dead_item,
                    allow_search_fallback=True,
                    max_retries=0,
                    cache=cache,
                    neg_cache=neg_cache,
                    controller=ctrl,
                    search_fallback_fn=fake_search,
                )
                self.assertFalse(r1["resolved"])
                self.assertEqual(search_calls[0], 1)
                self.assertIsNone(cache.get(dead_item["link"]))
                self.assertTrue(neg_cache.is_failed(dead_item["link"]))

                # Run ulang < 6 jam: langsung terlayani negative_cache, nol panggilan Serper/Exa
                now[0] += 3600.0
                r2 = resolve_article_with_fallback(
                    dead_item,
                    allow_search_fallback=True,
                    max_retries=0,
                    cache=cache,
                    neg_cache=neg_cache,
                    controller=ctrl,
                    search_fallback_fn=fake_search,
                )
                self.assertEqual(r2["method"], "negative_cache")
                self.assertEqual(search_calls[0], 1)

                # Setelah > 6 jam: TTL kedaluwarsa, fallback search dipanggil lagi
                now[0] += (6 * 3600.0) + 1.0
                resolve_article_with_fallback(
                    dead_item,
                    allow_search_fallback=True,
                    max_retries=0,
                    cache=cache,
                    neg_cache=neg_cache,
                    controller=ctrl,
                    search_fallback_fn=fake_search,
                )
                self.assertEqual(search_calls[0], 2)

                # Tujuan non-artikel (misal Google Maps) dari GoogleDecoder harus ditandai rejected_target
                # tanpa membakar kuota search dan tanpa memicu circuit breaker
                extract_content_mod._decoder_fn = lambda _u: {
                    "status": True,
                    "decoded_url": "https://www.google.com/maps/search/?api=1&query=Kopi+Tarts",
                }
                maps_item = {
                    "title": "Kopi & Tarts - Google Maps",
                    "link": "https://news.google.com/rss/articles/CBMiMAPS1?oc=5",
                }
                r_maps = resolve_article_with_fallback(
                    maps_item,
                    allow_search_fallback=True,
                    cache=cache,
                    neg_cache=neg_cache,
                    controller=ctrl,
                    search_fallback_fn=fake_search,
                )
                self.assertFalse(r_maps["resolved"])
                self.assertEqual(r_maps["method"], "rejected_target")
                self.assertEqual(search_calls[0], 2)
                self.assertEqual(ctrl.snapshot()["circuit_trips"], 0)
            finally:
                extract_content_mod._decoder_fn = orig_decoder

    def test_decode_stats_track_extraction_length_separately(self):
        stats = pipeline_main._init_decode_stats()
        pipeline_main._record_decode_stat(
            stats,
            {"link": "https://news.google.com/rss/articles/CBMi1"},
            {"decode_failed": False, "decode_method": "decode_local", "text": "A" * 350},
        )
        pipeline_main._record_decode_stat(
            stats,
            {"link": "https://news.google.com/rss/articles/CBMi2"},
            {"decode_failed": False, "decode_method": "decode_local", "text": "Pendek"},
        )
        pipeline_main._record_decode_stat(
            stats,
            {"link": "https://news.google.com/rss/articles/CBMi3"},
            {"decode_failed": True, "decode_method": "negative_cache", "text": ""},
        )
        self.assertEqual(stats["extract_total"], 3)
        self.assertEqual(stats["extract_ok"], 1)
        self.assertEqual(stats["extract_short"], 1)
        self.assertEqual(stats["negative_cache_hit"], 1)
        self.assertEqual(stats["decode_fail"], 0)

    def test_rss_metadata_extraction_ignores_google_and_root_links(self):
        fake_entry = {
            "links": [
                {"href": "https://news.google.com/rss/articles/CBMiABC"},
                {"href": "https://kontan.co.id"},
                {"href": "https://industri.kontan.co.id/news/pabrik-kakao-ekspansi"},
            ],
            "summary": '<a href="https://news.google.com/x">G</a> <a href="https://kemenperin.go.id/artikel/1234/agro">K</a>',
        }
        urls = _extract_rss_metadata_urls(fake_entry)
        self.assertEqual(
            urls,
            [
                "https://industri.kontan.co.id/news/pabrik-kakao-ekspansi",
                "https://kemenperin.go.id/artikel/1234/agro",
            ],
        )

    def test_retry_queue_merge_dedup_keywords(self):
        q1 = [{"link": "https://news.google.com/rss/articles/CBMiQ1?oc=5", "keyword": "cpo", "title": "A"}]
        q2 = [{"link": "https://news.google.com/articles/CBMiQ1", "keyword": "biodiesel", "title": "A"}]
        merged = pipeline_main._merge_retry_items(q1, q2)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["keyword"], "cpo, biodiesel")

    def test_drain_retry_queue_recovers_and_tracks_remaining_failures(self):
        orig_extract = pipeline_main.extract_one_article
        orig_filter = pipeline_main.filter_valid_articles
        orig_sig = pipeline_main.get_kemenperin_signal
        orig_save = pipeline_main.save_decode_cache
        try:
            def fake_extract(item, allow_search_fallback=True, **_kwargs):
                it = dict(item)
                if "CBMiOK" in it["link"]:
                    it["link"] = "https://ekonomi.bisnis.com/read/20261111/1/ok"
                    it["resolved_url"] = it["link"]
                    it["text"] = "Industri sawit nasional memperkuat hilirisasi minyak sawit dan CPO bersama Kemenperin di Jakarta. " * 5
                    it["decode_failed"] = False
                    it["decode_method"] = "fallback_serper"
                else:
                    it["decode_failed"] = True
                    it["decode_method"] = "failed"
                return it

            pipeline_main.extract_one_article = fake_extract
            pipeline_main.filter_valid_articles = lambda items, min_length=300, default_keyword=None: (items, [])
            pipeline_main.get_kemenperin_signal = lambda t, tx, nm: (True, "eksplisit", "kemenperin")
            pipeline_main.save_decode_cache = lambda force=False: None

            retry_q = [
                {"link": "https://news.google.com/rss/articles/CBMiOK?oc=5", "keyword": "cpo", "title": "Industri Sawit Tumbuh"},
                {"link": "https://news.google.com/rss/articles/CBMiBAD?oc=5", "keyword": "fame", "title": "Gagal Permanen"},
            ]
            valid, still_failed, summary = pipeline_main.drain_retry_queue(retry_q, name_map={})
            self.assertEqual(summary["queued"], 2)
            self.assertEqual(summary["recovered_urls"], 1)
            self.assertEqual(summary["valid_articles"], 1)
            self.assertEqual(summary["still_failed"], 1)
            self.assertEqual(len(valid), 1)
            self.assertEqual(valid[0]["terkait_kemenperin"], "Ya")
            self.assertEqual(len(still_failed), 1)
        finally:
            pipeline_main.extract_one_article = orig_extract
            pipeline_main.filter_valid_articles = orig_filter
            pipeline_main.get_kemenperin_signal = orig_sig
            pipeline_main.save_decode_cache = orig_save


class TestPointBDeterminismAndSnapshot(unittest.TestCase):
    def test_canonical_url_and_dedup_strip_tracking_and_wrappers(self):
        u1 = '=HYPERLINK("http://www.ekonomi.bisnis.com/read/20261111/1/cpo/?utm_source=google&fbclid=XYZ&b=2&a=1", "Buka")'
        u2 = "https://ekonomi.bisnis.com/read/20261111/1/cpo?a=1&b=2&gclid=999"
        self.assertEqual(canonical_url(u1), canonical_url(u2))
        self.assertEqual(canonical_url(u1), "https://ekonomi.bisnis.com/read/20261111/1/cpo?a=1&b=2")

        ded = dedup_by_link([
            {"link": u1, "keyword": "cpo", "title": "Ekspor CPO", "text": "Pendek"},
            {"link": u2, "keyword": "biodiesel", "title": "Ekspor CPO", "text": "Teks jauh lebih panjang dan lengkap " * 5},
        ])
        self.assertEqual(len(ded), 1)
        self.assertEqual(ded[0]["keyword"], "cpo, biodiesel")

    def test_decision_cache_versions_prompt_model_and_bounds_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache_decisions.json")
            now = [500.0]
            dc = DecisionCache(filepath=path, max_entries=100, time_fn=lambda: now[0])
            url = "https://industri.kontan.co.id/news/pabrik-gula-baru?utm_medium=rss"
            dc.set(url, "tone", "v2026-11-12-b", "gemini-2.5-flash", {"tone": "Positif"})
            dc.save(force=True)

            reloaded = DecisionCache(filepath=path, max_entries=100)
            self.assertEqual(
                reloaded.get("http://www.industri.kontan.co.id/news/pabrik-gula-baru/", "tone", "v2026-11-12-b", "gemini-2.5-flash"),
                {"tone": "Positif"},
            )
            # Berubah versi prompt atau model -> wajib cache miss
            self.assertIsNone(reloaded.get(url, "tone", "v2026-11-13-new", "gemini-2.5-flash"))
            self.assertIsNone(reloaded.get(url, "tone", "v2026-11-12-b", "gemini-2.5-flash-lite"))

            # Verifikasi pemangkasan batas maksimum entri
            for i in range(115):
                now[0] += 1.0
                reloaded.set(f"https://example.com/berita/{i}", "tone", "v1", "m1", {"tone": "Netral"})
            self.assertEqual(reloaded.size(), 100)

    def test_snapshot_store_unions_runs_and_prunes_over_30_days(self):
        from datetime import date

        with tempfile.TemporaryDirectory() as tmpdir:
            today_ref = date(2026, 11, 12)
            store = DateSnapshotStore(snapshot_dir=tmpdir, retention_days=30, today_fn=lambda: today_ref)

            # Buat snapshot lama (>30 hari) dan snapshot masih dalam jendela (<30 hari)
            with open(os.path.join(tmpdir, "2026-10-01.json"), "w", encoding="utf-8") as f:
                f.write('{"articles":[]}')
            with open(os.path.join(tmpdir, "2026-11-01.json"), "w", encoding="utf-8") as f:
                f.write('{"articles":[]}')

            run1 = [
                {"link": "https://bisnis.com/a1?utm_source=x", "title": "Pabrik CPO Ekspansi", "published": "2026-11-11 04:00:00", "keyword": "cpo", "text": "Teks CPO " * 60},
                {"link": "https://kontan.co.id/a2", "title": "Industri AMDK Tumbuh", "published": "2026-11-11 05:00:00", "keyword": "amdk", "text": "Teks AMDK " * 60},
            ]
            run2 = [
                {"link": "https://kontan.co.id/a2/", "title": "Industri AMDK Tumbuh", "published": "2026-11-11 08:00:00", "keyword": "mamin", "text": "Teks AMDK " * 60},
                {"link": "https://cnbc.com/a3", "title": "Ekspor Kakao Naik", "published": "2026-11-11 08:15:00", "keyword": "kakao", "text": "Teks Kakao " * 60},
            ]

            merged_r1 = store.merge_range_with_snapshots(date(2026, 11, 11), date(2026, 11, 11), run1)
            self.assertEqual(len(merged_r1), 2)

            merged_r2 = store.merge_range_with_snapshots(date(2026, 11, 11), date(2026, 11, 11), run2)
            self.assertEqual(len(merged_r2), 3)
            # Snapshot > 30 hari otomatis terhapus
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "2026-10-01.json")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "2026-11-01.json")))

    def test_ragu_rubric_and_yellow_review_row_preserved_in_excel(self):
        import openpyxl

        # 1. Kemenperin / Asosiasi -> HILIR
        lbl1, _ = apply_ragu_rubric(
            {"title": "Cukai Rokok Jadi Sorotan WHO, APVI dan Kemenperin Bahas Dampak IHT", "text": "Industri hasil tembakau."},
            "RAGU",
        )
        self.assertEqual(lbl1, "HILIR")

        # 2. Murni opini akademisi / WHO tanpa respons industri -> BUKAN_HILIR
        lbl2, _ = apply_ragu_rubric(
            {"title": "Pengamat Ekonomi Soroti Isu Kesehatan Rokok Menurut Laporan WHO", "text": "Dosen universitas menilai konsumsi rokok global."},
            "RAGU",
        )
        self.assertEqual(lbl2, "BUKAN_HILIR")

        # 3. Masih borderline setelah rubrik -> tetap RAGU -> di auto_recheck jadi review kuning dan TIDAK di-drop di Excel
        lbl3, _ = apply_ragu_rubric(
            {"title": "Dinamika Pasar Komoditas Spesial Triwulan IV", "text": "Pergerakan pasokan dan permintaan regional mengalami fluktuasi terbatas."},
            "RAGU",
        )
        self.assertEqual(lbl3, "RAGU")

        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = AutoRecheckPipeline(target_dir=tmpdir)
            # Bypass Pass 2 & Audit AI agar deterministik di unit test
            pipe.run_pass_2_ai = lambda arts, batch_size=15: (arts, [])
            pipe.run_audit_loop = lambda arts, max_audit_passes=4, batch_size=15: (
                [dict(a, _final_label="RAGU", _final_alasan="Topik perbatasan butuh cek manual") for a in arts],
                [],
                {},
            )
            kept, _disc = pipe.run(
                [
                    {
                        "title": "Dinamika Pasar Komoditas Spesial Triwulan IV",
                        "link": "https://bisnis.com/borderline-1",
                        "published": "2026-11-11 10:00:00",
                        "text": "Pasokan dan permintaan komoditas spesialis tercatat berubah di kuartal ini. " * 6,
                    }
                ],
                target_dir=tmpdir,
            )
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]["status"], "review")
            self.assertIn("PERLU CEK MANUAL", kept[0]["Status Review"])

            xlsx_path = os.path.join(tmpdir, "out_review.xlsx")
            save_to_excel(
                kept + [{"title": "Dibuang", "link": "https://x.com/drop", "status": "buang", "published": "2026-11-11 10:00:00"}],
                xlsx_path,
                merge_existing=False,
            )
            wb = openpyxl.load_workbook(xlsx_path)
            ws = wb["Berita"]
            self.assertEqual(ws.max_row, 2)  # 1 header + 1 baris review ("buang" tereliminasi)
            # Pastikan baris review berwarna kuning (FFFF00)
            fill_rgb = str(ws.cell(row=2, column=1).fill.start_color.rgb or "")
            self.assertTrue(fill_rgb.endswith("FFFF00"))

    def test_gemini_pool_filters_non_text_models_uses_temp_zero_and_rotates_on_404(self):
        self.assertTrue(_is_eligible_text_model("gemini-2.5-flash", ["generateContent"]))
        self.assertFalse(_is_eligible_text_model("gemini-2.5-flash-tts", ["generateContent"]))
        self.assertFalse(_is_eligible_text_model("gemini-2.5-flash-image", ["generateContent"]))
        self.assertFalse(_is_eligible_text_model("gemma-3-27b-it", ["generateContent"]))

        captured_configs = []

        class FakeModel404:
            def generate_content(self, prompt, generation_config=None, request_options=None):
                captured_configs.append(("m404", generation_config))
                raise RuntimeError("404 models/fake-404 is not found")

        class FakeModelOK:
            def generate_content(self, prompt, generation_config=None, request_options=None):
                captured_configs.append(("mOK", generation_config))

                class Resp:
                    text = '[{"id": 1, "tone": "Netral"}]'

                return Resp()

        pool = GeminiModelPool("TEST")
        pool._models = ["fake-404", "fake-ok"]
        pool._instances = {"fake-404": FakeModel404(), "fake-ok": FakeModelOK()}
        prev_key = os.environ.get("GEMINI_API_KEY")
        try:
            os.environ["GEMINI_API_KEY"] = "dummy-test-key"
            text, used_model, err = pool.generate_deterministic("test prompt", max_attempts=3)
            self.assertEqual(used_model, "fake-ok")
            self.assertEqual(err, "")
            self.assertIn("Netral", text or "")
            for _, cfg in captured_configs:
                self.assertEqual(cfg, {"temperature": 0})
        finally:
            if prev_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = prev_key


class TestPointCNonNewsEvergreenFilter(unittest.TestCase):
    def test_drops_gha_leaked_glossary_vendor_and_evergreen_via_single_codepath(self):
        leaks = [
            ("Apa Itu Crude Glycerin?", "https://gapki.id/news/apa-itu-crude-glycerin", "glosarium bahan kimia turunan."),
            ("Apa Itu Stearic Acid 1840?", "https://gapki.id/news/apa-itu-stearic-acid-1840", "pengertian dan sifat stearic acid."),
            ("Pengolahan Limbah Cair POME", "https://asahifibreglass.com/pengolahan-limbah-cair-pome/", "Hubungi kami untuk konsultasi sistem FRP."),
            ("Kisah Supermi Sedaaap", "https://example.com/lifestyle/kisah-supermi-sedaaap", "Sejarah panjang merek mie instan."),
        ]
        for title, url, text in leaks:
            flagged, reason = classify_non_news_evergreen(title=title, text=text, url=url)
            self.assertTrue(flagged, f"Harusnya terdeteksi non-berita: {title}")
            self.assertTrue(bool(reason))
            self.assertFalse(is_likely_relevant(title), f"is_likely_relevant harus menolak: {title}")
            recheck_reason = check_deterministic_rules({"title": title, "link": url, "text": text})
            self.assertIsNotNone(recheck_reason, f"auto_recheck harus menolak via codepath sama: {title}")

        # Verifikasi main.filter_valid_articles membuang semua item tersebut dengan alasan tercatat
        arts = [
            {"title": t, "link": u, "text": txt + (" kata tambahan " * 30), "published": "2026-11-11 10:00:00"}
            for t, u, txt in leaks
        ]
        valid, discarded = pipeline_main.filter_valid_articles(arts, min_length=50)
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(discarded), len(leaks))
        for d in discarded:
            self.assertIn("non_news_evergreen", d.get("discard_reason", ""))

    def test_keeps_real_industry_news_containing_similar_terms(self):
        real_news = [
            ("Kemenperin Resmikan Pabrik Biogas Pengolahan Limbah Cair POME", "https://ekonomi.bisnis.com/read/20261111/1/pome", "Kementerian Perindustrian mendorong hilirisasi industri sawit."),
            ("Kisah Sukses Ekspor Kopi Olahan Dorong Devisa Industri Nasional", "https://industri.kontan.co.id/news/ekspor-kopi", "Ekspor produk olahan kopi nasional meningkat tajam."),
            ("Kemenperin Siapkan Regulasi Pengolahan Limbah POME Terpadu", "https://agro.kemenperin.go.id/berita/123", "Rilis resmi Ditjen Industri Agro."),
        ]
        for title, url, text in real_news:
            flagged, reason = classify_non_news_evergreen(title=title, text=text, url=url)
            self.assertFalse(flagged, f"Berita nyata tidak boleh terbuang: {title} ({reason})")
            self.assertTrue(is_likely_relevant(title))


class TestPointDInfrastructureResilience(unittest.TestCase):
    def test_direct_crawl_dns_retry_recovers_with_exponential_backoff(self):
        import requests

        attempts = [0]
        sleeps = []

        def flaky_dns_get(url, headers=None, verify=False, timeout=20):
            attempts[0] += 1
            if attempts[0] < 4:
                raise requests.ConnectionError("Failed to resolve 'agro.kemenperin.go.id' ([Errno 11001] getaddrinfo failed)")

            class OkResp:
                status_code = 200
                text = "<html><body>OK</body></html>"

            return OkResp()

        html = fetch_with_retry(
            "https://agro.kemenperin.go.id/berita",
            max_retries=5,
            timeout=10,
            get_fn=flaky_dns_get,
            sleep_fn=lambda s: sleeps.append(s),
            jitter_fn=lambda a, b: 0.2,
        )
        self.assertEqual(attempts[0], 4)
        self.assertEqual(html, "<html><body>OK</body></html>")
        self.assertEqual(len(sleeps), 3)
        # Exponential backoff meningkat (1.7, 3.2, 6.2)
        self.assertLess(sleeps[0], sleeps[1])
        self.assertLess(sleeps[1], sleeps[2])

    def test_gemini_pool_recovers_batch1_from_404_and_timeout_to_fallback_model(self):
        class Model404:
            def generate_content(self, prompt, generation_config=None, request_options=None):
                raise RuntimeError("404 NotFound model")

        class ModelTimeout:
            def generate_content(self, prompt, generation_config=None, request_options=None):
                raise TimeoutError("Request timed out after 45s")

        class ModelWorking:
            def generate_content(self, prompt, generation_config=None, request_options=None):
                class Resp:
                    text = '{"hasil": [{"id": 1, "status": "relevan", "sub_sektor": "Mamin", "alasan": "Ok"}], "dibuang": []}'

                return Resp()

        pool = GeminiModelPool("BATCH1_TEST")
        pool._models = ["m-404", "m-timeout", "m-ok"]
        pool._instances = {"m-404": Model404(), "m-timeout": ModelTimeout(), "m-ok": ModelWorking()}

        import src.gemini_pool as gp_mod

        orig_sleep = gp_mod.time.sleep
        prev_key = os.environ.get("GEMINI_API_KEY")
        try:
            gp_mod.time.sleep = lambda _s: None
            os.environ["GEMINI_API_KEY"] = "dummy-test-key"
            resp_text, used_model, err = pool.generate_deterministic("batch 1 prompt", max_attempts=3)
            self.assertEqual(used_model, "m-ok")
            self.assertEqual(err, "")
            self.assertIn('"relevan"', resp_text or "")
        finally:
            gp_mod.time.sleep = orig_sleep
            if prev_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = prev_key


class TestPointENegativeSummaryConsistency(unittest.TestCase):
    def test_reproduces_missing_kayonews_item_retries_per_item_and_guarantees_1_to_1_in_excel(self):
        import pandas as pd

        records = [
            {
                "Tanggal": "2026-11-11 08:00:00",
                "Title": "Berita Negatif Satu",
                "Link Website": "https://bisnis.com/neg-1",
                "Media Name": "Bisnis.com",
                "Tone": "Negatif",
                "Terkait Kemenperin": "Tidak",
            },
            {
                "Tanggal": "2026-11-11 09:00:00",
                "Title": "Harga Karet Tertekan di Pasar Regional",
                "Link Website": "https://kayonews.co.id/artikel/karet-tertekan?utm_source=rss",
                "Media Name": "KayoNews",
                "Tone": "Negatif",
                "Terkait Kemenperin": "Tidak",
            },
            {
                "Tanggal": "2026-11-11 10:00:00",
                "Title": "Berita Netral",
                "Link Website": "https://kontan.co.id/netral-1",
                "Media Name": "Kontan",
                "Tone": "Netral",
                "Terkait Kemenperin": "Tidak",
            },
        ]

        # Kasus 1: Batch AI hanya mengembalikan ID 1 (ID 2 kayonews terlewat), namun per-item retry berhasil
        calls = []

        class PartialThenSinglePool:
            quota_exhausted = False

            def peek_active_model_name(self):
                return "mock-gemini"

            def generate_deterministic(self, prompt, timeout=60, max_attempts=6):
                calls.append(prompt)
                if len(calls) == 1:
                    # Simulasikan batch hanya mengembalikan ID 1 dan meninggalkan kayonews (ID 2)
                    return (
                        '{"hasil": [{"id": 1, "isu_inti": "Isu 1", "alasan_negatif": "Neg 1", "tone_valid": true, "catatan_tone": "", "w5h1": {"what": "Isu 1", "who": "Pelaku", "when": "2026-11-11", "where": "RI", "why": "Turun", "how": "Lesu"}, "stakeholder": []}]}',
                        "mock-gemini",
                        "",
                    )
                # Panggilan ke-2 adalah single-item retry untuk kayonews
                return (
                    '{"hasil": [{"id": 2, "isu_inti": "Karet Tertekan", "alasan_negatif": "Harga karet melemah", "tone_valid": true, "catatan_tone": "", "w5h1": {"what": "Harga karet", "who": "Industri karet", "when": "2026-11-11", "where": "RI", "why": "Lesu", "how": "Tertekan"}, "stakeholder": []}]}',
                    "mock-gemini",
                    "",
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_pool = neg_sum_mod._MODEL_POOL
            orig_cache = neg_sum_mod.CACHE_FILE
            orig_log = neg_sum_mod.LOG_FILE
            orig_q = neg_sum_mod.ANTREAN_FILE
            orig_extract = neg_sum_mod.extract_article_text
            prev_key = os.environ.get("GEMINI_API_KEY")
            try:
                neg_sum_mod._MODEL_POOL = PartialThenSinglePool()
                neg_sum_mod.gemini_quota_exhausted = False
                neg_sum_mod.CACHE_FILE = os.path.join(tmpdir, "cache_ringkasan.json")
                neg_sum_mod.LOG_FILE = os.path.join(tmpdir, "log_ringkasan.jsonl")
                neg_sum_mod.ANTREAN_FILE = os.path.join(tmpdir, "antrean_ringkasan.json")
                neg_sum_mod.extract_article_text = lambda url, max_length=6000: (
                    f"Artikel simulasi untuk {url} mengenai industri karet dan sawit nasional. " * 10
                )
                os.environ["GEMINI_API_KEY"] = "dummy-key"

                neg_rows = summarize_negative_articles(records, delay_between_batches=0.0)
                repaired = validate_and_repair_negative_summaries(records, neg_rows)
                self.assertEqual(len(repaired), 2)
                self.assertEqual(len(calls), 2)  # 1 batch + 1 per-item retry

                # Kasus 2: Artikel tanpa cache + model gagal total -> placeholder ditulis & TIDAK dibuang oleh export_excel
                neg_sum_mod.CACHE_FILE = os.path.join(tmpdir, "cache_ringkasan_fail.json")
                neg_sum_mod._MODEL_POOL = type(
                    "AlwaysFailPool",
                    (),
                    {
                        "quota_exhausted": False,
                        "peek_active_model_name": staticmethod(lambda: "mock-fail"),
                        "generate_deterministic": staticmethod(lambda *a, **kw: (None, "mock-fail", "503")),
                    },
                )()
                failed_rows = summarize_negative_articles(
                    [records[1]],  # kayonews tanpa cache di cache_ringkasan_fail.json
                    delay_between_batches=0.0,
                )
                self.assertEqual(len(failed_rows), 1)
                self.assertIn("PLACEHOLDER", failed_rows[0]["Isu Inti"])

                xlsx_path = os.path.join(tmpdir, "konsistensi_neg.xlsx")
                # Simulasikan juga saat 1 baris negatif hilang dari df_neg -> export_excel wajib tambal 1:1
                save_to_excel(records, xlsx_path, merge_existing=False, negative_summaries=[failed_rows[0]])
                df_b = pd.read_excel(xlsx_path, sheet_name="Berita")
                df_n = pd.read_excel(xlsx_path, sheet_name="Ringkasan Negatif")
                neg_b_count = int((df_b["Tone"].astype(str).str.lower() == "negatif").sum())
                self.assertEqual(neg_b_count, 2)
                self.assertEqual(len(df_n), neg_b_count)
                self.assertTrue(any("kayonews" in str(u) for u in df_n["Link Website"].tolist()))
            finally:
                neg_sum_mod._MODEL_POOL = orig_pool
                neg_sum_mod.CACHE_FILE = orig_cache
                neg_sum_mod.LOG_FILE = orig_log
                neg_sum_mod.ANTREAN_FILE = orig_q
                neg_sum_mod.extract_article_text = orig_extract
                neg_sum_mod.gemini_quota_exhausted = False
                if prev_key is None:
                    os.environ.pop("GEMINI_API_KEY", None)
                else:
                    os.environ["GEMINI_API_KEY"] = prev_key


if __name__ == "__main__":
    unittest.main(verbosity=2)
