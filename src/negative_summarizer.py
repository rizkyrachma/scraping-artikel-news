"""
negative_summarizer.py
Modul Ringkasan Otomatis Berita Bertone Negatif (5W+1H + Stakeholders) untuk Media Monitoring Ditjen Industri Agro:
1. Memilih artikel Negatif (status relevan / review).
2. Mengelompokkan judul identik / mirip (rapidfuzz >= 85) menjadi satu grup: buat SATU ringkasan per grup.
3. Mengambil teks lengkap (maks 6000 karakter) dari progress.json, cache, atau ekstraksi langsung via Link.
4. Gemini API batch 3 artikel per panggilan dengan delay 3s & backoff 429.
5. Grounding check: buang stakeholder yang tidak ada di teks (partial_ratio < 85), flag verifikasi angka.
6. Caching (cache_ringkasan.json), antrean saat kuota habis (antrean_ringkasan.json), dan log (log_ringkasan.jsonl).
"""

import os
import sys
import re
import json
import time
from datetime import datetime
from rapidfuzz import fuzz

try:
    from config import load_env_file
    load_env_file()
except Exception:
    pass

try:
    from extract_content import extract_article_text
except Exception:
    extract_article_text = None

CANDIDATE_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
]
_current_model_idx = 0
_model_instance = None
gemini_quota_exhausted = False
TOTAL_API_CALLS = 0

CACHE_FILE = os.path.join("hasil_scrapping", "cache_ringkasan.json")
LOG_FILE = os.path.join("hasil_scrapping", "log_ringkasan.jsonl")
ANTREAN_FILE = os.path.join("hasil_scrapping", "antrean_ringkasan.json")


def get_summary_api_call_count() -> int:
    global TOTAL_API_CALLS
    return TOTAL_API_CALLS


def reset_summary_api_call_count():
    global TOTAL_API_CALLS
    TOTAL_API_CALLS = 0


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(str(val))
    except (ValueError, TypeError):
        return default


def _get_gemini_model(force_next: bool = False):
    """Inisialisasi model Generative AI Gemini secara lazy dengan fallback model dinamis."""
    global _model_instance, _current_model_idx, gemini_quota_exhausted

    if gemini_quota_exhausted:
        return None

    if _model_instance is not None and not force_next:
        return _model_instance

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    if force_next:
        _current_model_idx += 1

    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key, transport="rest")  # type: ignore

        while _current_model_idx < len(CANDIDATE_MODELS):
            m_name = CANDIDATE_MODELS[_current_model_idx]
            try:
                m = genai.GenerativeModel(m_name)  # type: ignore
                _model_instance = m
                return _model_instance
            except Exception:
                _current_model_idx += 1
                continue

        gemini_quota_exhausted = True
        return None
    except Exception:
        return None


SYSTEM_PROMPT = """Kamu analis media monitoring Direktorat Jenderal Industri Agro, Kemenperin. Untuk setiap berita bertone Negatif, baca judul dan isi lengkap, lalu hasilkan:
- isu_inti: satu kalimat, berita ini terkait apa.
- alasan_negatif: satu kalimat, kenapa dinilai negatif bagi industri agro atau Kemenperin.
- tone_valid: true/false. Isi false jika setelah membaca isi lengkap berita ternyata bukan negatif bagi industri agro (hanya informasi atau kabar baik), dan jelaskan di catatan_tone satu kalimat.
- w5h1: what, who, when, where, why, how. Tiap field maksimal 2 kalimat.
- stakeholder: daftar objek {nama, kategori, peran}.
  kategori: Pemerintah | Legislatif | Asosiasi | Perusahaan | Petani/Pekebun | Akademisi/Lembaga Riset | Penegak Hukum | Konsumen | Lainnya.
  peran: pembuat kebijakan | pelaku usaha | pihak terdampak | pengamat/pengkritik | penegak hukum | pemicu masalah | lainnya.

ATURAN KETAT: hanya gunakan informasi yang tertulis di berita. Dilarang mengarang nama, angka, tanggal, atau lokasi. Jika tidak disebutkan, tulis 'Tidak disebutkan'. Untuk 'when' pakai tanggal atau periode di teks; jika tidak ada, tulis 'Tidak disebutkan (terbit <tanggal terbit>)'. Stakeholder hanya pihak yang benar-benar disebut di teks (nama orang, instansi, organisasi, perusahaan, atau kelompok seperti 'petani karet'), maksimal 8, urutkan dari yang paling berpengaruh. Jawab HANYA JSON valid tanpa markdown.

Format:
{"hasil":[{"id":1,"isu_inti":"..","alasan_negatif":"..","tone_valid":true,"catatan_tone":"","w5h1":{"what":"..","who":"..","when":"..","where":"..","why":"..","how":".."},"stakeholder":[{"nama":"..","kategori":"..","peran":".."}]}]}
"""


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CACHE ERROR] Gagal menyimpan cache: {e}")


