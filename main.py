"""
main.py
Orkestrasi pipeline scraping berita industri end-to-end:
1. Load dataset kata kunci & mapping pejabat
2. Fetch & filter domain berita (Google News RSS + .go.id)
3. Ekstraksi konten teks (trafilatura + fallback newspaper3k) dengan resolusi URL asli
4. Filter noise & relevansi:
   - Kosong & suspiciously short (< 300 chars)
   - Frekuensi topik utama (is_keyword_primary_topic)
   - Resep kuliner (is_recipe)
   - Iklan / promosi ritel (is_promotional)
   - Sinyal industri vs kesehatan personal (is_industry_policy_topic)
   - Deduplikasi kemiripan judul (is_near_duplicate_title >= 85)
5. Filter tanggal publikasi: HANYA KEMARIN (is_published_yesterday)
6. Mapping spokesperson (6 nama acuan) & unit eselon
7. Analisis sentimen tone (3 kelas IndoBERT: Positif/Netral/Negatif)
8. Ekspor ke Excel di folder 'hasil_scrapping/' dengan styling dan hyperlink
"""

import sys
import os

# Tambahkan src ke sys.path agar seluruh modul dalam src/ dapat diimpor langsung
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))
import json
import time
import threading
import argparse
from datetime import date
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            getattr(sys.stdout, "reconfigure")(encoding="utf-8")
    except Exception:
        pass

from src.config import (
    load_keywords,
    load_spokesperson_map,
    get_date_range,
    get_date_folder,
    is_published_yesterday,
    is_single_word_keyword,
    log_granular,
    start_heartbeat,
    format_display_url,
)
from src.fetch_news import (
    collect_all,
    search_keyword,
    is_near_duplicate_title,
    dedup_by_link,
    dedup_by_title,
    GoogleCaptchaBlockedError,
    determine_session_source,
)
from src.extract_content import (
    extract_article_text,
    is_suspiciously_short,
    resolve_article_url,
)
from src.relevance_filter import (
    is_pdf_document,
    is_recipe,
    is_promotional,
    is_job_posting,
    is_crime_or_accident,
    is_celebrity_entertainment,
    is_keyword_primary_topic,
    is_industry_policy_topic,
    is_kemenperin_related,
    get_kemenperin_signal,
    is_kertas_context_valid,
    is_kelapa_context_valid,
    is_karet_context_valid,
    is_kakao_context_valid,
    is_cokelat_context_valid,
    is_tar_context_valid,
    is_teh_context_valid,
    is_susu_context_valid,
    is_kopi_context_valid,
    is_fame_context_valid,
    is_foreign_noise_domain,
    is_pulp_context_valid,
    is_crime_accident_noise,
    is_sawit_context_valid,
    is_non_article_document_noise,
    is_social_media_engagement_noise,
    is_shorts_entertainment_noise,
    is_pome_context_valid,
    is_placeholder_or_error_title,
    is_viral_social_media_drama,
    is_lifestyle_tourism_noise,
    is_personal_blog_noise,
    is_local_retail_enforcement,
    is_non_article_structural_noise,
    is_ecommerce_product_listing,
    is_vendor_advertorial,
    is_farmgate_tbs_or_retail_price_noise,
    is_crime_wildlife_or_pure_seizure_noise,
    is_non_agro_or_general_politics_topic,
    has_ditjen_agro_override,
    has_kemenperin_or_agro_override,
    is_agro_relevant_content,
)
from src.ai_relevance_classifier import (
    classify_agro_relevance,
    log_ai_rejection,
    classify_articles_in_batches,
)
from src.tone_classifier import classify_tone_batch, classify_tone
from src.negative_summarizer import summarize_negative_articles
from src.config import ENABLE_YOUTUBE
from src.entity_mapper import find_spokespersons
from src.export_excel import save_to_excel
from src.serper_search import search_serper_news
from src.exa_search import search_exa_news
from src.youtube_search import search_youtube_videos, get_kemenperin_channel_videos
from src.direct_crawl_agro import (
    fetch_agro_kemenperin,
    cocokkan_rilis_resmi,
    integrate_agro_kemenperin_pipeline,
)

USE_SERPER_ONLY = os.environ.get("USE_SERPER_ONLY", "false").lower() in ("true", "1", "yes")

OUTPUT_DIR = "hasil_scrapping"
os.makedirs(OUTPUT_DIR, exist_ok=True)

_EXTRACTED_CACHE: dict[str, dict] = {}


def get_cached_article(url: str) -> dict | None:
    if not url:
        return None
    key = url.strip().split("?")[0].rstrip("/").lower()
    return _EXTRACTED_CACHE.get(key)


def cache_article(art: dict) -> None:
    link = (art.get("link") or art.get("Link Website") or art.get("url") or art.get("resolved_url") or "").strip()
    text = str(art.get("text") or "").strip()
    if link and text:
        key = link.split("?")[0].rstrip("/").lower()
        _EXTRACTED_CACHE[key] = art
        res_url = (art.get("resolved_url") or "").strip()
        if res_url:
            res_key = res_url.split("?")[0].rstrip("/").lower()
            _EXTRACTED_CACHE[res_key] = art


