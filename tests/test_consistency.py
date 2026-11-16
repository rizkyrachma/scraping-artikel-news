"""
tests/test_consistency.py
Unit tests untuk memverifikasi keandalan dekoder tahan rate limit, cache, circuit breaker,
determinisme, filter non-berita, dan konsistensi Ringkasan Negatif.
Jalankan: python tests/test_consistency.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.extract_content import (
    AdaptiveDecodeController,
    DecodeCache,
    DecodeNegativeCache,
    fallback_url_from_metadata,
    is_valid_decoded_url,
    normalize_google_news_url,
    resolve_article_with_fallback,
    is_prefiltered_rss_item,
    DECODE_VALIDATOR_VERSION,
    fallback_url_from_search,
    get_search_quota_usage,
    reset_search_quota_usage,
    get_search_memo_status,
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
                    "title": "Kopi & Tarts Resto",
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

                # Saat GoogleDecoder mengembalikan google.com/sorry/index (rate-limit/CAPTCHA gate),
                # harus mencatat failure ke controller dan lanjut ke Layer 3 fallback (bukan crash)
                extract_content_mod._decoder_fn = lambda _u: {
                    "status": False,
                    "message": "https://www.google.com/sorry/index?continue=...",
                }
                cap_item = {
                    "title": "Industri Biodiesel Nasional Tumbuh Positif",
                    "link": "https://news.google.com/rss/articles/CBMiCAP999?oc=5",
                    "source_url": "https://ekonomi.bisnis.com",
                }
                r_cap = resolve_article_with_fallback(
                    cap_item,
                    allow_search_fallback=True,
                    cache=cache,
                    neg_cache=neg_cache,
                    controller=ctrl,
                    search_fallback_fn=lambda _it: (
                        "https://ekonomi.bisnis.com/read/20261111/257/1999/industri-biodiesel-nasional-tumbuh-positif",
                        "fallback_serper",
                        "",
                    ),
                )
                self.assertTrue(r_cap["resolved"])
                self.assertEqual(r_cap["method"], "fallback_serper")
                self.assertGreaterEqual(ctrl.snapshot()["rolling_failures"], 1)
                self.assertIs(pipeline_main.GoogleCaptchaBlockedError, extract_content_mod.GoogleCaptchaBlockedError)
            finally:
                extract_content_mod._decoder_fn = orig_decoder

    def test_no_dual_module_identities(self):
        """Memastikan semua modul intra-repo diimpor via 'src.<modul>' dan tidak ada modul ganda di sys.modules."""
        core_modules = [
            "config",
            "stable",
            "extract_content",
            "fetch_news",
            "relevance_filter",
            "gemini_pool",
            "negative_summarizer",
            "auto_recheck",
        ]
        for mod_name in core_modules:
            src_name = f"src.{mod_name}"
            self.assertIn(src_name, sys.modules, f"{src_name} harus ada di sys.modules")
            self.assertNotIn(
                mod_name,
                sys.modules,
                f"Duplikasi identitas modul terdeteksi: bare module '{mod_name}' ada di sys.modules bersama '{src_name}'",
            )

    def test_rejected_target_versioned_persistence_and_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            neg_path = os.path.join(td, "cache_decode_failed.json")
            cache_v1 = DecodeNegativeCache(filepath=neg_path, validator_version="v1")
            url = "https://news.google.com/rss/articles/CBMiREJECTED1"

            # 1. Simpan penolakan di v1
            cache_v1.mark_failed(url, reason="rejected_target")
            cache_v1.save(force=True)
            self.assertEqual(cache_v1.get_reason(url), "rejected_target")

            # Cek isi file json memuat key dengan versi validator v1
            with open(neg_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            matching_keys = [k for k in saved if "val_v1" in k]
            self.assertTrue(len(matching_keys) > 0)

            # 2. Muat dengan validator_version="v2": cache penolakan lama tidak boleh terpakai
            cache_v2 = DecodeNegativeCache(filepath=neg_path, validator_version="v2")
            self.assertIsNone(cache_v2.get_reason(url))

            # 3. Muat kembali dengan v1: masih terbaca
            cache_v1_again = DecodeNegativeCache(filepath=neg_path, validator_version="v1")
            self.assertEqual(cache_v1_again.get_reason(url), "rejected_target")

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
        pipeline_main._record_decode_stat(
            stats,
            {"link": "https://news.google.com/rss/articles/CBMi4"},
            {"decode_failed": True, "decode_method": "rejected_target", "text": ""},
        )
        pipeline_main._record_decode_stat(
            stats,
            {"link": "https://news.google.com/rss/articles/CBMi5"},
            {"decode_failed": True, "decode_method": "failed", "text": ""},
        )
        self.assertEqual(stats["extract_total"], 5)
        self.assertEqual(stats["extract_ok"], 1)
        self.assertEqual(stats["extract_short"], 1)
        self.assertEqual(stats["negative_cache_hit"], 1)
        self.assertEqual(stats["rejected_target"], 1)
        self.assertEqual(stats["decode_fail"], 1)
        # gnews_total=5, rejected_target=1 -> penyebut efektif = 4, pembilang = 1 (25.0%), bukan 1/5 atau 2/5
        num, denom, pct = pipeline_main.compute_decode_failure_rate(stats)
        self.assertEqual(num, 1)
        self.assertEqual(denom, 4)
        self.assertAlmostEqual(pct, 25.0)

    def test_prefiltered_rss_item_and_metric_exclusion(self):
        # 1. Judul Google Maps
        maps_item = {"title": "Pusat Kelapa Sawit - Google Maps", "link": "https://news.google.com/rss/articles/CBMiMAPS"}
        is_pre, reason = is_prefiltered_rss_item(maps_item)
        self.assertTrue(is_pre)
        self.assertIn("maps", reason)

        # 2. Source URL di blocklist loker atau google.com
        job_item = {
            "title": "Lowongan Staff Agro",
            "link": "https://news.google.com/rss/articles/CBMiJOB",
            "source_url": "https://glints.com/id/opportunities/jobs/123",
        }
        is_pre, reason = is_prefiltered_rss_item(job_item)
        self.assertTrue(is_pre)
        self.assertIn("job_portal", reason)

        g_item = {
            "title": "Lokasi Kebun",
            "link": "https://news.google.com/rss/articles/CBMiGLOC",
            "source_url": "https://maps.google.com/location/456",
        }
        is_pre, reason = is_prefiltered_rss_item(g_item)
        self.assertTrue(is_pre)
        self.assertIn("google", reason)

        # 3. Berita normal tidak boleh ter-prefilter (pastikan link news.google.com tidak salah dideteksi)
        normal_item = {
            "title": "Kemenperin Dorong Hilirisasi Minyak Sawit",
            "link": "https://news.google.com/rss/articles/CBMiOK",
            "source_url": "https://ekonomi.bisnis.com/read/123",
        }
        is_pre, reason = is_prefiltered_rss_item(normal_item)
        self.assertFalse(is_pre)

        # 3b. source_url www.google.com harus ter-prefilter, tetapi news.google.com pada link artikel tidak boleh memicu filter
        g_direct = {
            "title": "Google Search Info",
            "link": "https://news.google.com/rss/articles/CBMiGDIRECT",
            "source_url": "https://www.google.com/search?q=test",
        }
        is_pre_g, reason_g = is_prefiltered_rss_item(g_direct)
        self.assertTrue(is_pre_g)
        self.assertEqual(reason_g, "prefiltered_google_source")

        # 4. extract_one_article menolak langsung tanpa dekoder dan mencatat domain & sampel
        ext_res = pipeline_main.extract_one_article(maps_item)
        self.assertTrue(ext_res.get("decode_failed"))
        self.assertTrue(ext_res.get("skip_retry"))
        self.assertEqual(ext_res.get("decode_method"), "pre_filtered")
        self.assertIn("prefiltered_domain", ext_res)

        # 5. Metrik compute_decode_failure_rate mengeluarkan pre_filtered dari pembilang & penyebut
        stats = pipeline_main._init_decode_stats()
        # gnews_total = 2, 1 pre_filtered, 1 decode_fail
        pipeline_main._record_decode_stat(stats, maps_item, ext_res)
        pipeline_main._record_decode_stat(
            stats,
            {"link": "https://news.google.com/rss/articles/CBMiFAIL"},
            {"decode_failed": True, "decode_method": "failed", "text": ""},
        )
        self.assertEqual(stats["gnews_total"], 2)
        self.assertEqual(stats["pre_filtered"], 1)
        self.assertEqual(len(stats.get("prefiltered_samples", [])), 1)
        self.assertIn("maps", stats["prefiltered_samples"][0]["reason"])
        self.assertEqual(stats["decode_fail"], 1)
        num, denom, pct = pipeline_main.compute_decode_failure_rate(stats)
        # Denom = 2 - 1 = 1, Num = 1 -> 100% (bukan 1/2 = 50%)
        self.assertEqual(num, 1)
        self.assertEqual(denom, 1)
        self.assertAlmostEqual(pct, 100.0)

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

    def test_layer3_memo_three_states_and_layer4_retry_and_quota_caps(self):
        reset_search_quota_usage()
        orig_post = extract_content_mod.requests.post
        orig_serper_key = os.environ.get("SERPER_API_KEY")
        orig_exa_key = os.environ.get("EXA_API_KEY")
        orig_serp_max = extract_content_mod.MAX_SERPER_CALLS_PER_RUN
        orig_exa_max = extract_content_mod.MAX_EXA_CALLS_PER_RUN

        try:
            os.environ["SERPER_API_KEY"] = "fake-key"
            os.environ["EXA_API_KEY"] = "fake-key"
            extract_content_mod.MAX_SERPER_CALLS_PER_RUN = 2
            extract_content_mod.MAX_EXA_CALLS_PER_RUN = 2
            extract_content_mod._SERPER_EXHAUSTED = False
            extract_content_mod._EXA_EXHAUSTED = False

            # 1. State: SEARCHED_EMPTY (HTTP 200, 0 hits)
            class FakeResp200:
                status_code = 200
                def json(self): return {"organic": [], "results": []}

            extract_content_mod.requests.post = lambda *a, **kw: FakeResp200()
            item_empty = {
                "title": "Judul Kosong Tidak Ditemukan",
                "media_name": "Media Satu",
                "link": "https://news.google.com/rss/articles/CBMiEMPTY1",
            }
            res_empty = fallback_url_from_search(item_empty, bypass_memo=True)
            self.assertEqual(res_empty[3], "SEARCHED_EMPTY")
            self.assertEqual(get_search_memo_status(item_empty), "SEARCHED_EMPTY")

            # 2. State: TRANSIENT_FAIL (Network error/timeout)
            def fake_timeout(*a, **kw):
                raise extract_content_mod.requests.exceptions.Timeout("Timeout")
            extract_content_mod.requests.post = fake_timeout
            item_timeout = {
                "title": "Judul Mengalami Gangguan Jaringan",
                "media_name": "Media Dua",
                "link": "https://news.google.com/rss/articles/CBMiTIMEOUT2",
            }
            res_timeout = fallback_url_from_search(item_timeout, bypass_memo=True)
            self.assertEqual(res_timeout[3], "TRANSIENT_FAIL")
            self.assertEqual(get_search_memo_status(item_timeout), "TRANSIENT_FAIL")

            # 3. State: NOT_SEARCHED (Batas kuota habis)
            extract_content_mod._SERPER_CALL_COUNT = extract_content_mod.MAX_SERPER_CALLS_PER_RUN
            extract_content_mod._EXA_CALL_COUNT = extract_content_mod.MAX_EXA_CALLS_PER_RUN
            item_quota = {
                "title": "Judul Ketika Kuota Habis",
                "media_name": "Media Tiga",
                "link": "https://news.google.com/rss/articles/CBMiQUOTA3",
            }
            res_quota = fallback_url_from_search(item_quota, bypass_memo=True)
            self.assertEqual(res_quota[3], "NOT_SEARCHED")
            self.assertEqual(get_search_memo_status(item_quota), "NOT_SEARCHED")

            # Cek pemakaian kuota tidak bertambah saat limit tercapai dan flag alert aktif
            q_usage = get_search_quota_usage()
            self.assertEqual(q_usage["serper_calls"], 2)
            self.assertEqual(q_usage["exa_calls"], 2)
            self.assertTrue(q_usage["serper_limit_reached"])
            self.assertTrue(q_usage["exa_limit_reached"])

            # 4. Layer 4 verifikasi:
            # SEARCHED_EMPTY -> allow_search_fallback=False
            # TRANSIENT_FAIL & NOT_SEARCHED -> allow_search_fallback=True, bypass_search_memo=True
            l4_calls = []
            orig_extract = pipeline_main.extract_one_article
            orig_filter = pipeline_main.filter_valid_articles
            orig_sig = pipeline_main.get_kemenperin_signal
            orig_save = pipeline_main.save_decode_cache
            try:
                def fake_l4_extract(it, allow_search_fallback=True, bypass_search_memo=False, **kw):
                    l4_calls.append({
                        "link": it.get("link"),
                        "allow_search": allow_search_fallback,
                        "bypass_memo": bypass_search_memo,
                    })
                    return {"decode_failed": True, "decode_method": "failed", "link": it.get("link")}
                pipeline_main.extract_one_article = fake_l4_extract
                pipeline_main.filter_valid_articles = lambda items, **kw: ([], items)
                pipeline_main.get_kemenperin_signal = lambda *a: (False, "", "")
                pipeline_main.save_decode_cache = lambda *a, **kw: None

                pipeline_main.drain_retry_queue([item_empty, item_timeout, item_quota], name_map={})
                self.assertEqual(len(l4_calls), 3)
                call_empty = next(c for c in l4_calls if c["link"] == item_empty["link"])
                self.assertFalse(call_empty["allow_search"])
                self.assertFalse(call_empty["bypass_memo"])
                call_to = next(c for c in l4_calls if c["link"] == item_timeout["link"])
                self.assertTrue(call_to["allow_search"])
                self.assertTrue(call_to["bypass_memo"])
                call_q = next(c for c in l4_calls if c["link"] == item_quota["link"])
                self.assertTrue(call_q["allow_search"])
                self.assertTrue(call_q["bypass_memo"])
            finally:
                pipeline_main.extract_one_article = orig_extract
                pipeline_main.filter_valid_articles = orig_filter
                pipeline_main.get_kemenperin_signal = orig_sig
                pipeline_main.save_decode_cache = orig_save
        finally:
            extract_content_mod.requests.post = orig_post
            if orig_serper_key is not None:
                os.environ["SERPER_API_KEY"] = orig_serper_key
            else:
                os.environ.pop("SERPER_API_KEY", None)
            if orig_exa_key is not None:
                os.environ["EXA_API_KEY"] = orig_exa_key
            else:
                os.environ.pop("EXA_API_KEY", None)
            extract_content_mod.MAX_SERPER_CALLS_PER_RUN = orig_serp_max
            extract_content_mod.MAX_EXA_CALLS_PER_RUN = orig_exa_max
            reset_search_quota_usage()


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


class TestPointFMergeRuns(unittest.TestCase):
    def test_merge_runs_union_decision_cache_overwrite_protection_and_trailing_sumber_run(self):
        import pandas as pd
        from src.export_excel import BERITA_COLUMNS
        from src.stable import merge_runs_from_excel

        with tempfile.TemporaryDirectory() as tmpdir:
            base_xlsx = os.path.join(tmpdir, "all_2026-11-11_ringkasan.xlsx")
            other_xlsx = os.path.join(tmpdir, "gha_2026-11-11_ringkasan.xlsx")
            cache_path = os.path.join(tmpdir, "cache_decisions.json")

            dcache = DecisionCache(filepath=cache_path)
            dcache.set(
                "https://bisnis.com/artikel-a",
                "tone",
                "v2",
                "mock-model",
                {"id": 1, "tone": "Negatif", "dasar": "judul", "alasan": "Cache tone", "metode": "AI"},
            )
            dcache.set(
                "https://bisnis.com/artikel-a",
                "pass3_audit",
                "v2",
                "mock-model",
                {"id": 1, "status": "hilir", "alasan": "Tetap relevan hilir"},
            )
            dcache.save(force=True)

            base_recs = [
                {
                    "Tanggal": "2026-11-11 08:00:00",
                    "Title": "Artikel A Versi Lokal",
                    "Link Website": "https://bisnis.com/artikel-a",
                    "Media Name": "Bisnis Lokal",
                    "Tone": "Netral",  # Sengaja beda dengan DecisionCache ('Negatif')
                    "Spokesperson 1": "Putu Juli Ardika",
                    "Unit Eselon": "IA",
                    "Terkait Kemenperin": "Ya",
                    "Keywords": "sawit",
                    "Sumber Data": "RSS",
                },
                {
                    "Tanggal": "2026-11-11 09:00:00",
                    "Title": "Artikel B Hanya Lokal",
                    "Link Website": "https://kontan.co.id/artikel-b",
                    "Media Name": "Kontan",
                    "Tone": "Positif",
                    "Terkait Kemenperin": "Tidak",
                    "Keywords": "cpo",
                    "Sumber Data": "RSS",
                },
            ]
            other_recs = [
                {
                    "Tanggal": "2026-11-11 08:00:00",
                    "Title": "Artikel A Versi GHA",
                    "Link Website": "https://www.bisnis.com/artikel-a?utm_source=gha",
                    "Media Name": "Bisnis GHA",
                    "Tone": "Positif",  # Konflik dengan base & DecisionCache
                    "Terkait Kemenperin": "Tidak",
                    "Keywords": "hilirisasi sawit",
                    "Sumber Data": "RSS",
                },
                {
                    "Tanggal": "2026-11-11 10:00:00",
                    "Title": "Artikel C Negatif Dari GHA",
                    "Link Website": "https://kayonews.co.id/artikel-c",
                    "Media Name": "KayoNews",
                    "Tone": "Negatif",
                    "Terkait Kemenperin": "Tidak",
                    "Keywords": "karet",
                    "Sumber Data": "RSS",
                },
                {
                    "Tanggal": "2026-11-11 11:00:00",
                    "Title": "Laporan PDF Tahunan",
                    "Link Website": "https://example.go.id/laporan.pdf",
                    "Media Name": "Example",
                    "Tone": "Netral",
                    "Terkait Kemenperin": "Tidak",
                    "Keywords": "sawit",
                    "Sumber Data": "PDF",
                },
            ]
            other_neg = [
                {
                    "Tanggal": "2026-11-11 10:00:00",
                    "Title": "Artikel C Negatif Dari GHA",
                    "Link Website": "https://kayonews.co.id/artikel-c",
                    "Media Name": "KayoNews",
                    "Terkait Kemenperin": "Tidak",
                    "Isu Inti": "Harga karet melemah",
                    "Alasan Negatif": "Menekan industri karet",
                }
            ]

            save_to_excel(base_recs, base_xlsx, merge_existing=False)
            save_to_excel(other_recs, other_xlsx, merge_existing=False, negative_summaries=other_neg)
            orig_base_df = pd.read_excel(base_xlsx, sheet_name="Berita")
            self.assertEqual(len(orig_base_df), 2)

            # 1. Tanpa --overwrite: file lama TIDAK boleh ditimpa, konflik non-cache pertahankan data lama, Tone ikut DecisionCache
            res = merge_runs_from_excel(
                base_xlsx,
                other_xlsx,
                output_path=base_xlsx,
                overwrite=False,
                decision_cache=dcache,
            )
            self.assertNotEqual(res["output_path"], base_xlsx)
            self.assertTrue(os.path.exists(res["output_path"]))
            # Pastikan base_xlsx lama tetap 2 baris (tidak tertimpa)
            self.assertEqual(len(pd.read_excel(base_xlsx, sheet_name="Berita")), 2)

            df_m = pd.read_excel(res["output_path"], sheet_name="Berita")
            df_m_neg = pd.read_excel(res["output_path"], sheet_name="Ringkasan Negatif")
            self.assertEqual(list(df_m.columns[: len(BERITA_COLUMNS)]), list(BERITA_COLUMNS))
            self.assertEqual(df_m.columns[-1], "Sumber Run")
            self.assertEqual(len(df_m), 3)  # A + B + C (PDF gugur)

            row_a = df_m[df_m["Link Website"].astype(str).str.contains("artikel-a")].iloc[0]
            self.assertEqual(row_a["Title"], "Artikel A Versi Lokal")  # data lama dipertahankan
            self.assertEqual(row_a["Tone"], "Negatif")  # konflik pakai DecisionCache
            self.assertEqual(row_a["Sumber Run"], "lokal + merge_from")
            self.assertIn("sawit", str(row_a["Keywords"]).lower())
            self.assertIn("hilirisasi sawit", str(row_a["Keywords"]).lower())

            # Konsistensi 1:1 Ringkasan Negatif (Artikel A dari DecisionCache + Artikel C)
            self.assertEqual(len(df_m_neg), 2)

            # 2. Dengan --overwrite: boleh menimpa file target & field non-cache dari merge_from
            res_ow = merge_runs_from_excel(
                base_xlsx,
                other_xlsx,
                output_path=base_xlsx,
                overwrite=True,
                decision_cache=dcache,
            )
            self.assertEqual(res_ow["output_path"], base_xlsx)
            df_ow = pd.read_excel(base_xlsx, sheet_name="Berita")
            row_a_ow = df_ow[df_ow["Link Website"].astype(str).str.contains("artikel-a")].iloc[0]
            self.assertEqual(row_a_ow["Title"], "Artikel A Versi GHA")
            self.assertEqual(row_a_ow["Tone"], "Negatif")  # tetap dari DecisionCache

    def test_cli_help_exposes_merge_overwrite_publish_and_guard_blocks_data_export(self):
        import subprocess
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        proc = subprocess.run([sys.executable, main_py, "--help"], capture_output=True, text=True, check=True)
        self.assertIn("--merge-from", proc.stdout)
        self.assertIn("--overwrite", proc.stdout)
        self.assertIn("--publish", proc.stdout)

        # Pastikan data_export hanya dipanggil saat --publish=True
        with open(main_py, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("if not publish_flag:\n            return", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