def _log_summary_action(title: str, grup: str, jumlah_panggilan: int, metode: str, catatan: str):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    entry = {
        "title": title,
        "grup": grup,
        "jumlah_panggilan": jumlah_panggilan,
        "metode": metode,
        "catatan": catatan,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[LOG ERROR] Gagal menulis log: {e}")


def _save_to_antrean(items: list[dict]):
    os.makedirs(os.path.dirname(ANTREAN_FILE), exist_ok=True)
    current_antrean = []
    if os.path.exists(ANTREAN_FILE):
        try:
            with open(ANTREAN_FILE, "r", encoding="utf-8") as f:
                current_antrean = json.load(f)
        except Exception:
            current_antrean = []
    existing_urls = {it.get("url") for it in current_antrean if it.get("url")}
    for it in items:
        u = it.get("url")
        if u and u not in existing_urls:
            current_antrean.append(it)
            existing_urls.add(u)
    try:
        with open(ANTREAN_FILE, "w", encoding="utf-8") as f:
            json.dump(current_antrean, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ANTREAN ERROR] Gagal menyimpan antrean: {e}")


def validate_grounding(raw_item: dict, source_text: str, source_title: str) -> tuple[dict, int, bool]:
    """
    Pengecekan grounding:
    - Tiap stakeholder.nama harus muncul di teks artikel (rapidfuzz partial_ratio >= 85).
      Jika tidak, hapus stakeholder itu dan catat.
    - Angka (urutan digit >= 2) di what/why/how harus ada di teks/judul; jika tidak, flag perlunya verifikasi angka.
    Mengembalikan (item_tervalidasi, jumlah_stakeholder_dibuang, angka_perlu_verifikasi).
    """
    valid_item = dict(raw_item)
    full_corpus = f"{source_title} {source_text}".lower()

    # 1. Validasi Stakeholders
    orig_sh = valid_item.get("stakeholder", []) or []
    valid_sh = []
    dropped_sh_count = 0

    for s in orig_sh:
        nama = str(s.get("nama", "")).strip()
        if not nama:
            continue
        # Cek kemunculan di teks/judul
        score = fuzz.partial_ratio(nama.lower(), full_corpus)
        if score >= 85:
            valid_sh.append(s)
        else:
            dropped_sh_count += 1
            print(f"  [GROUNDING DROP] Stakeholder '{nama}' dibuang (tidak ada di teks, score={score:.1f})")

    valid_item["stakeholder"] = valid_sh

    # 2. Validasi Angka di what, why, how
    w5h1 = valid_item.get("w5h1", {}) or {}
    wwh_combined = f"{w5h1.get('what', '')} {w5h1.get('why', '')} {w5h1.get('how', '')}"
    found_digits = re.findall(r"\b\d{2,}\b", wwh_combined)
    need_num_verif = False

    for d in found_digits:
        if d not in full_corpus:
            need_num_verif = True
            break

    return valid_item, dropped_sh_count, need_num_verif


def group_negative_articles(articles: list[dict], threshold: float = 85.0) -> list[list[dict]]:
    """
    Mengelompokkan judul identik atau mirip (rapidfuzz >= 85) menjadi satu grup.
    """
    groups = []
    for art in articles:
        t_raw = str(art.get("Title") or art.get("title", "")).strip()
        t_clean = re.sub(r"\s*[-–—|]\s*[^–—|-]+$", "", t_raw).strip().lower()
        if not t_clean:
            t_clean = t_raw.lower()

        matched = None
        for grp in groups:
            rep_raw = str(grp[0].get("Title") or grp[0].get("title", "")).strip()
            rep_clean = re.sub(r"\s*[-–—|]\s*[^–—|-]+$", "", rep_raw).strip().lower()
            if not rep_clean:
                rep_clean = rep_raw.lower()

            score_ratio = fuzz.ratio(t_clean, rep_clean)
            score_token = fuzz.token_set_ratio(t_clean, rep_clean)
            if score_ratio >= threshold or score_token >= threshold:
                matched = grp
                break

        if matched is not None:
            matched.append(art)
        else:
            groups.append([art])
    return groups


def _call_gemini_summary_batch(chunk: list[dict]) -> dict[int, dict]:
    """
    Memanggil Gemini API untuk 1 batch (maksimal 3 artikel).
    Mendukung backoff untuk error 429 dan fallback model.
    """
    global gemini_quota_exhausted, TOTAL_API_CALLS

    if gemini_quota_exhausted:
        return {}

    model = _get_gemini_model()
    if model is None:
        return {}

    payload = []
    for a in chunk:
        payload.append({
            "id": a["id"],
            "judul": str(a.get("title", "")).strip(),
            "tanggal_terbit": str(a.get("published", "")).strip(),
            "isi_teks": str(a.get("text", ""))[:6000].strip()
        })

    user_msg = f"Berikut artikel bertone Negatif untuk diringkas (total: {len(payload)}):\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_msg}"

    max_retries = 3
    for attempt in range(max_retries):
        if model is None:
            break
        try:
            TOTAL_API_CALLS += 1
            resp = model.generate_content(full_prompt, request_options={"timeout": 60})
            resp_text = (resp.text or "").strip()

            clean_json = re.sub(r"^```(?:json)?\s*", "", resp_text, flags=re.MULTILINE)
            clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE).strip()
            m = re.search(r"\{[\s\S]*\}", clean_json)
            if m:
                clean_json = m.group(0)

            data = json.loads(clean_json, strict=False)
            hasil_list = data.get("hasil", [])
            res_by_id = {}
            for item in hasil_list:
                it_id = item.get("id")
                try:
                    res_by_id[int(it_id)] = item
                except Exception:
                    res_by_id[it_id] = item

            # Cek apakah seluruh ID chunk kembali
            missing = [a["id"] for a in chunk if a["id"] not in res_by_id and str(a["id"]) not in res_by_id]
            if not missing:
                return res_by_id
            if attempt == max_retries - 1:
                return res_by_id
            print(f"  [GEMINI RETRY] ID hilang: {missing}. Melakukan retry...", flush=True)

        except Exception as e:
            err_s = str(e).lower()
            if "429" in err_s or "quota" in err_s or "resourceexhausted" in err_s:
                if "perday" in err_s or "daily" in err_s:
                    print(f"[GEMINI] Batas harian tercapai. Beralih model...", flush=True)
                    model = _get_gemini_model(force_next=True)
                    if model is None:
                        gemini_quota_exhausted = True
                        return {}
                else:
                    wait_sec = 6.0 * (attempt + 1)
                    print(f"[GEMINI 429] Rate limit tercapai, jeda {wait_sec}s...", flush=True)
                    time.sleep(wait_sec)
            else:
                print(f"[GEMINI ERROR] {e}. Beralih model / retry {attempt+1}/{max_retries}...", flush=True)
                model = _get_gemini_model(force_next=True)
                if model is None:
                    gemini_quota_exhausted = True
                    return {}
                time.sleep(2.0)

    return {}


