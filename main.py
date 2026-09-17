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
import json
import argparse
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import (
    load_keywords,
    load_spokesperson_map,
    get_date_range,
    get_date_folder,
    is_published_yesterday,
    is_single_word_keyword,
)
from fetch_news import (
    collect_all,
    search_keyword,
    is_near_duplicate_title,
    dedup_by_link,
    dedup_by_title,
)
from extract_content import (
    extract_article_text,
    is_suspiciously_short,
    resolve_article_url,
)
from relevance_filter import (
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
    has_ditjen_agro_override,
)
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel
from serper_search import search_serper_news
from exa_search import search_exa_news

USE_SERPER_ONLY: bool = os.environ.get("USE_SERPER_ONLY", "false").lower() in ("true", "1", "yes")

OUTPUT_DIR = "hasil_scrapping"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def extract_one_article(item: dict) -> dict:
    """Helper untuk ekstraksi konten satu artikel secara concurrent (mendukung resolusi URL Google News & direct URL Serper/Exa)."""
    link = item.get("link", "")
    if "news.google.com" in link:
        try:
            resolved = resolve_article_url(link)
        except Exception:
            resolved = link
    else:
        # Tautan langsung dari Serper.dev / Exa tidak membutuhkan resolusi Google decoder
        resolved = link

    # Jika teks sudah disediakan oleh Exa dan memadai (>= 300 char), gunakan langsung
    text = item.get("text", "")
    if not text or len(text.strip()) < 300:
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
    return item_copy


