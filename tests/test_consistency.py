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
    fallback_url_from_metadata,
    is_valid_decoded_url,
    normalize_google_news_url,
    resolve_article_with_fallback,
)
from src.fetch_news import _extract_rss_metadata_urls
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
            # Paksa circuit breaker OPEN agar langsung menguji Layer 2 & Layer 3
            for _ in range(5):
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
            def fake_extract(item, allow_search_fallback=True):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