def summarize_negative_articles(
    articles: list[dict],
    progress_text_map: dict[str, str] | None = None,
    delay_between_batches: float = 3.0
) -> list[dict]:
    """
    Fungsi utama ringkasan berita bertone negatif:
    1. Filter: Tone == 'Negatif' dan status in ['relevan', 'review']
    2. Kelompokkan judul rapidfuzz >= 85
    3. Ekstraksi / muat teks
    4. Gemini API batch 3 artikel
    5. Grounding check & validasi
    6. Return list of summary records untuk Sheet 'Ringkasan Negatif'
    """
    if progress_text_map is None:
        progress_text_map = {}

    cache = _load_cache()

    # 1. Pilih artikel negatif yang bukan dibuang
    negative_items = []
    for art in articles:
        tone_val = str(art.get("Tone") or art.get("tone", "")).strip().capitalize()
        status_val = str(art.get("status") or art.get("Status") or art.get("status_ai") or "relevan").strip().lower()
        if tone_val == "Negatif" and status_val != "buang":
            negative_items.append(art)

    print(f"\n[NEGATIVE SUMMARIZER] Menemukan {len(negative_items)} artikel bertone Negatif untuk diproses.")
    if not negative_items:
        return []

    # 2. Kelompokkan judul mirip (rapidfuzz >= 85)
    groups = group_negative_articles(negative_items, threshold=85.0)
    print(f"[NEGATIVE SUMMARIZER] Dikelompokkan menjadi {len(groups)} grup judul unik.")

    # 3. Siapkan perwakilan setiap grup dengan teks paling lengkap
    group_representatives = []
    for g_idx, grp in enumerate(groups, start=1):
        # Cari artikel dengan teks paling panjang di progress_text_map atau properti teks
        best_art = None
        best_text = ""
        for a in grp:
            u = str(a.get("Link Website") or a.get("link") or "").strip()
            clean_u = u.split("?")[0].rstrip("/")
            txt = progress_text_map.get(u) or progress_text_map.get(clean_u) or str(a.get("text") or a.get("content") or "")
            if len(txt) > len(best_text):
                best_text = txt
                best_art = a

        if best_art is None:
            best_art = grp[0]

        rep_url = str(best_art.get("Link Website") or best_art.get("link") or "").strip()

        # Ekstraksi ulang dari link jika teks kosong / < 300
        is_short_or_empty = len(best_text.strip()) < 300
        if is_short_or_empty and rep_url and extract_article_text is not None:
            try:
                print(f"  [EXTRACT] Mengekstrak ulang isi artikel: {best_art.get('Title', '')[:50]}...")
                re_txt = extract_article_text(rep_url, max_length=6000)
                if re_txt and len(re_txt.strip()) >= 300:
                    best_text = re_txt.strip()
                    is_short_or_empty = False
            except Exception as e:
                print(f"  [EXTRACT ERROR] Gagal ekstrak {rep_url}: {e}")

        group_representatives.append({
            "group_id": g_idx,
            "rep_article": best_art,
            "url": rep_url,
            "title": str(best_art.get("Title") or best_art.get("title", "")).strip(),
            "published": str(best_art.get("Tanggal") or best_art.get("published", "")).strip(),
            "text": best_text[:6000].strip(),
            "is_short_or_empty": is_short_or_empty,
            "group_members": grp
        })

    # 4. Cek Cache vs Panggilan API
    to_call_api = []
    group_summaries = {}  # group_id -> dict of summary
    total_cached = 0

    for rep in group_representatives:
        u = str(rep.get("url", ""))
        clean_u = u.split("?")[0].rstrip("/")
        cached_val = cache.get(u) or cache.get(clean_u)
        rep_gid = _safe_int(rep.get("group_id", 0))
        rep_title = str(rep.get("title", ""))
        members = rep.get("group_members", [])
        mem_len = len(members) if isinstance(members, list) else 1

        if cached_val:
            group_summaries[rep_gid] = cached_val
            total_cached += 1
            _log_summary_action(
                title=rep_title,
                grup=f"Grup {rep_gid} (size={mem_len})",
                jumlah_panggilan=0,
                metode="cache",
                catatan="Diambil dari cache"
            )
        else:
            to_call_api.append(rep)

    print(f"[NEGATIVE SUMMARIZER] {total_cached} grup ditemukan di cache, {len(to_call_api)} grup perlu diproses via Gemini API.")

    # 5. Jalankan API dalam batch 3 artikel
    batch_size = 3
    antrean_items = []

    for i in range(0, len(to_call_api), batch_size):
        chunk = to_call_api[i:i + batch_size]
        chunk_payload = [
            {
                "id": it.get("group_id"),
                "title": str(it.get("title", "")),
                "published": str(it.get("published", "")),
                "text": str(it.get("text", ""))
            }
            for it in chunk
        ]

        if not gemini_quota_exhausted:
            batch_res = _call_gemini_summary_batch(chunk_payload)
        else:
            batch_res = {}

        for rep in chunk:
            gid = _safe_int(rep.get("group_id", 0))
            rep_url = str(rep.get("url", ""))
            rep_title = str(rep.get("title", ""))
            rep_pub = str(rep.get("published", ""))
            rep_txt = str(rep.get("text", ""))
            members = rep.get("group_members", [])
            mem_len = len(members) if isinstance(members, list) else 1

            raw_summary = batch_res.get(gid)
            if raw_summary is None:
                for k, v in batch_res.items():
                    if str(k) == str(gid):
                        raw_summary = v
                        break

            if raw_summary:
                group_summaries[gid] = {
                    "raw": raw_summary,
                    "status": "success",
                    "metode": "AI"
                }
                # Simpan ke cache
                if rep_url:
                    cache[rep_url] = group_summaries[gid]
                    clean_u = rep_url.split("?")[0].rstrip("/")
                    cache[clean_u] = group_summaries[gid]
                _log_summary_action(
                    title=rep_title,
                    grup=f"Grup {gid} (size={mem_len})",
                    jumlah_panggilan=1,
                    metode="AI",
                    catatan="Sukses diringkas via Gemini API"
                )
            else:
                if gemini_quota_exhausted:
                    group_summaries[gid] = {
                        "status": "quota_exhausted",
                        "metode": "antrean"
                    }
                    antrean_items.append({
                        "url": rep_url,
                        "title": rep_title,
                        "published": rep_pub,
                        "text": rep_txt
                    })
                    _log_summary_action(
                        title=rep_title,
                        grup=f"Grup {gid}",
                        jumlah_panggilan=0,
                        metode="antrean",
                        catatan="Belum diringkas (kuota habis)"
                    )
                else:
                    group_summaries[gid] = {
                        "status": "failed",
                        "metode": "failed"
                    }
                    _log_summary_action(
                        title=rep_title,
                        grup=f"Grup {gid}",
                        jumlah_panggilan=1,
                        metode="failed",
                        catatan="Ringkasan gagal dibuat (respon AI kosong)"
                    )

        if i + batch_size < len(to_call_api) and not gemini_quota_exhausted:
            time.sleep(delay_between_batches)

    # Simpan cache terupdate & antrean jika ada
    _save_cache(cache)
    if antrean_items:
        _save_to_antrean(antrean_items)
        print(f"[NEGATIVE SUMMARIZER] {len(antrean_items)} artikel disimpan ke antrean_ringkasan.json.")

    # 6. Susun baris akhir untuk setiap anggota grup dan lakukan grounding validation
    total_stakeholder_dropped = 0
    total_number_verif_needed = 0
    tone_invalid_articles = []
    final_output_rows = []

    for rep in group_representatives:
        gid = _safe_int(rep.get("group_id", 0))
        g_data = group_summaries.get(gid, {})
        status_summ = str(g_data.get("status", "failed"))
        raw = g_data.get("raw") or {}
        is_short = bool(rep.get("is_short_or_empty", False))
        rep_txt = str(rep.get("text", ""))
        rep_title = str(rep.get("title", ""))

        if status_summ == "quota_exhausted":
            isu_inti = "Belum diringkas (kuota habis)"
            alasan_neg = "Belum diringkas (kuota habis)"
            what = who = when = where = why = how = "Belum diringkas (kuota habis)"
            stakeholders_str = "-"
            catatan_str = "Belum diringkas (kuota habis)"
        elif status_summ == "failed" or not raw:
            isu_inti = "Ringkasan gagal dibuat"
            alasan_neg = "Ringkasan gagal dibuat"
            what = who = when = where = why = how = "Ringkasan gagal dibuat"
            stakeholders_str = "-"
            catatan_str = "Ringkasan gagal dibuat"
        else:
            # Sukses didapatkan dari AI / cache -> validasi grounding
            val_item, dropped_sh, need_num = validate_grounding(raw, rep_txt, rep_title)
            total_stakeholder_dropped += dropped_sh
            if need_num:
                total_number_verif_needed += 1

            isu_inti = str(val_item.get("isu_inti", "")).strip()
            alasan_neg = str(val_item.get("alasan_negatif", "")).strip()

            w5 = val_item.get("w5h1", {}) or {}
            what = str(w5.get("what", "Tidak disebutkan")).strip()
            who = str(w5.get("who", "Tidak disebutkan")).strip()
            when = str(w5.get("when", "Tidak disebutkan")).strip()
            where = str(w5.get("where", "Tidak disebutkan")).strip()
            why = str(w5.get("why", "Tidak disebutkan")).strip()
            how = str(w5.get("how", "Tidak disebutkan")).strip()

            sh_list = val_item.get("stakeholder", []) or []
            sh_lines = [
                f"{s.get('nama', '').strip()} | {s.get('kategori', 'Lainnya').strip()} | {s.get('peran', 'pihak terdampak').strip()}"
                for s in sh_list if s.get("nama")
            ]
            stakeholders_str = "\n".join(sh_lines) if sh_lines else "Tidak disebutkan"

            notes = []
            if is_short:
                notes.append("Teks tidak tersedia, ringkasan terbatas pada judul")

            tone_valid = val_item.get("tone_valid", True)
            if tone_valid is False or str(tone_valid).lower() == "false":
                c_tone = str(val_item.get("catatan_tone", "")).strip()
                notes.append(f"Tone perlu ditinjau: {c_tone}" if c_tone else "Tone perlu ditinjau")
                tone_invalid_articles.append({
                    "title": rep_title,
                    "catatan_tone": c_tone
                })

            if need_num:
                notes.append("Perlu verifikasi angka")

            catatan_str = "; ".join(notes)

        # Pasangkan ringkasan grup ini ke SEMUA baris artikel di grup
        members = rep.get("group_members", [])
        if isinstance(members, list):
            for member in members:
                if isinstance(member, dict):
                    m_date = member.get("Tanggal") or member.get("published", "")
                    m_title = member.get("Title") or member.get("title", "")
                    m_link = member.get("Link Website") or member.get("link", "")
                    m_media = member.get("Media Name") or member.get("media_name", "")
                    m_kemenperin = member.get("Terkait Kemenperin") or member.get("terkait_kemenperin", "Tidak")

                    final_output_rows.append({
                        "Tanggal": m_date,
                        "Title": m_title,
                        "Link Website": m_link,
                        "Media Name": m_media,
                        "Terkait Kemenperin": m_kemenperin,
                        "Isu Inti": isu_inti,
                        "Alasan Negatif": alasan_neg,
                        "What": what,
                        "Who": who,
                        "When": when,
                        "Where": where,
                        "Why": why,
                        "How": how,
                        "Stakeholder Terkait": stakeholders_str,
                        "Catatan": catatan_str,
                        "_source_text": rep_txt
                    })

    # Sort: Terkait Kemenperin == 'Ya' dulu, lalu Tanggal descending
    def _sort_key(row):
        is_kem = 0 if str(row.get("Terkait Kemenperin", "")).strip().lower() == "ya" else 1
        tgl_str = str(row.get("Tanggal", "")).strip()
        return (is_kem, tgl_str)

    final_output_rows.sort(key=_sort_key)

    print(f"\n[NEGATIVE SUMMARIZER SELESAI]")
    print(f"Total baris ringkasan dibuat    : {len(final_output_rows)}")
    print(f"Total stakeholder dibuang       : {total_stakeholder_dropped}")
    print(f"Total perlu verifikasi angka    : {total_number_verif_needed}")
    print(f"Total tone_valid = false        : {len(tone_invalid_articles)}")
    for ti in tone_invalid_articles:
        print(f"  - {ti['title']}: {ti['catatan_tone']}")

    return final_output_rows