def filter_valid_articles(
    articles: list[dict], min_length: int = 300, default_keyword: str = None
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

    for item in articles:
        title = item.get("title", "")
        text = item.get("text", "")
        link = item.get("resolved_url") or item.get("link", "")
        keyword = item.get("keyword") or default_keyword

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
        if is_crime_or_accident(title, text):
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

        # OVERRIDE: Artikel yang menyebut Ditjen Industri Agro langsung lolos tanpa filter sekunder
        if not has_ditjen_agro_override(title, text):
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

            if keyword and not is_keyword_primary_topic(title, text, keyword):
                item_copy = dict(item)
                item_copy["discard_reason"] = "keyword_not_primary_topic"
                discarded.append(item_copy)
                continue

            # 3. Cek resep kuliner
            if is_recipe(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "recipe"
                discarded.append(item_copy)
                continue

            # 4. Cek materi promosi ritel
            if is_promotional(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "promotional"
                discarded.append(item_copy)
                continue

            # 5. Filter topik industri/kebijakan vs kesehatan personal
            if not is_industry_policy_topic(title, text):
                item_copy = dict(item)
                item_copy["discard_reason"] = "health_personal_topic"
                discarded.append(item_copy)
                continue

        # 6. Deduplikasi kemiripan judul (threshold = 85)
        matched_idx = -1
        for idx, existing in enumerate(valid):
            if is_near_duplicate_title(title, existing.get("title", ""), threshold=85):
                matched_idx = idx
                break

        if matched_idx == -1:
            valid.append(item)
        else:
            existing_text = valid[matched_idx].get("text", "")
            is_any_rss = valid[matched_idx].get("sumber_data") == "RSS" or item.get("sumber_data") == "RSS"
            if len(text) > len(existing_text):
                discarded.append({**valid[matched_idx], "discard_reason": "near_duplicate_title"})
                valid[matched_idx] = item
                if is_any_rss:
                    valid[matched_idx]["sumber_data"] = "RSS"
            else:
                item_copy = dict(item)
                item_copy["discard_reason"] = "near_duplicate_title"
                discarded.append(item_copy)
                if is_any_rss:
                    valid[matched_idx]["sumber_data"] = "RSS"

    return valid, discarded


def process_single_keyword(
    keyword: str,
    delay: float = 1.0,
    max_workers: int = 8,
    name_map: dict[str, str] | None = None,
    serper_only: bool = False,
) -> dict:
    """
    Mengambil, mengekstrak, dan menyaring berita untuk satu kata kunci,
    termasuk filter tanggal 'kemarin' dan filter institusi Kemenperin (Eksplisit/Implisit).
    """
    if name_map is None:
        name_map = load_spokesperson_map("keyword_nama.xlsx")

    use_serper = serper_only or USE_SERPER_ONLY
    if use_serper:
        print(f"  [>] [Serper.dev] Fetching berita untuk '{keyword}'...", flush=True)
        raw_results = search_serper_news(keyword)
    else:
        print(f"  [>] Fetching berita untuk '{keyword}'...", flush=True)
        raw_results = search_keyword(keyword, delay=delay)

    for item in raw_results:
        if "sumber_data" not in item:
            item["sumber_data"] = "Serper" if use_serper else "RSS"

    # Integrasi Exa Search permanen: HANYA dipanggil jika keyword satu kata
    if is_single_word_keyword(keyword):
        print(f"  [>] [Exa.ai] Fetching berita pelengkap untuk keyword 1 kata '{keyword}'...", flush=True)
        exa_items = search_exa_news(keyword)
        if exa_items:
            print(f"      -> {len(exa_items)} kandidat pelengkap ditemukan oleh Exa Search.", flush=True)
            raw_results = raw_results + exa_items
        else:
            print(f"      -> Tidak ada entri tambahan dari Exa (atau EXA_API_KEY tidak diset).", flush=True)

    candidates = dedup_by_link(raw_results)
    init_count = len(candidates)
    print(f"      -> {init_count} kandidat unik setelah filter domain & URL dedup.", flush=True)

    # 1. Filter tanggal dari metadata RSS (HANYA KEMARIN) sebelum ekstraksi web
    yesterday_candidates = [c for c in candidates if is_published_yesterday(c.get("published", ""))]
    date_dropped_count = init_count - len(yesterday_candidates)
    print(f"      -> {len(yesterday_candidates)} kandidat tanggal kemarin (Gugur tanggal arsip lama: {date_dropped_count}).", flush=True)

    extracted = []
    if yesterday_candidates:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(extract_one_article, item) for item in yesterday_candidates]
            for f in as_completed(futures):
                extracted.append(f.result())

    content_valid, discarded = filter_valid_articles(extracted, min_length=300, default_keyword=keyword)

    reasons = {}
    for d in discarded:
        r = d.get("discard_reason", "other")
        reasons[r] = reasons.get(r, 0) + 1

    # 2. Flagging institusi: Terkait Kemenperin (Eksplisit / Implisit) - OPSI B (BUKAN BUANG)
    kemenperin_yes_count = 0
    flagged_articles = []
    for item in content_valid:
        is_rel, sig_type, sig_det = get_kemenperin_signal(
            item.get("title", ""), item.get("text", ""), name_map
        )
        item_copy = dict(item)
        item_copy["terkait_kemenperin"] = "Ya" if is_rel else "Tidak"
        item_copy["kemenperin_signal_type"] = sig_type
        item_copy["kemenperin_signal_detail"] = sig_det
        flagged_articles.append(item_copy)
        if is_rel:
            kemenperin_yes_count += 1

    kemenperin_no_count = len(content_valid) - kemenperin_yes_count
    print(
        f"      -> Final Valid (setelah filter konten): {len(content_valid)} | "
        f"Terkait Kemenperin: Ya={kemenperin_yes_count} / Tidak={kemenperin_no_count}",
        flush=True,
    )

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

    # 3. Entity Mapping & Sentiment Analysis
    print(f"\nMenjalankan Entity Mapping dan Sentiment Analysis pada {total_after} artikel...", flush=True)
    records = []
    sp_count = 0
    tone_dist = {"Positif": 0, "Netral": 0, "Negatif": 0}

    for idx, art in enumerate(final_unique, start=1):
        text = art.get("text", "")
        sp1, sp2, unit = find_spokespersons(text, name_map)
        tone = classify_tone(text)
        is_rel, sig_type, sig_det = get_kemenperin_signal(
            art.get("title", ""), text, name_map
        )
        terkait_kemenperin = "Ya" if is_rel else "Tidak"

        if sp1 or sp2:
            sp_count += 1
        tone_dist[tone] = tone_dist.get(tone, 0) + 1

        records.append({
            "Tanggal": art.get("published", ""),
            "Title": art["title"],
            "Link Website": art.get("link", ""),
            "Media Name": art.get("media_name") or "",
            "Tone": tone,
            "Spokesperson 1": sp1,
            "Spokesperson 2": sp2,
            "Unit Eselon": unit,
            "Terkait Kemenperin": terkait_kemenperin,
            "Keywords": art.get("keyword", ""),
            "Sumber Data": art.get("sumber_data", "RSS"),
        })

    print(f"Entity Mapping: {sp_count} artikel memiliki Spokesperson terisi, {total_after - sp_count} kosong.", flush=True)
    print(f"Distribusi Tone: Positif={tone_dist.get('Positif', 0)}, Netral={tone_dist.get('Netral', 0)}, Negatif={tone_dist.get('Negatif', 0)}", flush=True)

    # 4. Simpan ke file Excel (merge jika file sudah ada)
    save_to_excel(records, output_excel, merge_existing=True)
    print(f"\nHasil akhir berhasil disimpan / di-merge ke: {output_excel}", flush=True)

    return records, tone_dist


def run_pipeline(
    keywords_or_file: str | list[str] = "keyword_data.txt",
    output_excel: str | None = None,
):
    """
    Pipeline runner untuk single keyword atau kumpulan keyword.
    Menyimpan hasil ke folder hasil_scrapping/.
    """
    print("=== MEMULAI PIPELINE SCRAPING BERITA INDUSTRI ===")

    yesterday_date, _ = get_date_range()
    date_folder = get_date_folder(yesterday_date)
    date_str = yesterday_date.strftime("%Y-%m-%d")

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

    name_map = load_spokesperson_map("keyword_nama.xlsx")
    print(f"Loaded: {len(keywords)} keyword ({keywords[:5]}...), {len(name_map)} pejabat.")

    if USE_SERPER_ONLY:
        print(f"  [>] Mode USE_SERPER_ONLY aktif: Mengambil kandidat via Serper.dev...", flush=True)
        raw_results = []
        for kw in keywords:
            raw_results.extend(search_serper_news(kw))
    else:
        raw_results = collect_all(keywords)

    for item in raw_results:
        if "sumber_data" not in item:
            item["sumber_data"] = "Serper" if USE_SERPER_ONLY else "RSS"

    # Integrasi Exa Search permanen: HANYA untuk keyword satu kata
    for kw in keywords:
        if is_single_word_keyword(kw):
            print(f"  [>] [Exa.ai] Fetching berita pelengkap untuk keyword 1 kata '{kw}'...", flush=True)
            exa_items = search_exa_news(kw)
            if exa_items:
                print(f"      -> {len(exa_items)} kandidat pelengkap ditemukan oleh Exa Search.", flush=True)
                raw_results.extend(exa_items)
            else:
                print(f"      -> Tidak ada entri tambahan dari Exa (atau EXA_API_KEY tidak diset).", flush=True)

    raw_results = dedup_by_link(raw_results)
    print(f"Kandidat berita setelah domain filter & dedup awal: {len(raw_results)}")

    # Filter Tanggal: HANYA KEMARIN (sebelum ekstraksi untuk kecepatan)
    start_date, end_date = get_date_range()
    print(f"\n[Filter Tanggal] Menyaring artikel tanggal publikasi persis kemarin: {start_date}...")
    yesterday_candidates = [item for item in raw_results if is_published_yesterday(item.get("published", ""))]
    date_dropped_count = len(raw_results) - len(yesterday_candidates)
    print(f"Total sebelum filter tanggal : {len(raw_results)} artikel")
    print(f"Artikel gugur filter tanggal: {date_dropped_count} artikel")
    print(f"Artikel lolos filter tanggal (kemarin): {len(yesterday_candidates)} artikel")

    print(f"Mengekstrak {len(yesterday_candidates)} artikel tanggal kemarin...")
    extracted_articles = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(extract_one_article, item) for item in yesterday_candidates]
        for f in as_completed(futures):
            extracted_articles.append(f.result())

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
        tone = classify_tone(text)
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
    keywords_or_file: str | list[str] = "keyword_data.txt",
    batch_size: int = 5,
    target_batch: int | None = None,
    checkpoint_file: str | None = None,
    output_excel: str | None = None,
):
    """
    Menjalankan scraping per batch (misal 5 keyword per batch),
    menyimpan progress ke checkpoint_file di dalam folder tanggal, dan mengekspor hasil gabungan.
    """
    yesterday_date, _ = get_date_range()
    date_folder = get_date_folder(yesterday_date)
    date_str = yesterday_date.strftime("%Y-%m-%d")

    if not checkpoint_file:
        checkpoint_file = os.path.join(date_folder, "progress.json")
    elif not os.path.dirname(checkpoint_file):
        checkpoint_file = os.path.join(date_folder, checkpoint_file)

    if not output_excel:
        output_excel = os.path.join(date_folder, f"all_{date_str}.xlsx")
    elif not os.path.dirname(output_excel):
        output_excel = os.path.join(date_folder, output_excel)

    if isinstance(keywords_or_file, list):
        keywords = keywords_or_file
    else:
        keywords = load_keywords(keywords_or_file)

    name_map = load_spokesperson_map("keyword_nama.xlsx")
    batches = [keywords[i : i + batch_size] for i in range(0, len(keywords), batch_size)]
    total_batches = len(batches)

    print(f"Total keyword: {len(keywords)} dibagi menjadi {total_batches} batch (ukuran batch: {batch_size})", flush=True)

    checkpoint = {"batches_done": [], "batch_reports": [], "articles": []}
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
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
            res = process_single_keyword(kw, name_map=name_map)
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

        with open(checkpoint_file, "w", encoding="utf-8") as f:
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
            print(
                f"  - '{s['keyword']}': Awal={s['initial']} -> LolosKemarin={s['initial'] - s['date_dropped']} -> "
                f"FINAL={s['final_valid']} (Kemenperin: Ya={s.get('kemenperin_yes', 0)} / Tidak={s['final_valid'] - s.get('kemenperin_yes', 0)})",
                flush=True,
            )
        print(f"Checkpoint tersimpan ke: {checkpoint_file}", flush=True)
        print("-" * 50, flush=True)

    if len(checkpoint["batches_done"]) == total_batches:
        print("\nSeluruh batch telah selesai! Melanjutkan ke finalisasi...", flush=True)
        finalize_and_export(checkpoint["articles"], name_map, output_excel=output_excel)
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

    args = parser.parse_args()

    if args.api_key:
        os.environ["SERPER_API_KEY"] = args.api_key.strip()

    if args.serper_only:
        USE_SERPER_ONLY = True
        os.environ["USE_SERPER_ONLY"] = "true"

    if args.keyword and not args.keyword.startswith("--"):
        out = args.output if args.output else os.path.join(OUTPUT_DIR, f"hasil_scraping_{args.keyword}.xlsx")
        run_pipeline(keywords_or_file=[args.keyword], output_excel=out)
    elif args.batch is not None:
        run_batch_pipeline(batch_size=args.batch_size, target_batch=args.batch)
    elif args.all:
        run_batch_pipeline(batch_size=args.batch_size)
    else:
        run_batch_pipeline(batch_size=args.batch_size)