def preload_cache(target_dates: list[str] | None = None) -> None:
    candidates = [
        "hasil_scrapping/Oktober/2026-10-13_sd_2026-10-19/progress.json",
        "hasil_scrapping/Oktober/2026-10-13/progress.json",
        "hasil_scrapping/Oktober/2026-10-12/progress.json",
        "hasil_scrapping/Oktober/2026-10-11/progress.json",
        "hasil_scrapping/Oktober/2026-10-09_sd_2026-10-12/progress.json",
        "hasil_scrapping/Oktober/2026-10-08/progress.json",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    p_data = json.load(f)
                    for a in p_data.get("articles", []):
                        cache_article(a)
            except Exception:
                pass
    if _EXTRACTED_CACHE:
        print(f"[Cache Preload] Siap menggunakan cache teks untuk {len(_EXTRACTED_CACHE)} URL.", flush=True)


def extract_one_article(item: dict) -> dict:
    """Helper untuk ekstraksi konten satu artikel secara concurrent (mendukung resolusi URL Google News & direct URL Serper/Exa)."""
    link = item.get("link", "")
    cached = get_cached_article(link)
    if cached and len(str(cached.get("text", "")).strip()) >= 300:
        item_copy = dict(item)
        item_copy["text"] = cached["text"]
        item_copy["resolved_url"] = cached.get("resolved_url") or link
        if item_copy["resolved_url"] and "news.google.com" not in item_copy["resolved_url"]:
            item_copy["link"] = item_copy["resolved_url"]
        item_copy["is_suspiciously_short"] = False
        return item_copy

    if "news.google.com" in link:
        try:
            resolved = resolve_article_url(link)
        except Exception:
            resolved = link
    else:
        # Tautan langsung dari Serper.dev / Exa tidak membutuhkan resolusi Google decoder
        resolved = link

    # Cek cache lagi dengan resolved URL
    if resolved != link:
        cached = get_cached_article(resolved)
        if cached and len(str(cached.get("text", "")).strip()) >= 300:
            item_copy = dict(item)
            item_copy["text"] = cached["text"]
            item_copy["resolved_url"] = resolved
            item_copy["link"] = resolved
            item_copy["is_suspiciously_short"] = False
            return item_copy

    # Jika teks sudah disediakan oleh Exa / YouTube dan memadai (>= 300 char), gunakan langsung
    text = item.get("text", "")
    if not text or len(text.strip()) < 300:
        if item.get("sumber_data") != "YouTube":
            try:
                extracted_text = extract_article_text(resolved, max_length=8000)
                if extracted_text and len(extracted_text.strip()) > len(text):
                    text = extracted_text
            except Exception:
                pass

    item_copy = dict(item)
    item_copy["text"] = text
    item_copy["resolved_url"] = resolved
    if resolved and "news.google.com" not in resolved:
        item_copy["link"] = resolved
    item_copy["is_suspiciously_short"] = is_suspiciously_short(text)
    cache_article(item_copy)
    return item_copy


def extract_single_article_with_timer(item: dict) -> tuple[dict, str]:
    """
    Ekstraksi konten satu artikel dengan watchdog timer 10 detik.
    Jika melebihi 10 detik, cetak peringatan [LAMBAT] tanpa memutus proses.
    """
    disp_url = format_display_url(item)
    timer = threading.Timer(
        10.0,
        lambda: log_granular(f"       [LAMBAT] URL ini butuh waktu lebih dari 10 detik: {disp_url}, masih mencoba...")
    )
    timer.daemon = True
    timer.start()
    try:
        res = extract_one_article(item)
        return res, disp_url
    finally:
        timer.cancel()


def filter_valid_articles(
    articles: list[dict], min_length: int = 300, default_keyword: str | None = None
) -> tuple[list[dict], list[dict]]:
    """
    Menyaring artikel yang valid secara konten:
    - Membuang artikel kosong / gagal ekstrak / suspiciously short (< min_length)
    - Membuang materi lowongan kerja / rekrutmen (is_job_posting)
    - Membuang jika keyword bukan topik utama (title match ATAU >= 2x di teks)
    - Membuang resep kuliner (is_recipe)
    - Membuang iklan/promosi ritel (is_promotional)
    - Membuang topik kesehatan/nutrisi pribadi (is_industry_policy_topic)
    - Deduplikasi kemiripan judul (is_near_duplicate_title >= 85)
    """
    valid: list[dict] = []
    discarded: list[dict] = []
    candidates_for_ai: list[dict] = []

    for item in articles:
        title = item.get("title", "")
        text = item.get("text", "")
        link = item.get("resolved_url") or item.get("link", "")
        keyword = item.get("keyword") or default_keyword
        # 0-agro. Berita dari agro.kemenperin.go.id otomatis relevan: lewati filter penolakan & Gemini
        if item.get("sumber_data") == "agro.kemenperin.go.id" or "agro.kemenperin.go.id" in str(item.get("media_name", "")):
            item["status"] = "relevan"
            item["status_ai"] = "relevan"
            item["alasan"] = "Rilis resmi Ditjen Industri Agro (agro.kemenperin.go.id)"
            item["terkait_kemenperin"] = "Ya"
            item["unit_eselon"] = "IA"
            item["Status Review"] = ""
            valid.append(item)
            continue

        # 1-yt-disabled. Skip YouTube jika flag ENABLE_YOUTUBE = False
        if not ENABLE_YOUTUBE and item.get("sumber_data", "").strip().lower() == "youtube":
            item_copy = dict(item)
            item_copy["discard_reason"] = "youtube_disabled"
            discarded.append(item_copy)
            continue

        # BAGIAN 1: Filter pola struktural (nomor telepon/WA, placeholder agregator, galeri stock foto, campaign donasi, profil sekolah statis, e-commerce, vendor, OJS, BCA Sekuritas / entitas tanpa berita, pendanaan korporasi)
        # Filter paling awal sebelum filter relevansi lain (gratis, rule-based)
        if is_non_article_structural_noise(title=title, url=link, text=text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "structural_noise"
            discarded.append(item_copy)
            continue

        # 1-tbs. Cek harga TBS sawit tingkat petani harian / harga pangan eceran lokal
        if is_farmgate_tbs_or_retail_price_noise(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "farmgate_tbs_or_retail_price"
            discarded.append(item_copy)
            continue

        # 1-crime-wildlife. Cek kriminal murni, satwa liar, atau razia sita rokok lokal tanpa kebijakan industri
        if is_crime_wildlife_or_pure_seizure_noise(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "crime_wildlife_or_pure_seizure"
            discarded.append(item_copy)
            continue

        # 1-non-agro. Cek topik non-agro (emas, kriya keramik, perombakan kabinet umum, hilirisasi ESDM Bahlil, penutupan perkebunan sepihak)
        if is_non_agro_or_general_politics_topic(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "non_agro_or_general_politics"
            discarded.append(item_copy)
            continue

        # 1-placeholder. Cek judul placeholder / error / artifact halaman sistem non-berita
        if is_placeholder_or_error_title(title=title, text=text, url=link):
            item_copy = dict(item)
            item_copy["discard_reason"] = "placeholder_or_error_title"
            discarded.append(item_copy)
            continue

        # 1-viral. Cek video viral / medsos tanpa konteks kebijakan/industri
        if is_viral_social_media_drama(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "viral_social_media_drama"
            discarded.append(item_copy)
            continue

        # 1-pdf. Cek dokumen PDF (diblokir total sesuai instruksi)
        if (item.get("sumber_data", "").upper() == "PDF" or
            is_pdf_document(url=link, title=title, sumber_data=item.get("sumber_data", ""))):
            item_copy = dict(item)
            item_copy["discard_reason"] = "pdf_blocked"
            discarded.append(item_copy)
            continue

        # 1. Cek isi kosong atau terlalu pendek
        if not text or len(text.strip()) < min_length:
            item_copy = dict(item)
            item_copy["discard_reason"] = "empty_or_too_short"
            discarded.append(item_copy)
            continue

        # 1a. Cek domain asing yang mengindeks berita auto-translate (seperti .vn)
        if is_foreign_noise_domain(link):
            item_copy = dict(item)
            item_copy["discard_reason"] = "foreign_noise_domain"
            discarded.append(item_copy)
            continue

        # 1b. Cek materi lowongan pekerjaan / rekrutmen (termasuk pola URL /job/)
        if is_job_posting(title, text, url=link):
            item_copy = dict(item)
            item_copy["discard_reason"] = "job_posting"
            discarded.append(item_copy)
            continue

        # 1c. Cek berita kriminal/kecelakaan/musibah non-industri
        if is_crime_or_accident(title, text) or is_crime_accident_noise(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "crime_or_accident"
            discarded.append(item_copy)
            continue

        # 1d. Cek berita infotainment / selebriti murni
        if is_celebrity_entertainment(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "celebrity_entertainment"
            discarded.append(item_copy)
            continue

        # 1e. Cek resep kuliner (wajib dibuang meski menyebut Kemenperin/Agro)
        if is_recipe(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "recipe"
            discarded.append(item_copy)
            continue

        # 1f. Cek materi promosi ritel / iklan (wajib dibuang meski menyebut Kemenperin/Agro)
        if is_promotional(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "promotional"
            discarded.append(item_copy)
            continue

        # 1g. Cek dokumen non-artikel berita (bab skripsi/tesis, template jurnal akademik, abstrak)
        if is_non_article_document_noise(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "non_article_document_noise"
            discarded.append(item_copy)
            continue

        # 1h-tourism. Cek konten rekreasi wisata / kafe / nongkrong non-industri
        if is_lifestyle_tourism_noise(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "lifestyle_tourism_noise"
            discarded.append(item_copy)
            continue

        # 1h-blog. Cek esai pribadi / curhat / diary non-industri (Kompasiana dll)
        if is_personal_blog_noise(title, text, url=link):
            item_copy = dict(item)
            item_copy["discard_reason"] = "personal_blog_noise"
            discarded.append(item_copy)
            continue

        # 1h-retail. Cek penegakan hukum ritel lokal (Satpol PP segel toko, Raperda DPRD kota/kabupaten)
        if is_local_retail_enforcement(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "local_retail_enforcement"
            discarded.append(item_copy)
            continue

        # 1j. Cek konten interaktif / engagement media sosial (Shorts CTA / Q&A polling)
        if is_social_media_engagement_noise(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "social_media_engagement_noise"
            discarded.append(item_copy)
            continue

        # 1k. Cek konten hiburan YouTube Shorts / meme / hashtag spam
        if (item.get("sumber_data", "").strip().lower() == "youtube" or "#shorts" in title.lower()) and is_shorts_entertainment_noise(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "shorts_entertainment_noise"
            discarded.append(item_copy)
            continue

        # 1l. Validasi khusus keyword 'pome' (wajib lolos konteks industri limbah sawit/biogas, tolak anjing Pomeranian)
        if keyword and keyword.lower() == "pome" and not is_pome_context_valid(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "pome_pomeranian_or_non_industrial"
            discarded.append(item_copy)
            continue

        # 1h. Validasi khusus keyword 'fame' (wajib lolos konteks industri biodiesel/oleokimia, tidak boleh di-override)
        if keyword and keyword.lower() == "fame" and not is_fame_context_valid(title, text):
            item_copy = dict(item)
            item_copy["discard_reason"] = "fame_non_industrial"
            discarded.append(item_copy)
            continue

        # 1i. Validasi khusus pencarian pejabat (wajib substantif Agro untuk pejabat lintas-direktorat)
        if keyword in ("pejabat_presisi", "pejabat_kemenperin"):
            sp1, _, _ = find_spokespersons(f"{title} {text}")
            is_specific_agro = sp1.lower() in {
                "putu juli ardika", "merrijantij punguan", "dyan garneta",
                "rr citra rapati", "krisna septiningrum",
            }
            if not is_specific_agro and not is_agro_relevant_content(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "non_agro_pejabat_topic"
                discarded.append(item_copy)
                continue

        # OVERRIDE: Artikel yang menyebut Kemenperin, Menperin/Wamenperin, Ditjen Industri Agro,
        # atau salah satu dari 13 pejabat Kemenperin langsung lolos is_keyword_primary_topic dan is_industry_policy_topic
        if not has_kemenperin_or_agro_override(title, text):
            # 2. Filter frekuensi keyword & makna ganda
            if keyword and keyword.lower() == "kertas" and not is_kertas_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "kertas_kerja_or_idiom"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "kelapa" and not is_kelapa_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "kelapa_location_or_spam"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "karet" and not is_karet_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "karet_idiom_or_marine"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "kakao" and not is_kakao_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "kakao_entertainment"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "cokelat" and not is_cokelat_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "cokelat_color_or_envelope"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "pulp" and not is_pulp_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "pulp_fiction_or_pop_culture"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "tar" and not is_tar_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "tar_not_tobacco"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "teh" and not is_teh_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "teh_sundanese_honorific"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "susu" and not is_susu_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "susu_idiom_or_dental"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "kopi" and not is_kopi_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "kopi_lifestyle_or_parenting"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "fame" and not is_fame_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "fame_sports_hall_of_fame"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() == "pome" and not is_pome_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "pome_pomeranian_or_non_industrial"
                discarded.append(item_copy)
                continue

            if keyword and keyword.lower() in ("sawit", "minyak sawit") and not is_sawit_context_valid(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "sawit_location_duren_sawit"
                discarded.append(item_copy)
                continue

            if is_crime_accident_noise(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "crime_accident_noise"
                discarded.append(item_copy)
                continue

            if keyword and not is_keyword_primary_topic(title, text, keyword):
                item_copy = dict(item)
                item_copy["discard_reason"] = "keyword_not_primary_topic"
                discarded.append(item_copy)
                continue

            # 3. Filter topik industri/kebijakan vs kesehatan personal
            if not is_industry_policy_topic(title, text, sumber_data=item.get("sumber_data", "")):
                item_copy = dict(item)
                item_copy["discard_reason"] = "health_personal_topic"
                discarded.append(item_copy)
                continue
        # Lolos seluruh filter rule-based -> kumpulkan untuk evaluasi AI batch
        candidates_for_ai.append(item)

    # BAGIAN 2: AI Relevance Classifier (Google Gemini API) Mode Batch
    # Mengevaluasi kandidat yang lolos rule-based dalam batch efisien (tanpa terkena RPM limit)
    if candidates_for_ai:
        for idx, c in enumerate(candidates_for_ai, start=1):
            c["id"] = idx
        batch_res = classify_articles_in_batches(candidates_for_ai, batch_size=25, delay_between_batches=1.0)
        by_id = batch_res.get("by_id", {})

        for c in candidates_for_ai:
            info = by_id.get(c["id"]) or by_id.get(str(c["id"])) or {}
            status_ai = info.get("status", "review")
            is_rel = status_ai in ["relevan", "review"]
            ai_reason = info.get("alasan", "")
            sub_sektor = info.get("sub_sektor", "-")

            if is_rel is False:
                c_copy = dict(c)
                c_copy["discard_reason"] = "ai_irrelevant"
                c_copy["ai_reason"] = ai_reason
                c_copy["status"] = "buang"
                discarded.append(c_copy)
                log_ai_rejection(
                    title=c.get("title", ""),
                    reason=ai_reason,
                    published=c.get("published", ""),
                    keyword=c.get("keyword") or default_keyword or ""
                )
            else:
                c["status"] = status_ai
                c["status_ai"] = status_ai
                c["alasan"] = ai_reason
                c["alasan_ai"] = ai_reason
                c["sub_sektor"] = sub_sektor
                if "ai tidak dijalankan" in str(ai_reason).lower():
                    c["Status Review"] = ai_reason
                elif status_ai == "review":
                    c["Status Review"] = f"Perlu Dicek Manual: {ai_reason}" if ai_reason else "Perlu Dicek Manual"
                else:
                    c["Status Review"] = ""
                valid.append(c)

    return valid, discarded


def process_single_keyword(
    keyword: str,
    delay: float = 1.0,
    max_workers: int = 8,
    name_map: dict[str, str] | None = None,
    serper_only: bool = False,
    target_date: date | tuple | list | None = None,
) -> dict:
    """
    Mengambil, mengekstrak, dan menyaring berita untuk satu kata kunci,
    termasuk filter tanggal 'kemarin' dan filter institusi Kemenperin (Eksplisit/Implisit)
    dengan 6 sub-tahap granular dan progress counter live.
    """
    t_start = time.time()
    if name_map is None:
        name_map = load_spokesperson_map("keyword/keyword_nama.xlsx")

    start_d, end_d = get_date_range(target_date)
    eval_target_date = (start_d, end_d)

    use_serper = serper_only or USE_SERPER_ONLY
    log_granular(f"  [>] Memproses keyword: '{keyword}'...")

    # [1/6] Fetch RSS (media + gov)
    if use_serper:
        raw_results = search_serper_news(keyword, target_date=eval_target_date)
    else:
        raw_results = search_keyword(keyword, delay=delay, target_date=eval_target_date)
    log_granular(f"     [1/6] Fetch RSS (media + gov)...          -> selesai, {len(raw_results)} kandidat")

    for item in raw_results:
        if "sumber_data" not in item:
            item["sumber_data"] = "Serper" if use_serper else "RSS"

    # [2/6] Fetch Exa (jika keyword 1 kata)
    if is_single_word_keyword(keyword):
        exa_items = search_exa_news(keyword, target_date=eval_target_date)
        if exa_items:
            log_granular(f"     [2/6] Fetch Exa (jika keyword 1 kata)...  -> selesai, {len(exa_items)} kandidat")
            raw_results = raw_results + exa_items
        else:
            log_granular(f"     [2/6] Fetch Exa (jika keyword 1 kata)...  -> selesai, 0 kandidat")
    else:
        log_granular(f"     [2/6] Fetch Exa (jika keyword 1 kata)...  -> dilewati (keyword > 1 kata)")

    # Fetch YouTube (1x per keyword, hemat kuota: 100 unit)
    if ENABLE_YOUTUBE:
        yt_items = search_youtube_videos(keyword, target_date=eval_target_date)
        if yt_items:
            log_granular(f"     [+] Fetch YouTube (search 1x)...          -> selesai, {len(yt_items)} video")
            raw_results = raw_results + yt_items
        else:
            log_granular(f"     [-] Fetch YouTube (search 1x)...          -> 0 video (atau API key kosong)")
    else:
        log_granular(f"     [-] Fetch YouTube (search 1x)...          -> dilewati (ENABLE_YOUTUBE=False)")

    candidates = dedup_by_link(raw_results)
    init_count = len(candidates)

    # [3/6] Filter tanggal kemarin
    yesterday_candidates = [c for c in candidates if is_published_yesterday(c.get("published", ""), target_date=eval_target_date)]
    date_dropped_count = init_count - len(yesterday_candidates)
    log_granular(f"     [3/6] Filter tanggal kemarin...            -> {len(yesterday_candidates)} lolos")

    # [4/6] Ekstraksi konten
    total_yest = len(yesterday_candidates)
    log_granular(f"     [4/6] Ekstraksi konten ({total_yest} artikel)...")
    extracted = []
    if yesterday_candidates:
        workers = min(max_workers, 10 if use_serper else 6)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(extract_single_article_with_timer, item) for item in yesterday_candidates]
            completed = 0
            for f in as_completed(futures):
                completed += 1
                try:
                    res, disp_url = f.result(timeout=35)
                    extracted.append(res)
                except GoogleCaptchaBlockedError:
                    raise
                except Exception:
                    disp_url = "url"
                log_granular(f"       -> mengekstrak artikel {completed}/{total_yest}: {disp_url}")
    else:
        log_granular(f"       -> tidak ada artikel tanggal kemarin untuk diekstrak")

    # [5/6] Filter relevansi & dedup
    content_valid, discarded = filter_valid_articles(extracted, min_length=300, default_keyword=keyword)
    log_granular(f"     [5/6] Filter relevansi & dedup...          -> {len(content_valid)} lolos")

    reasons = {}
    for d in discarded:
        r = d.get("discard_reason", "other")
        reasons[r] = reasons.get(r, 0) + 1

    # [6/6] Sentiment & entity mapping
    kemenperin_yes_count = 0
    flagged_articles = []
    for item in content_valid:
        is_rel, sig_type, sig_det = get_kemenperin_signal(
            item.get("title", ""), item.get("text", ""), name_map
        )
        item_copy = dict(item)
        item_copy["keyword"] = keyword
        item_copy["terkait_kemenperin"] = "Ya" if is_rel else "Tidak"
        item_copy["kemenperin_signal_type"] = sig_type
        item_copy["kemenperin_signal_detail"] = sig_det
        flagged_articles.append(item_copy)
        if is_rel:
            kemenperin_yes_count += 1

    log_granular(f"     [6/6] Sentiment & entity mapping...        -> selesai")
    duration = time.time() - t_start
    log_granular(f"   [OK] '{keyword}' selesai: {len(content_valid)} artikel final. (durasi: {duration:.0f} detik)")

    kemenperin_no_count = len(content_valid) - kemenperin_yes_count

    return {
        "keyword": keyword,
        "initial_candidates": init_count,
        "date_valid_count": len(yesterday_candidates),
        "date_dropped_count": date_dropped_count,
        "content_valid_count": len(content_valid),
        "kemenperin_yes_count": kemenperin_yes_count,
        "valid_articles": flagged_articles,
        "discarded_count": len(discarded) + date_dropped_count,
        "discard_reasons": reasons,
    }



def finalize_and_export(
    articles: list[dict],
    name_map: dict[str, str],
    output_excel: str = os.path.join(OUTPUT_DIR, "hasil_scraping_berita_lengkap.xlsx"),
):
    """
    Deduplikasi lintas keyword, entity mapping, sentiment analysis, dan export ke file Excel.
    """
    print("\n" + "=" * 60, flush=True)
    print("=== TAHAP FINAL: DEDUPLIKASI LINTAS KEYWORD & NLP ===", flush=True)
    print("=" * 60, flush=True)

    # 0. Direct crawl portal resmi Ditjen Industri Agro (agro.kemenperin.go.id)
    try:
        start_date, end_date = get_date_range()
        print(f"\n[Direct Crawl Ditjen Agro] Memeriksa portal agro.kemenperin.go.id ({start_date} s.d {end_date})...", flush=True)
        agro_articles = fetch_agro_kemenperin(start_date, end_date, include_content=True)
        if agro_articles:
            print(f"  -> Ditemukan {len(agro_articles)} rilis resmi Ditjen Agro. Menggabungkan ke antrean...", flush=True)
            for a in agro_articles:
                tgl_val = a.get("Tanggal")
                tgl_str = tgl_val.strftime("%Y-%m-%d %H:%M:%S") if hasattr(tgl_val, "strftime") else str(tgl_val or "")
                articles.append({
                    "title": a.get("Title", ""),
                    "link": a.get("Link Website", ""),
                    "resolved_url": a.get("Link Website", ""),
                    "published": tgl_str,
                    "media_name": "Kemenperin (agro.kemenperin.go.id)",
                    "sumber_data": "agro.kemenperin.go.id",
                    "text": a.get("isi", ""),
                    "keyword": "Rilis Resmi Ditjen Agro",
                })
        else:
            print("  -> Tidak ada rilis baru di agro.kemenperin.go.id pada rentang tanggal tersebut.", flush=True)
    except Exception as e:
        print(f"  -> Peringatan direct crawl agro.kemenperin.go.id: {e}", flush=True)

    total_before = len(articles)

    # 1. Dedup lintas keyword berdasarkan URL dasar
    seen_urls = set()
    cross_deduped = []
    for art in articles:
        url_to_check = art.get("resolved_url") or art.get("link", "")
        clean_url = url_to_check.split("?")[0].rstrip("/")
        if clean_url not in seen_urls:
            seen_urls.add(clean_url)
            cross_deduped.append(art)

    # 2. Dedup lintas keyword berdasarkan kemiripan judul (rapidfuzz >= 85)
    final_unique = dedup_by_title(cross_deduped, threshold=85)
    total_after = len(final_unique)

    print(f"Total artikel sebelum dedup lintas keyword : {total_before}", flush=True)
    print(f"Total artikel setelah dedup URL & judul   : {total_after} (Dieliminasi: {total_before - total_after})", flush=True)

    # 3. Entity Mapping & Gemini AI Tone Analysis
    print(f"\nMenjalankan Entity Mapping dan Gemini AI Tone Analysis pada {total_after} artikel...", flush=True)
    records = []
    sp_count = 0
    tone_dist = {"Positif": 0, "Netral": 0, "Negatif": 0}

    # Beri ID untuk batch tone classification
    for idx, art in enumerate(final_unique, start=1):
        art["id"] = idx

    print(f"Menginspeksi tone dengan Gemini AI API untuk {total_after} artikel...", flush=True)
    tone_batch_results = classify_tone_batch(final_unique, use_ai=True)
    tone_map = {res["id"]: res.get("tone", "Netral") for res in tone_batch_results}

    for idx, art in enumerate(final_unique, start=1):
        text = art.get("text", "")
        sp1, sp2, unit = find_spokespersons(text, name_map)
        tone = tone_map.get(art.get("id"), "Netral")
        is_rel, sig_type, sig_det = get_kemenperin_signal(
            art.get("title", ""), text, name_map
        )
        terkait_kemenperin = "Ya" if is_rel else "Tidak"

        if sp1 or sp2:
            sp_count += 1
        tone_dist[tone] = tone_dist.get(tone, 0) + 1

        records.append({
            "Tanggal": art.get("published", ""),
            "Isu": art.get("Isu") or art.get("isu") or art["title"],
            "Title": art["title"],
            "Link Website": art.get("link", ""),
            "Media Name": art.get("media_name") or "",
            "Tone": tone,
            "Spokesperson 1": sp1,
            "Spokesperson 2": sp2,
            "Unit Eselon": unit,
            "Terkait Kemenperin": terkait_kemenperin,
            "Status Review": art.get("Status Review", ""),
            "Keywords": art.get("keyword", ""),
            "Sumber Data": art.get("sumber_data", "RSS"),
        })

    print(f"Entity Mapping: {sp_count} artikel memiliki Spokesperson terisi, {total_after - sp_count} kosong.", flush=True)
    print(f"Distribusi Tone: Positif={tone_dist.get('Positif', 0)}, Netral={tone_dist.get('Netral', 0)}, Negatif={tone_dist.get('Negatif', 0)}", flush=True)

    # 3b. Verifikasi silang judul media lain dengan rilis resmi Ditjen Agro jika ada
    official_agro = [
        r for r in records
        if r.get("Sumber Data") == "agro.kemenperin.go.id" or "agro.kemenperin.go.id" in str(r.get("Media Name", ""))
    ]
    if official_agro:
        df_recs = pd.DataFrame(records)
        df_recs = cocokkan_rilis_resmi(df_recs, official_agro, ambang=80)
        records = df_recs.to_dict(orient="records")

    # 3c. Ringkasan Otomatis Berita Bertone Negatif (5W+1H + Stakeholders)
    neg_summaries = None
    if any(r.get("Tone") == "Negatif" for r in records):
        print(f"\nMenjalankan ringkasan otomatis 5W+1H untuk berita bertone Negatif...", flush=True)
        txt_map = {
            str(a.get("link") or "").strip(): str(a.get("text") or "").strip()
            for a in final_unique if a.get("link")
        }
        neg_summaries = summarize_negative_articles(records, progress_text_map=txt_map)

    # 4. Simpan ke file Excel (merge jika file sudah ada)
    save_to_excel(records, output_excel, merge_existing=True, negative_summaries=neg_summaries)
    print(f"\nHasil akhir berhasil disimpan / di-merge ke: {output_excel}", flush=True)

    if neg_summaries:
        base_dir, base_file = os.path.split(output_excel)
        if not base_file.endswith("_ringkasan.xlsx"):
            ringkasan_path = os.path.join(base_dir, base_file.replace(".xlsx", "_ringkasan.xlsx"))
            save_to_excel(records, ringkasan_path, merge_existing=False, negative_summaries=neg_summaries)
            print(f"Salinan dengan ringkasan negatif disimpan ke: {ringkasan_path}", flush=True)

    return records, tone_dist


def run_pipeline(
    keywords_or_file: str | list[str] = "keyword/keyword_data.txt",
    output_excel: str | None = None,
):
    """
    Pipeline runner untuk single keyword atau kumpulan keyword.
    Menyimpan hasil ke folder hasil_scrapping/.
    """
    print("=== MEMULAI PIPELINE SCRAPING BERITA INDUSTRI ===")

    start_date, end_date = get_date_range()
    date_folder = get_date_folder((start_date, end_date))
    date_str = start_date.strftime("%Y-%m-%d") if start_date == end_date else f"{start_date.strftime('%Y-%m-%d')}_sd_{end_date.strftime('%Y-%m-%d')}"

    if isinstance(keywords_or_file, list):
        keywords = keywords_or_file
    else:
        keywords = load_keywords(keywords_or_file)

    if not output_excel:
        if len(keywords) == 1:
            output_excel = os.path.join(date_folder, f"checkpoint_{keywords[0]}.xlsx")
        else:
            output_excel = os.path.join(date_folder, f"all_{date_str}.xlsx")
    elif not os.path.dirname(output_excel):
        output_excel = os.path.join(date_folder, output_excel)

    name_map = load_spokesperson_map("keyword/keyword_nama.xlsx")
    print(f"Loaded: {len(keywords)} keyword ({keywords[:5]}...), {len(name_map)} pejabat.")

    eval_target_date = (start_date, end_date)
    if USE_SERPER_ONLY:
        print(f"  [>] Mode USE_SERPER_ONLY aktif: Mengambil kandidat via Serper.dev...", flush=True)
        raw_results = []
        for kw in keywords:
            raw_results.extend(search_serper_news(kw, target_date=eval_target_date))
    else:
        raw_results = collect_all(keywords)

    for item in raw_results:
        if "sumber_data" not in item:
            item["sumber_data"] = "Serper" if USE_SERPER_ONLY else "RSS"

    # Integrasi Exa Search permanen: HANYA untuk keyword satu kata
    for kw in keywords:
        if is_single_word_keyword(kw):
            print(f"  [>] [Exa.ai] Fetching berita pelengkap untuk keyword 1 kata '{kw}'...", flush=True)
            exa_items = search_exa_news(kw, target_date=eval_target_date)
            if exa_items:
                print(f"      -> {len(exa_items)} kandidat pelengkap ditemukan oleh Exa Search.", flush=True)
                raw_results.extend(exa_items)
            else:
                print(f"      -> Tidak ada entri tambahan dari Exa (atau EXA_API_KEY tidak diset).", flush=True)

    raw_results = dedup_by_link(raw_results)
    print(f"Kandidat berita setelah domain filter & dedup awal: {len(raw_results)}")

    # Filter Tanggal: HANYA TARGET DATE (sebelum ekstraksi untuk kecepatan)
    print(f"\n[Filter Tanggal] Menyaring artikel tanggal publikasi target: {start_date} s.d. {end_date}...")
    yesterday_candidates = [item for item in raw_results if is_published_yesterday(item.get("published", ""), target_date=eval_target_date)]
    date_dropped_count = len(raw_results) - len(yesterday_candidates)
    print(f"Total sebelum filter tanggal : {len(raw_results)} artikel")
    print(f"Artikel gugur filter tanggal: {date_dropped_count} artikel")
    print(f"Artikel lolos filter tanggal (kemarin): {len(yesterday_candidates)} artikel")

    total_yest = len(yesterday_candidates)
    log_granular(f"Mengekstrak {total_yest} artikel tanggal kemarin...")
    extracted_articles = []
    if yesterday_candidates:
        workers = min(8, 4 if USE_SERPER_ONLY else 2)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(extract_single_article_with_timer, item) for item in yesterday_candidates]
            completed = 0
            for f in as_completed(futures):
                completed += 1
                try:
                    res, disp_url = f.result(timeout=35)
                    extracted_articles.append(res)
                except Exception:
                    disp_url = "url"
                log_granular(f"  -> mengekstrak artikel {completed}/{total_yest}: {disp_url}")
    else:
        log_granular("  -> 0 artikel untuk diekstrak")

    content_valid, discarded = filter_valid_articles(extracted_articles, min_length=300)
    print(f"Artikel lolos filter konten & industri: {len(content_valid)} (Dibuang konten: {len(discarded)})")

    # Flagging Institusi: Terkait Kemenperin (Eksplisit atau Implisit) - OPSI B
    records = []
    spokesperson_filled = 0
    spokesperson_empty = 0
    kemenperin_yes_count = 0

    for item in content_valid:
        text = item["text"]
        sp1, sp2, unit = find_spokespersons(text, name_map)
        tone = classify_tone(text=text, title=item.get("title", ""))
        is_rel, sig_type, sig_det = get_kemenperin_signal(
            item.get("title", ""), text, name_map
        )
        terkait_kemenperin = "Ya" if is_rel else "Tidak"
        if is_rel:
            kemenperin_yes_count += 1

        if sp1 or sp2:
            spokesperson_filled += 1
        else:
            spokesperson_empty += 1

        records.append({
            "Tanggal": item.get("published", ""),
            "Title": item["title"],
            "Link Website": item["link"],
            "Media Name": item.get("media_name") or "",
            "Tone": tone,
            "Spokesperson 1": sp1,
            "Spokesperson 2": sp2,
            "Unit Eselon": unit,
            "Terkait Kemenperin": terkait_kemenperin,
            "Keywords": item.get("keyword", ""),
            "Sumber Data": item.get("sumber_data", "RSS"),
        })

    print(f"Status Kemenperin: {kemenperin_yes_count} Terkait Kemenperin: Ya | {len(content_valid) - kemenperin_yes_count} Tidak.")
    print(f"Entity Mapping: {spokesperson_filled} artikel memiliki Spokesperson terisi, {spokesperson_empty} kosong.")
    saved_path = save_to_excel(records, output_excel, merge_existing=True)
    print(f"Selesai. {len(records)} artikel berhasil disimpan / di-merge ke {saved_path}")
    return records, len(content_valid), date_dropped_count, kemenperin_yes_count


def run_batch_pipeline(
    keywords_or_file: str | list[str] = "keyword/keyword_data.txt",
    batch_size: int = 5,
    target_batch: int | None = None,
    checkpoint_file: str | None = None,
    output_excel: str | None = None,
):
    """
    Menjalankan scraping per batch (misal 5 keyword per batch),
    menyimpan progress ke checkpoint_file di dalam folder tanggal, dan mengekspor hasil gabungan.
    """
    start_date, end_date = get_date_range()
    date_folder = get_date_folder((start_date, end_date))
    date_str = start_date.strftime("%Y-%m-%d") if start_date == end_date else f"{start_date.strftime('%Y-%m-%d')}_sd_{end_date.strftime('%Y-%m-%d')}"

    if not checkpoint_file:
        checkpoint_path = os.path.join(date_folder, "progress.json")
    elif not os.path.dirname(checkpoint_file):
        checkpoint_path = os.path.join(date_folder, checkpoint_file)
    else:
        checkpoint_path = checkpoint_file

    if not output_excel:
        out_excel_path = os.path.join(date_folder, f"all_{date_str}.xlsx")
    elif not os.path.dirname(output_excel):
        out_excel_path = os.path.join(date_folder, output_excel)
    else:
        out_excel_path = output_excel

    if isinstance(keywords_or_file, list):
        keywords = keywords_or_file
    else:
        keywords = load_keywords(keywords_or_file)

    name_map = load_spokesperson_map("keyword/keyword_nama.xlsx")
    batches = [keywords[i : i + batch_size] for i in range(0, len(keywords), batch_size)]
    total_batches = len(batches)

    print(f"Total keyword: {len(keywords)} dibagi menjadi {total_batches} batch (ukuran batch: {batch_size})", flush=True)

    checkpoint = {"batches_done": [], "batch_reports": [], "articles": []}
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
                print(f"Checkpoint dimuat: Batch yang sudah selesai: {checkpoint.get('batches_done', [])}", flush=True)
        except Exception as e:
            print(f"Warning membaca checkpoint: {e}", flush=True)

    batches_to_run = []
    if target_batch is not None:
        if 1 <= target_batch <= total_batches:
            batches_to_run = [target_batch - 1]
        else:
            raise ValueError(f"target_batch harus antara 1 dan {total_batches}")
    else:
        batches_to_run = [i for i in range(total_batches) if i not in checkpoint.get("batches_done", [])]

    for b_idx in batches_to_run:
        b_num = b_idx + 1
        current_kws = batches[b_idx]
        print("\n" + "=" * 60, flush=True)
        print(f"=== MEMULAI BATCH {b_num}/{total_batches}: {current_kws} ===", flush=True)
        print("=" * 60, flush=True)

        batch_initial = 0
        batch_content_valid = 0
        batch_date_dropped = 0
        batch_kemenperin_yes = 0
        batch_final_valid = 0
        batch_kw_stats = []

        for kw in current_kws:
            res = process_single_keyword(kw, name_map=name_map, target_date=(start_date, end_date))
            batch_initial += res["initial_candidates"]
            batch_content_valid += res["content_valid_count"]
            batch_date_dropped += res["date_dropped_count"]
            batch_kemenperin_yes += res.get("kemenperin_yes_count", 0)
            batch_final_valid += len(res["valid_articles"])
            checkpoint["articles"].extend(res["valid_articles"])
            batch_kw_stats.append({
                "keyword": kw,
                "initial": res["initial_candidates"],
                "content_valid": res["content_valid_count"],
                "date_dropped": res["date_dropped_count"],
                "kemenperin_yes": res.get("kemenperin_yes_count", 0),
                "final_valid": len(res["valid_articles"]),
                "discarded": res["discarded_count"],
                "reasons": res["discard_reasons"],
            })

        checkpoint["batches_done"].append(b_idx)
        checkpoint["batch_reports"].append({
            "batch_num": b_num,
            "keywords": current_kws,
            "total_initial": batch_initial,
            "total_content_valid": batch_content_valid,
            "total_date_dropped": batch_date_dropped,
            "total_kemenperin_yes": batch_kemenperin_yes,
            "total_final_valid": batch_final_valid,
            "details": batch_kw_stats,
        })

        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)

        print("\n" + "-" * 50, flush=True)
        print(f"[LAPORAN SELESAI BATCH {b_num}/{total_batches}]", flush=True)
        print(f"Keywords diproses        : {', '.join(current_kws)}", flush=True)
        print(f"Total kandidat awal      : {batch_initial}", flush=True)
        print(f"Gugur filter tanggal     : {batch_date_dropped}", flush=True)
        print(f"Total final lolos kemarin: {batch_final_valid}", flush=True)
        print(f"Terkait Kemenperin (Ya)  : {batch_kemenperin_yes} | Tidak: {batch_final_valid - batch_kemenperin_yes}", flush=True)
        print("Rincian per keyword:", flush=True)
        for s in batch_kw_stats:
            kw_init = int(s.get("initial", 0) or 0)
            kw_dropped = int(s.get("date_dropped", 0) or 0)
            kw_final = int(s.get("final_valid", 0) or 0)
            kw_kem_yes = int(s.get("kemenperin_yes", 0) or 0)
            kw_kem_no = kw_final - kw_kem_yes
            print(
                f"  - '{s.get('keyword', '')}': Awal={kw_init} -> LolosKemarin={kw_init - kw_dropped} -> "
                f"FINAL={kw_final} (Kemenperin: Ya={kw_kem_yes} / Tidak={kw_kem_no})",
                flush=True,
            )
        print(f"Checkpoint tersimpan ke: {checkpoint_path}", flush=True)
        print("-" * 50, flush=True)

    if len(checkpoint["batches_done"]) == total_batches:
        print("\nSeluruh batch telah selesai! Melanjutkan ke finalisasi...", flush=True)
        try:
            from direct_crawl_kemenperin import crawl_kemenperin_siaran_pers
            from direct_crawl_agro import fetch_agro_kemenperin
            c_items = crawl_kemenperin_siaran_pers(target_date=(start_date, end_date), max_pages=3)
            if c_items:
                print(f"[Direct Crawl] Ditemukan {len(c_items)} siaran pers kemenperin.go.id", flush=True)
                for a in c_items:
                    checkpoint["articles"].append(a)
            a_items = fetch_agro_kemenperin(date_from=start_date, date_to=end_date, include_content=True)
            if a_items:
                print(f"[Direct Crawl] Ditemukan {len(a_items)} rilis resmi Ditjen Agro", flush=True)
                for a in a_items:
                    checkpoint["articles"].append({
                        "title": a.get("Title", ""),
                        "link": a.get("Link Website", ""),
                        "published": a.get("Tanggal"),
                        "media_name": a.get("Media Name", "Kemenperin (agro.kemenperin.go.id)"),
                        "unit_eselon": a.get("Unit Eselon", "IA"),
                        "terkait_kemenperin": "Ya",
                        "keyword": "agro_kemenperin_resmi",
                        "sumber_data": "agro.kemenperin.go.id",
                        "text": a.get("isi", ""),
                    })
        except Exception as e:
            print(f"[Direct Crawl Warning] {e}", flush=True)

        finalize_and_export(checkpoint["articles"], name_map, output_excel=out_excel_path)
    elif target_batch is not None:
        batch_out = os.path.join(date_folder, f"checkpoint_batch_{target_batch}.xlsx")
        print(f"\nBatch {target_batch} selesai diproses. Mengekspor hasil batch ke {batch_out}...", flush=True)
        finalize_and_export(checkpoint["articles"], name_map, output_excel=batch_out)
        print(f"Jalankan batch berikutnya dengan --batch {target_batch + 1} atau --all.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline Scraping Berita Industri & NLP")
    parser.add_argument("keyword", nargs="?", default=None, help="Satu kata kunci spesifik (opsional)")
    parser.add_argument("output", nargs="?", default=None, help="Nama file output Excel (opsional)")
    parser.add_argument("--batch", type=int, default=None, help="Nomor batch tertentu untuk dijalankan (1-indexed)")
    parser.add_argument("--all", action="store_true", help="Jalankan semua batch dari awal / lanjutkan checkpoint")
    parser.add_argument("--serper-only", action="store_true", help="Pakai Serper.dev SAJA untuk fetch berita (bypass Google News RSS)")
    parser.add_argument("--api-key", type=str, default=None, help="Serper.dev API Key")
    parser.add_argument("--date", "--target-date", dest="target_date", type=str, default=None, help="Tanggal target evaluasi YYYY-MM-DD atau range YYYY-MM-DD:YYYY-MM-DD")
    parser.add_argument("--start-date", type=str, default=None, help="Tanggal awal rentang evaluasi YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default=None, help="Tanggal akhir rentang evaluasi YYYY-MM-DD")

    args = parser.parse_args()

    if args.api_key:
        os.environ["SERPER_API_KEY"] = args.api_key.strip()

    if args.start_date and args.end_date:
        os.environ["OVERRIDE_DATE"] = f"{args.start_date.strip()}_sd_{args.end_date.strip()}"
    elif args.target_date:
        t_raw = args.target_date.strip()
        parsed = False
        for sep in (":", "_sd_", "..", " to ", " - "):
            if sep in t_raw:
                p1, p2 = t_raw.split(sep, 1)
                os.environ["OVERRIDE_DATE"] = f"{p1.strip()}_sd_{p2.strip()}"
                parsed = True
                break
        if not parsed:
            os.environ["OVERRIDE_DATE"] = t_raw

    USE_SERPER_ONLY, source_msg = determine_session_source(force_serper=args.serper_only)
    print(f"\n[STATUS SUMBER SESI] {source_msg}\n")

    preload_cache()
    start_heartbeat()

    if args.keyword and not args.keyword.startswith("--"):
        out = args.output if args.output else os.path.join(OUTPUT_DIR, f"hasil_scraping_{args.keyword}.xlsx")
        run_pipeline(keywords_or_file=[args.keyword], output_excel=out)
    elif args.batch is not None:
        run_batch_pipeline(batch_size=5, target_batch=args.batch)
    elif args.all:
        run_batch_pipeline(batch_size=5)
    else:
        run_batch_pipeline(batch_size=5)
