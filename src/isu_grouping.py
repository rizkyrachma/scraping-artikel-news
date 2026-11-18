"""
src/isu_grouping.py
Modul pengelompokan isu berita (Fase 1) dan registri isu aktif untuk Ditjen Industri Agro:
- Normalisasi teks (html.unescape, buang akhiran media, kamus alias config/alias_isu.json).
- Pemuatan daftar rilis resmi Kemenperin (dari CSV/cache/crawler kemenperin.go.id).
- Pencocokan berita baru ke registri isu aktif (hasil_scrapping/isu_registry.json) dengan jendela tanggal,
  skor TF-IDF + overlap entitas/aksi spesifik, dan margin top1 minus top2.
- Kolom Keywords, Spokesperson, dan Unit Eselon TIDAK dipakai sebagai syarat maupun fitur skor.
- Pengelompokan sisa berita secara deterministik (TF-IDF / RapidFuzz / Embedding + Agglomerative).
- Pencatatan log ke hasil_scrapping/log_isu.jsonl dan coverage rilis ke hasil_scrapping/coverage_rilis.json.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
from typing import Any

import numpy as np
from rapidfuzz import fuzz
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from src.gemini_pool import GeminiModelPool
from src.stable import canonical_url

DEFAULT_ALIAS_CONFIG_PATH = os.path.join("config", "alias_isu.json")
DEFAULT_ISU_REGISTRY_PATH = os.path.join("hasil_scrapping", "isu_registry.json")
DEFAULT_LOG_ISU_PATH = os.path.join("hasil_scrapping", "log_isu.jsonl")
DEFAULT_COVERAGE_RILIS_PATH = os.path.join("hasil_scrapping", "coverage_rilis.json")
DEFAULT_RILIS_CSV_PATH = os.path.join("data", "rilis_kemenperin.csv")
DEFAULT_RILIS_CACHE_PATH = os.path.join("hasil_scrapping", "cache_rilis_kemenperin.json")

# Default parameter jendela tanggal, ambang skor, margin, dan kedaluwarsa
DEFAULT_RILIS_MAX_DAYS_BEFORE = 1
DEFAULT_RILIS_MAX_DAYS_AFTER = 7
DEFAULT_CLUSTER_EXPIRY_DAYS = 14
DEFAULT_MATCH_THRESHOLD = 0.48
DEFAULT_GRAY_ZONE_LOW = 0.36
DEFAULT_MARGIN_THRESHOLD = 0.06
DEFAULT_CLUSTER_SIM_THRESHOLD = 0.42
DEFAULT_REEVAL_MEMBER_DELTA = 3

_ISU_MODEL_POOL = GeminiModelPool("ISU GROUPING")

MATCH_ISU_PROMPT = """Kamu menerima satu berita media dan beberapa kandidat isu (judul rilis resmi Kemenperin atau isu hasil pengelompokan). Tentukan apakah berita itu meliput peristiwa, pernyataan, atau data yang SAMA dengan salah satu kandidat. Topik yang hanya mirip TIDAK cukup. Jika ragu, jawab tidak ada.
Balas HANYA JSON: {"cocok": <id kandidat atau null>, "alasan": "<satu kalimat>"}"""

ISU_LABEL_PROMPT = """Kamu menerima beberapa kelompok berita, tiap kelompok membahas satu isu yang sama. Untuk tiap kelompok, tulis satu nama isu berupa satu kalimat bergaya judul berita yang memuat pelaku utama dan tindakan utamanya. Gunakan hanya informasi di judul dan cuplikan. Jangan menambah fakta. Tandai id berita yang jelas bukan bagian isu kelompok itu pada "outlier_ids".
Balas HANYA JSON valid tanpa markdown: {"hasil":[{"kelompok_id":<id>,"isu":"...","outlier_ids":[<id>]}]}"""


_ALIAS_CACHE: dict[str, Any] | None = None


def load_alias_config(path: str | os.PathLike = DEFAULT_ALIAS_CONFIG_PATH) -> dict[str, Any]:
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None and str(path) == DEFAULT_ALIAS_CONFIG_PATH:
        return _ALIAS_CACHE
    p = Path(path)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if str(path) == DEFAULT_ALIAS_CONFIG_PATH:
                _ALIAS_CACHE = data
            return data
        except Exception:
            pass
    fallback = {
        "phrase_aliases": {
            "rokok elektrik": "rokok_elektronik",
            "rokok elektronik": "rokok_elektronik",
            "proyek strategis nasional": "psn",
            "makan bergizi gratis": "mbg",
            "seram bagian timur": "sbt",
            "susu ikan": "susu_ikan",
            "minyak atsiri": "minyak_atsiri",
            "tenaga kerja": "pekerja",
            "pelaku industri": "industri",
            "pelaku usaha": "industri",
        },
        "token_aliases": {
            "rel": "rokok_elektronik",
            "vape": "rokok_elektronik",
            "vapor": "rokok_elektronik",
            "perlindungan": "lindungi",
            "melindungi": "lindungi",
            "memohon": "minta",
            "meminta": "minta",
            "karyawan": "pekerja",
        },
        "stopwords": [
            "dan", "di", "ke", "dari", "yang", "untuk", "pada", "dengan", "ini", "itu",
            "atau", "dalam", "oleh", "sebagai", "karena", "agar", "hingga", "sampai",
            "akan", "sudah", "telah", "masih", "jadi", "menjadi", "para", "terkait",
            "begini", "dulu", "kini", "nasional", "indonesia", "ri",
        ],
        "generic_topic_tokens": [
            "sawit", "sagu", "rokok_elektronik", "susu_ikan", "kakao", "karet",
            "pulp", "tekstil", "gula", "garam", "kelor", "rumput_laut", "pakan_ternak",
            "mamin", "industri", "pemerintah", "kemenperin", "ekspor", "hilirisasi",
        ],
    }
    return fallback


_MEDIA_SUFFIX_RE = re.compile(
    r"\s+(?:[-–—|]\s*)(?:"
    r"[A-Za-z0-9_.-]+\.(?:com|co\.id|id|go\.id|net|org)"
    r"|ANTARA\s+News(?:\s+[A-Za-z]+)?"
    r"|CNN\s+Indonesia|CNBC\s+Indonesia|detik[A-Za-z]*|Kompas\.com|Tempo\.co"
    r"|Liputan6\.com|kumparan|Inilah\.com|Harian\s+Jogja|Sumut\s+Pos"
    r"|MetroTVNews\.com|FORTUNE\s+Indonesia|Industry\.co\.id|Kontan(?:\.co\.id)?"
    r"|Bisnis(?:\.com)?|Radar\s+[A-Za-z]+|Index\s+Sumut|Rakyat\s+Maluku|Ameks\s+Online"
    r")\s*$",
    re.IGNORECASE,
)


def clean_display_title(raw_title: str) -> str:
    """
    Membersihkan judul untuk tampilan nama isu:
    - html.unescape
    - Hapus akhiran nama media (contoh: ' - kumparan.com', ' | Tempo.co')
      tanpa memotong kata ulang bertanda hubung seperti 'Digadang-gadang'.
    """
    if not raw_title:
        return ""
    s = html.unescape(str(raw_title)).strip()
    s = _MEDIA_SUFFIX_RE.sub("", s).strip()
    # Cadangan: jika diakhiri ' | <Media Pendek>'
    if " | " in s:
        left, right = s.rsplit(" | ", 1)
        if len(right.split()) <= 4 and len(left) >= 15:
            s = left.strip()
    if " - " in s:
        left, right = s.rsplit(" - ", 1)
        if (
            any(ext in right.lower() for ext in (".com", ".id", ".co.id", "news", "pos", "online", "tv"))
            and len(right.split()) <= 4
            and len(left) >= 15
        ):
            s = left.strip()
    return re.sub(r"\s+", " ", s).strip()


def normalize_isu_text(text: str, alias_config: dict[str, Any] | None = None) -> str:
    """
    Normalisasi teks judul/cuplikan untuk pencocokan & klaster isu:
    1. html.unescape & buang akhiran media
    2. Lowercase & normalisasi angka mata uang (US$ / USD / Rp)
    3. Terapkan phrase_aliases & token_aliases dari config/alias_isu.json
    """
    if not text:
        return ""
    cfg = alias_config or load_alias_config()
    s = clean_display_title(text).lower()

    # Normalisasi simbol mata uang dan angka desimal
    s = re.sub(r"\bus\$\s*(\d+)[.,](\d+)", r"usd \1_\2", s)
    s = re.sub(r"\bus\$\s*(\d+)", r"usd \1", s)
    s = re.sub(r"\brp\s*(\d+)[.,](\d+)", r"rp \1_\2", s)
    s = re.sub(r"\brp\s*(\d+)", r"rp \1", s)

    # Ganti tanda baca selain underscore dan tanda hubung kata dengan spasi
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # Terapkan phrase aliases (frasa terpanjang lebih dulu)
    phrase_aliases: dict[str, str] = cfg.get("phrase_aliases") or {}
    for src_phrase in sorted(phrase_aliases.keys(), key=len, reverse=True):
        target = phrase_aliases[src_phrase]
        pat = re.compile(rf"\b{re.escape(src_phrase.lower())}\b")
        s = pat.sub(target.lower(), s)

    # Ganti sisa tanda hubung dengan spasi
    s = s.replace("-", " ")

    # Terapkan token aliases
    token_aliases: dict[str, str] = cfg.get("token_aliases") or {}
    tokens = []
    for tok in s.split():
        mapped = token_aliases.get(tok, tok)
        tokens.extend(mapped.split())

    return " ".join(tokens)


def extract_tokens(
    norm_text: str,
    alias_config: dict[str, Any] | None = None,
    exclude_generic: bool = False,
) -> set[str]:
    cfg = alias_config or load_alias_config()
    stopwords = set(cfg.get("stopwords") or [])
    generics = set(cfg.get("generic_topic_tokens") or []) if exclude_generic else set()
    out = set()
    for t in norm_text.split():
        if len(t) < 2 and not t.isdigit():
            continue
        if t in stopwords:
            continue
        if exclude_generic and t in generics:
            continue
        out.add(t)
    return out


_NUMBER_ENTITY_RE = re.compile(
    r"\b(?:usd\s*\d+(?:_\d+)?(?:\s*(?:juta|miliar|triliun))?"
    r"|rp\s*\d+(?:_\d+)?(?:\s*(?:juta|miliar|triliun))?"
    r"|\d+(?:_\d+)?\s*(?:juta|miliar|triliun|persen|ton|tahun|hari)"
    r"|\d{1,2}\s+(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)"
    r"|202\d)\b"
)

_ACRONYM_SET = {
    "kkp", "mbg", "psn", "sbt", "mk", "bnn", "mui", "ispo", "b50", "tkdn",
    "dpr", "knma", "apki", "askindo", "gapki", "hippindo", "kadin", "bpdp",
    "ntb", "sumut", "maluku", "jepang", "sumsel", "aceh", "meranti", "riau",
}


def extract_entities(norm_text: str) -> dict[str, set[str]]:
    nums = {m.group(0).strip() for m in _NUMBER_ENTITY_RE.finditer(norm_text)}
    toks = set(norm_text.split())
    acronyms = toks.intersection(_ACRONYM_SET)
    return {
        "numbers": nums,
        "acronyms": acronyms,
    }


def parse_article_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    try:
        from src.config import parse_to_wib
        ts = parse_to_wib(s)
        if ts is not None:
            return ts.date()
    except Exception:
        pass
    return None


def _char_ngrams(text: str, n_values: tuple[int, ...] = (3, 4)) -> dict[str, float]:
    padded = f" {text} "
    counts: dict[str, float] = {}
    for n in n_values:
        for i in range(max(0, len(padded) - n + 1)):
            g = padded[i : i + n]
            counts[g] = counts.get(g, 0.0) + 1.0
    return counts


def _cosine_dict(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    dot = sum(v * vec_b.get(k, 0.0) for k, v in vec_a.items())
    if dot <= 0.0:
        return 0.0
    na = math.sqrt(sum(v * v for v in vec_a.values()))
    nb = math.sqrt(sum(v * v for v in vec_b.values()))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


def compute_pair_similarity(
    item_a: dict[str, Any],
    item_b: dict[str, Any],
    method: str = "tfidf",
    alias_config: dict[str, Any] | None = None,
    idf_map: dict[str, float] | None = None,
) -> float:
    """
    Menghitung skor kemiripan [0.0 .. 1.0] antara dua artikel/isu.
    PENTING: Kolom Keywords, Spokesperson, dan Unit Eselon TIDAK pernah dipakai.
    """
    cfg = alias_config or load_alias_config()
    title_a = str(item_a.get("title") or item_a.get("Title") or item_a.get("judul") or item_a.get("isu") or "")
    title_b = str(item_b.get("title") or item_b.get("Title") or item_b.get("judul") or item_b.get("isu") or "")

    norm_a = item_a.get("_norm_title") or normalize_isu_text(title_a, cfg)
    norm_b = item_b.get("_norm_title") or normalize_isu_text(title_b, cfg)

    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0

    if method == "rapidfuzz":
        return fuzz.token_set_ratio(norm_a, norm_b) / 100.0

    all_tok_a = extract_tokens(norm_a, cfg, exclude_generic=False)
    all_tok_b = extract_tokens(norm_b, cfg, exclude_generic=False)
    spec_tok_a = extract_tokens(norm_a, cfg, exclude_generic=True)
    spec_tok_b = extract_tokens(norm_b, cfg, exclude_generic=True)

    shared_all = all_tok_a.intersection(all_tok_b)
    shared_spec = spec_tok_a.intersection(spec_tok_b)

    ent_a = extract_entities(norm_a)
    ent_b = extract_entities(norm_b)
    shared_nums = ent_a["numbers"].intersection(ent_b["numbers"])
    shared_acrs = ent_a["acronyms"].intersection(ent_b["acronyms"])

    # Guard kemurnian isu: jika tidak berbagi satupun kata spesifik (di luar topik umum)
    # dan tidak berbagi angka/akronim spesifik, batasi skor agar topik umum tidak menyatu
    if not shared_spec and not shared_nums and not shared_acrs:
        return min(0.18, len(shared_all) * 0.05)

    # Penalti jika hanya berbagi 1 kata spesifik umum tetapi angka spesifiknya bertabrakan
    if (
        ent_a["numbers"]
        and ent_b["numbers"]
        and not shared_nums
        and len(shared_spec) <= 1
    ):
        return 0.15

    # Penalti khusus jika salah satu adalah berita "sidang ... mk" dan yang lain bukan sidang/mk
    sidang_mk_a = bool({"sidang", "mk"}.intersection(all_tok_a))
    sidang_mk_b = bool({"sidang", "mk"}.intersection(all_tok_b))
    if sidang_mk_a != sidang_mk_b:
        return 0.12

    # 1. Word TF-IDF Cosine
    vec_w_a: dict[str, float] = {}
    vec_w_b: dict[str, float] = {}
    generics = set(cfg.get("generic_topic_tokens") or [])
    for t in all_tok_a:
        w = (idf_map.get(t, 1.0) if idf_map else 1.0) * (0.45 if t in generics else 1.25)
        vec_w_a[t] = w
    for t in all_tok_b:
        w = (idf_map.get(t, 1.0) if idf_map else 1.0) * (0.45 if t in generics else 1.25)
        vec_w_b[t] = w
    word_cos = _cosine_dict(vec_w_a, vec_w_b)

    # 2. Specific token Dice similarity
    if spec_tok_a and spec_tok_b:
        spec_dice = (2.0 * len(shared_spec)) / (len(spec_tok_a) + len(spec_tok_b))
    else:
        spec_dice = 0.0

    # 3. Char n-gram cosine similarity
    char_cos = _cosine_dict(_char_ngrams(norm_a), _char_ngrams(norm_b))

    score = 0.45 * word_cos + 0.35 * spec_dice + 0.20 * char_cos

    # Gabungkan kemiripan cuplikan teks pembuka (250 karakter) bila keduanya punya teks isi
    txt_a = str(item_a.get("text") or item_a.get("isi") or "").strip()[:250]
    txt_b = str(item_b.get("text") or item_b.get("isi") or "").strip()[:250]
    if txt_a and txt_b and score >= 0.25:
        lead_a = normalize_isu_text(txt_a, cfg)
        lead_b = normalize_isu_text(txt_b, cfg)
        if lead_a and lead_b:
            lead_cos = _cosine_dict(_char_ngrams(lead_a), _char_ngrams(lead_b))
            score = 0.85 * score + 0.15 * lead_cos

    # Bonus entitas spesifik
    if shared_nums:
        score += 0.14 * min(2, len(shared_nums))
    if shared_acrs and len(shared_all) >= 2:
        score += 0.10 * min(2, len(shared_acrs))
    if len(shared_spec) >= 3:
        score += 0.12
    elif len(shared_spec) == 1 and not shared_nums and not shared_acrs:
        # Hanya 1 kata spesifik tanpa angka/akronim bersama -> tahan di bawah ambang klaster
        score = min(score, 0.35)

    # Kedekatan tanggal sebagai komponen skor sekunder bila sudah lolos kemiripan substansi
    if score >= 0.30:
        d_a = item_a.get("_pub_date") or parse_article_date(item_a.get("published") or item_a.get("Tanggal") or item_a.get("tanggal_terakhir"))
        d_b = item_b.get("_pub_date") or parse_article_date(item_b.get("published") or item_b.get("Tanggal") or item_b.get("tanggal_terakhir"))
        if d_a is not None and d_b is not None:
            diff_d = abs((d_a - d_b).days)
            if diff_d == 0:
                score += 0.04
            elif diff_d == 1:
                score += 0.02
            elif diff_d > 7:
                score -= 0.03

    return float(min(1.0, max(0.0, score)))


def _build_idf_map(texts: list[str], alias_config: dict[str, Any] | None = None) -> dict[str, float]:
    cfg = alias_config or load_alias_config()
    n_docs = max(1, len(texts))
    df_counts: dict[str, int] = {}
    for txt in texts:
        for tok in extract_tokens(txt, cfg, exclude_generic=False):
            df_counts[tok] = df_counts.get(tok, 0) + 1
    idf: dict[str, float] = {}
    for tok, df in df_counts.items():
        idf[tok] = math.log((n_docs + 1.0) / (df + 1.0)) + 1.0
    return idf


def _crawl_kemenperin_listings_respectful(
    target_date_range: tuple[date, date] | None = None,
    max_pages: int = 3,
    delay_sec: float = 2.0,
) -> list[dict[str, Any]]:
    """
    Mengambil daftar judul/tanggal/url rilis dari https://www.kemenperin.go.id/siaran-pers secara sopan:
    - Cek robots.txt terlebih dahulu.
    - Beri jeda minimal delay_sec antar permintaan HTTP.
    - Berhenti lebih awal jika tanggal halaman sudah melewati batas bawah target_date_range.
    - Tidak mengunduh isi penuh tiap artikel (hanya metadata daftar rilis).
    """
    import time
    import urllib.robotparser
    from urllib.parse import urljoin
    import requests
    from bs4 import BeautifulSoup

    base = "https://www.kemenperin.go.id"
    headers = {
        "User-Agent": "MedMonAgroBot/1.0 (+internal media monitoring Kemenperin)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # 1. Hormati robots.txt
    allowed = True
    try:
        rob_resp = requests.get(f"{base}/robots.txt", headers=headers, timeout=15, verify=False)
        if rob_resp.status_code == 200 and rob_resp.text.strip():
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(rob_resp.text.splitlines())
            allowed = rp.can_fetch(headers["User-Agent"], f"{base}/siaran-pers")
        time.sleep(delay_sec)
    except Exception:
        pass
    if not allowed:
        return []

    collected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_item_urls: set[str] = set()
    current_url: str | None = f"{base}/siaran-pers"
    min_date = target_date_range[0] if target_date_range else None
    max_date = target_date_range[1] if target_date_range else None

    for page_idx in range(max_pages):
        if not current_url or current_url in seen_urls:
            break
        seen_urls.add(current_url)
        try:
            resp = requests.get(current_url, headers=headers, timeout=20, verify=False)
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            page_dates: list[date] = []
            for a in soup.find_all("a", href=True):
                href = str(a.get("href") or "")
                if "/artikel/" not in href:
                    continue
                title = clean_display_title(a.get_text(" ", strip=True))
                if not title or len(title) < 10 or title.upper().startswith("PENGUMUMAN "):
                    continue
                par = a.find_parent()
                par_txt = par.get_text(" ", strip=True) if par else ""
                m_d = re.search(r"(\d{2})/(\d{2})/(\d{4})", par_txt)
                pub_d: date | None = None
                if m_d:
                    try:
                        pub_d = date(int(m_d.group(3)), int(m_d.group(2)), int(m_d.group(1)))
                        page_dates.append(pub_d)
                    except ValueError:
                        pass
                if min_date and pub_d and pub_d < min_date:
                    continue
                if max_date and pub_d and pub_d > max_date:
                    continue
                full_url = urljoin(f"{base}/", href)
                if full_url in seen_item_urls:
                    continue
                seen_item_urls.add(full_url)
                collected.append({
                    "judul": title,
                    "tanggal": pub_d.strftime("%Y-%m-%d") if pub_d else "",
                    "url": full_url,
                    "nama_acara": "Siaran Pers Kemenperin",
                })

            if min_date and page_dates and max(page_dates) < min_date:
                break

            active_li = soup.find("li", class_="active")
            next_li = active_li.find_next_sibling("li") if active_li else None
            next_a = next_li.find("a") if next_li else None
            if next_a and next_a.get("href") and str(next_a.get("href")) != "#":
                nh = str(next_a.get("href"))
                current_url = urljoin(f"{base}/", nh)
            else:
                current_url = None

            if current_url and page_idx + 1 < max_pages:
                time.sleep(delay_sec)
        except Exception:
            break

    return collected


def load_rilis_kemenperin(
    csv_path: str | os.PathLike = DEFAULT_RILIS_CSV_PATH,
    cache_path: str | os.PathLike = DEFAULT_RILIS_CACHE_PATH,
    crawl_online: bool = False,
    target_date_range: tuple[date, date] | None = None,
    cache_ttl_hours: float = 6.0,
) -> list[dict[str, Any]]:
    """
    Memuat daftar rilis resmi Kemenperin dari CSV lokal dan cache disk.
    Jika crawl_online=True (dan cache kedaluwarsa atau belum mencakup target_date_range),
    mengambil siaran pers terbaru dari https://www.kemenperin.go.id/siaran-pers secara sopan.
    """
    import csv as _csv
    import time as _time

    by_key: dict[str, dict[str, Any]] = {}

    # 1. Baca dari CSV lokal
    p_csv = Path(csv_path)
    if p_csv.exists():
        try:
            with open(p_csv, mode="r", encoding="utf-8-sig") as f:
                for _idx, row in enumerate(_csv.DictReader(f), start=1):
                    judul = clean_display_title(str(row.get("judul") or row.get("title") or ""))
                    tgl = str(row.get("tanggal") or row.get("published") or "").strip()
                    url = str(row.get("url") or row.get("link") or "").strip()
                    acara = str(row.get("nama_acara") or "").strip()
                    if not judul:
                        continue
                    rid = str(row.get("id") or f"rilis_{hashlib.sha1(judul.lower().encode('utf-8')).hexdigest()[:10]}")
                    by_key[judul.lower()] = {
                        "id": rid,
                        "judul": judul,
                        "tanggal": tgl,
                        "url": url,
                        "nama_acara": acara,
                    }
        except Exception:
            pass

    # 2. Baca dari cache disk bila ada
    p_cache = Path(cache_path)
    cache_fresh = False
    if p_cache.exists():
        try:
            age_sec = _time.time() - p_cache.stat().st_mtime
            raw_cache = json.loads(p_cache.read_text(encoding="utf-8"))
            cached_range = raw_cache.get("date_range") if isinstance(raw_cache, dict) else None
            range_covered = target_date_range is None
            if (
                not range_covered
                and isinstance(cached_range, (list, tuple))
                and len(cached_range) == 2
                and target_date_range is not None
            ):
                c_min = parse_article_date(cached_range[0])
                c_max = parse_article_date(cached_range[1])
                if c_min and c_max and c_min <= target_date_range[0] and c_max >= target_date_range[1]:
                    range_covered = True
            cache_fresh = (age_sec < (cache_ttl_hours * 3600.0)) and range_covered
            cached_list = raw_cache.get("items", raw_cache) if isinstance(raw_cache, dict) else raw_cache
            if isinstance(cached_list, list):
                for item in cached_list:
                    judul = clean_display_title(str(item.get("judul") or item.get("title") or ""))
                    if judul and judul.lower() not in by_key:
                        rid = str(item.get("id") or f"rilis_{hashlib.sha1(judul.lower().encode('utf-8')).hexdigest()[:10]}")
                        by_key[judul.lower()] = {
                            "id": rid,
                            "judul": judul,
                            "tanggal": str(item.get("tanggal") or item.get("published") or ""),
                            "url": str(item.get("url") or item.get("link") or ""),
                            "nama_acara": str(item.get("nama_acara") or ""),
                        }
        except Exception:
            pass

    # 3. Crawl opsional dari www.kemenperin.go.id/siaran-pers dan prioritaskan metadata resmi live
    if crawl_online and not cache_fresh:
        try:
            crawled = _crawl_kemenperin_listings_respectful(target_date_range=target_date_range, max_pages=3)
            for c in crawled:
                judul = clean_display_title(str(c.get("judul") or ""))
                if not judul:
                    continue
                k = judul.lower()
                existing = by_key.get(k)
                rid = (
                    str(existing["id"])
                    if existing and existing.get("id")
                    else f"rilis_{hashlib.sha1(k.encode('utf-8')).hexdigest()[:10]}"
                )
                by_key[k] = {
                    "id": rid,
                    "judul": judul,
                    "tanggal": str(c.get("tanggal") or (existing.get("tanggal") if existing else "") or ""),
                    "url": str(c.get("url") or (existing.get("url") if existing else "") or ""),
                    "nama_acara": str(c.get("nama_acara") or (existing.get("nama_acara") if existing else "") or "Siaran Pers Kemenperin"),
                }
            p_cache.parent.mkdir(parents=True, exist_ok=True)
            cache_payload: dict[str, Any] = {
                "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "items": list(by_key.values()),
            }
            if target_date_range is not None:
                cache_payload["date_range"] = [target_date_range[0].isoformat(), target_date_range[1].isoformat()]
            p_cache.write_text(
                json.dumps(cache_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    return list(by_key.values())


class IsuRegistry:
    """
    Registri persisten isu aktif (hasil_scrapping/isu_registry.json).
    Menyimpan isu dari dua sumber:
    - 'rilis': rilis resmi Kemenperin (judul rilis = nama isu)
    - 'klaster': isu dari pengelompokan berita
    """

    def __init__(
        self,
        filepath: str | os.PathLike = DEFAULT_ISU_REGISTRY_PATH,
        rilis_max_days_before: int = DEFAULT_RILIS_MAX_DAYS_BEFORE,
        rilis_max_days_after: int = DEFAULT_RILIS_MAX_DAYS_AFTER,
        cluster_expiry_days: int = DEFAULT_CLUSTER_EXPIRY_DAYS,
    ):
        self.filepath = Path(filepath)
        self.rilis_max_days_before = int(rilis_max_days_before)
        self.rilis_max_days_after = int(rilis_max_days_after)
        self.cluster_expiry_days = int(cluster_expiry_days)
        self.issues: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.filepath.exists():
            return
        try:
            raw = json.loads(self.filepath.read_text(encoding="utf-8"))
            items = raw.get("issues", []) if isinstance(raw, dict) else raw
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get("isu_id"):
                        self.issues[str(it["isu_id"])] = it
        except Exception:
            pass

    def save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "issues": list(self.issues.values()),
        }
        self.filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def seed_releases(self, releases: list[dict[str, Any]], alias_config: dict[str, Any] | None = None) -> int:
        cfg = alias_config or load_alias_config()
        added = 0
        for r in releases:
            judul = clean_display_title(str(r.get("judul") or r.get("title") or ""))
            if not judul:
                continue
            rid = str(r.get("id") or f"rilis_{hashlib.sha1(judul.lower().encode('utf-8')).hexdigest()[:10]}")
            d_obj = parse_article_date(r.get("tanggal") or r.get("published"))
            d_str = d_obj.strftime("%Y-%m-%d") if d_obj else str(r.get("tanggal") or "")
            existing = self.issues.get(rid, {})
            self.issues[rid] = {
                "isu_id": rid,
                "isu": judul,
                "sumber_isu": "rilis",
                "tanggal_awal": d_str,
                "tanggal_terakhir": d_str,
                "nama_acara": str(r.get("nama_acara") or existing.get("nama_acara") or ""),
                "url": str(r.get("url") or existing.get("url") or ""),
                "_norm_title": normalize_isu_text(judul, cfg),
                "tone": existing.get("tone"),
                "tone_alasan": existing.get("tone_alasan", ""),
                "tone_keyakinan": existing.get("tone_keyakinan", ""),
                "evaluated_at": existing.get("evaluated_at"),
                "member_count_at_eval": int(existing.get("member_count_at_eval", 0) or 0),
                "member_count": int(existing.get("member_count", 0) or 0),
                "sample_titles": existing.get("sample_titles", [judul]),
                "matched_articles": existing.get("matched_articles", []),
            }
            added += 1
        return added

    def prune_expired(self, reference_date: date) -> int:
        to_delete = []
        for isu_id, info in self.issues.items():
            if info.get("sumber_isu") != "klaster":
                continue
            last_d = parse_article_date(info.get("tanggal_terakhir"))
            if last_d and (reference_date - last_d).days > self.cluster_expiry_days:
                to_delete.append(isu_id)
        for k in to_delete:
            del self.issues[k]
        return len(to_delete)

    def is_within_date_window(self, article_date: date | None, issue: dict[str, Any]) -> bool:
        if article_date is None:
            return True
        sumber = str(issue.get("sumber_isu") or "klaster")
        if sumber == "rilis":
            r_date = parse_article_date(issue.get("tanggal_awal") or issue.get("tanggal_terakhir"))
            if r_date is None:
                return True
            diff_days = (article_date - r_date).days
            # Default: rilis tidak lebih baru dari 1 hari setelah berita (diff >= -1)
            # dan berita tidak lebih dari 7 hari setelah rilis (diff <= 7)
            return (-self.rilis_max_days_before) <= diff_days <= self.rilis_max_days_after
        else:
            last_d = parse_article_date(issue.get("tanggal_terakhir") or issue.get("tanggal_awal"))
            if last_d is None:
                return True
            return abs((article_date - last_d).days) <= self.cluster_expiry_days


def _verify_gray_zone_match_with_llm(
    article: dict[str, Any],
    candidates: list[tuple[float, dict[str, Any]]],
) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not candidates:
        return None
    cand_payload = [
        {
            "id": c[1]["isu_id"],
            "isu": c[1]["isu"],
            "sumber_isu": c[1].get("sumber_isu", "klaster"),
            "tanggal": c[1].get("tanggal_terakhir") or c[1].get("tanggal_awal") or "",
        }
        for c in candidates[:3]
    ]
    art_title = clean_display_title(str(article.get("title") or article.get("Title") or ""))
    art_snippet = str(article.get("text") or "")[:300].strip()
    user_msg = json.dumps(
        {
            "berita": {"judul": art_title, "cuplikan": art_snippet},
            "kandidat_isu": cand_payload,
        },
        ensure_ascii=False,
    )
    resp_text, _used_model, _err = _ISU_MODEL_POOL.generate_deterministic(
        f"{MATCH_ISU_PROMPT}\n\n{user_msg}",
        timeout=45,
        max_attempts=3,
    )
    if not resp_text:
        return None
    m = re.search(r"\{[\s\S]*\}", resp_text)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0), strict=False)
        cocok = parsed.get("cocok")
        if cocok and str(cocok) in {c[1]["isu_id"] for c in candidates[:3]}:
            return str(cocok)
    except Exception:
        pass
    return None


def _select_representative_title(members: list[dict[str, Any]], sim_matrix: np.ndarray | None = None) -> str:
    if not members:
        return "Isu Industri Agro"
    if len(members) == 1:
        return clean_display_title(str(members[0].get("title") or members[0].get("Title") or ""))
    if sim_matrix is not None and sim_matrix.shape[0] == len(members):
        avg_sims = sim_matrix.mean(axis=1)
        best_idx = int(np.argmax(avg_sims))
        return clean_display_title(str(members[best_idx].get("title") or members[best_idx].get("Title") or ""))
    # Fallback deterministik: judul paling informatif (panjang moderat 45-95 karakter)
    cleaned = [clean_display_title(str(m.get("title") or m.get("Title") or "")) for m in members]
    cleaned = [c for c in cleaned if c]
    cleaned.sort(key=lambda s: (-len(set(s.lower().split())), len(s), s))
    return cleaned[0] if cleaned else "Isu Industri Agro"


def _label_clusters_with_llm(
    clusters: list[dict[str, Any]],
    use_ai: bool = False,
) -> dict[int, dict[str, Any]]:
    """
    Memberi nama isu untuk klaster berukuran >= 2 memakai ISU_LABEL_PROMPT (batch maksimal 5 klaster).
    Jika use_ai=False atau API tidak tersedia, gunakan judul representatif paling sentral secara deterministik.
    """
    out: dict[int, dict[str, Any]] = {}
    multi_clusters = [c for c in clusters if len(c["members"]) >= 2]
    for c in clusters:
        cid = c["cluster_idx"]
        out[cid] = {
            "isu": _select_representative_title(c["members"], c.get("sub_sim")),
            "outlier_ids": [],
        }

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not use_ai or not api_key or not multi_clusters:
        return out

    batch_size = 5
    for i in range(0, len(multi_clusters), batch_size):
        batch = multi_clusters[i : i + batch_size]
        req_items = []
        for c in batch:
            cid = c["cluster_idx"]
            berita_list = []
            for m in c["members"][:8]:
                entry: dict[str, Any] = {
                    "id": m["_internal_id"],
                    "judul": clean_display_title(str(m.get("title") or m.get("Title") or "")),
                }
                txt = str(m.get("text") or "").strip()[:250]
                if txt:
                    entry["cuplikan"] = txt
                berita_list.append(entry)
            req_items.append({"kelompok_id": cid, "berita": berita_list})

        prompt = f"{ISU_LABEL_PROMPT}\n\nInput:\n{json.dumps(req_items, ensure_ascii=False)}"
        resp_text, _model, _err = _ISU_MODEL_POOL.generate_deterministic(prompt, timeout=60, max_attempts=4)
        if not resp_text:
            continue
        m_json = re.search(r"\{[\s\S]*\}", resp_text)
        if not m_json:
            continue
        try:
            data = json.loads(m_json.group(0), strict=False)
            for h in data.get("hasil", []):
                kid = int(h.get("kelompok_id", -1))
                isu_str = clean_display_title(str(h.get("isu") or "").strip())
                outliers = [str(x) for x in (h.get("outlier_ids") or [])]
                if kid in out and isu_str:
                    out[kid] = {"isu": isu_str, "outlier_ids": outliers}
        except Exception:
            pass

    return out


def _compute_embedding_similarity_matrix(texts: list[str]) -> np.ndarray | None:
    """Menghitung matriks kemiripan cosine menggunakan models/gemini-embedding-001 bila tersedia."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not texts:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key, transport="rest")  # type: ignore
        all_embs: list[list[float]] = []
        chunk_size = 50
        for i in range(0, len(texts), chunk_size):
            batch = texts[i : i + chunk_size]
            res = genai.embed_content(
                model="models/gemini-embedding-001",
                content=batch,
                task_type="clustering",
            )
            embs = res.get("embedding") if isinstance(res, dict) else getattr(res, "embedding", None)
            if not embs or len(embs) != len(batch):
                return None
            # Single string edge case: wrap if 1D
            if isinstance(embs[0], (int, float)):
                embs = [embs]
            all_embs.extend(embs)
        if len(all_embs) != len(texts):
            return None
        mat = np.array(all_embs, dtype=np.float64)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normed = mat / norms
        sim = np.clip(normed @ normed.T, 0.0, 1.0)
        return sim
    except Exception:
        return None


def _upsert_issue_member(issue: dict[str, Any], item: dict[str, Any], score: float) -> bool:
    """Menambahkan anggota baru ke issue secara idempoten (berbasis canonical_url atau judul bersih)."""
    matched_list = issue.setdefault("matched_articles", [])
    link = str(item.get("resolved_url") or item.get("link") or item.get("Link Website") or "").strip()
    title = str(item.get("_clean_title") or clean_display_title(str(item.get("title") or item.get("Title") or ""))).strip()
    can_u = canonical_url(link) if link else ""
    dedup_key = can_u or title.lower()
    existing_keys = {
        (canonical_url(str(m.get("link") or "")) if m.get("link") else "") or str(m.get("title") or "").strip().lower()
        for m in matched_list
    }
    if dedup_key and dedup_key in existing_keys:
        return False

    snippet = str(item.get("text") or item.get("isi") or "").strip()[:400]
    matched_list.append({
        "id": item.get("_internal_id") or item.get("id"),
        "title": title,
        "link": link,
        "canonical_url": can_u,
        "media_name": str(item.get("media_name") or item.get("Media Name") or ""),
        "tanggal": str(item.get("published") or item.get("Tanggal") or ""),
        "skor": round(score, 4),
    })
    sample_titles = issue.setdefault("sample_titles", [])
    if title and title not in sample_titles and len(sample_titles) < 12:
        sample_titles.append(title)
    if snippet:
        sample_snips = issue.setdefault("sample_snippets", [])
        if snippet not in sample_snips and len(sample_snips) < 2:
            sample_snips.append(snippet)
    issue["member_count"] = max(int(issue.get("member_count", 0) or 0), len(matched_list))
    return True


def write_isu_log(
    items: list[dict[str, Any]],
    log_path: str | os.PathLike | None = DEFAULT_LOG_ISU_PATH,
) -> None:
    """Menulis entri hasil penetapan isu ke log_isu.jsonl."""
    if not log_path or not items:
        return
    try:
        lp = Path(log_path)
        lp.parent.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(lp, "a", encoding="utf-8") as f:
            for it in items:
                log_entry = {
                    "id": it.get("id"),
                    "title": it.get("title") or it.get("Title") or "",
                    "isu_id": it.get("isu_id", ""),
                    "isu": it.get("isu", ""),
                    "sumber_isu": it.get("sumber_isu", "klaster"),
                    "skor": it.get("skor_isu", 0.0),
                    "margin": it.get("margin_isu", 0.0),
                    "timestamp": now_str,
                }
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def assign_and_cluster_issues(
    articles: list[dict[str, Any]],
    registry: IsuRegistry | None = None,
    method: str = "tfidf",
    use_ai: bool = False,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    gray_zone_low: float = DEFAULT_GRAY_ZONE_LOW,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    cluster_sim_threshold: float = DEFAULT_CLUSTER_SIM_THRESHOLD,
    log_path: str | os.PathLike | None = DEFAULT_LOG_ISU_PATH,
    coverage_path: str | os.PathLike | None = DEFAULT_COVERAGE_RILIS_PATH,
    label_with_llm: bool | None = None,
) -> list[dict[str, Any]]:
    """
    Alur utama Fase 1:
    1. Normalisasi tiap berita (tanpa menyentuh Keywords, Spokesperson, Unit Eselon).
    2. Cocokkan berita ke isu aktif di IsuRegistry (memperhatikan jendela tanggal, skor, margin).
    3. Kelompokkan berita yang belum cocok secara deterministik menjadi isu klaster baru.
    4. Perbarui registri isu aktif, simpan log_isu.jsonl dan coverage_rilis.json.
    """
    if not articles:
        return []

    cfg = load_alias_config()
    reg = registry if registry is not None else IsuRegistry()

    # Siapkan salinan kerja dengan _internal_id dan normalisasi
    work_items: list[dict[str, Any]] = []
    for idx, art in enumerate(articles):
        item = dict(art)
        raw_t = str(item.get("title") or item.get("Title") or "")
        item["_orig_pos"] = idx
        item["_internal_id"] = str(item.get("id") if item.get("id") is not None else f"row_{idx + 1}")
        item["_clean_title"] = clean_display_title(raw_t)
        item["_norm_title"] = normalize_isu_text(raw_t, cfg)
        item["_pub_date"] = parse_article_date(item.get("published") or item.get("Tanggal"))
        work_items.append(item)

    # Bangun kamus IDF gabungan dari artikel + isu registri
    all_norm_texts = [w["_norm_title"] for w in work_items if w["_norm_title"]]
    for iss in reg.issues.values():
        nt = iss.get("_norm_title") or normalize_isu_text(str(iss.get("isu") or ""), cfg)
        iss["_norm_title"] = nt
        if nt:
            all_norm_texts.append(nt)
    idf_map = _build_idf_map(all_norm_texts, cfg)

    # Urutkan secara kanonik terlebih dahulu agar 100% deterministik terlepas dari urutan input
    sorted_items = sorted(
        work_items,
        key=lambda x: (x["_norm_title"], x["_clean_title"], x["_internal_id"]),
    )

    # Pangkas isu klaster yang sudah kedaluwarsa (> 14 hari dari tanggal maksimum batch)
    valid_dates = [w["_pub_date"] for w in sorted_items if w["_pub_date"] is not None]
    if valid_dates:
        reg.prune_expired(max(valid_dates))

    matched_results: dict[int, dict[str, Any]] = {}
    unmatched_items: list[dict[str, Any]] = []

    # Snapshot isu aktif sebelum batch klaster baru dibuat
    active_issues_list = sorted(reg.issues.values(), key=lambda x: str(x.get("isu_id") or ""))

    for item in sorted_items:
        art_date = item["_pub_date"]
        scored_cands: list[tuple[float, dict[str, Any]]] = []
        for iss in active_issues_list:
            if not reg.is_within_date_window(art_date, iss):
                continue
            sim = compute_pair_similarity(item, iss, method=method, alias_config=cfg, idf_map=idf_map)
            # Syarat tambahan pencocokan rilis: wajib berbagi minimal 2 token spesifik (non-generik) atau 1 angka/akronim + 1 token spesifik
            spec_item = extract_tokens(item["_norm_title"], cfg, exclude_generic=True)
            spec_iss = extract_tokens(iss["_norm_title"], cfg, exclude_generic=True)
            shared_spec = spec_item.intersection(spec_iss)
            ent_item = extract_entities(item["_norm_title"])
            ent_iss = extract_entities(iss["_norm_title"])
            shared_ent = ent_item["numbers"].intersection(ent_iss["numbers"]) | ent_item["acronyms"].intersection(ent_iss["acronyms"])
            if len(shared_spec) < 2 and not (len(shared_spec) >= 1 and len(shared_ent) >= 1):
                sim = min(sim, 0.30)
            scored_cands.append((sim, iss))

        scored_cands.sort(key=lambda pair: (-pair[0], str(pair[1].get("isu_id") or "")))
        top1_score = scored_cands[0][0] if scored_cands else 0.0
        top2_score = scored_cands[1][0] if len(scored_cands) >= 2 else 0.0
        margin = round(top1_score - top2_score, 4)

        chosen_issue: dict[str, Any] | None = None
        if scored_cands and top1_score >= match_threshold and (len(scored_cands) == 1 or margin >= margin_threshold):
            chosen_issue = scored_cands[0][1]
        elif use_ai and scored_cands and gray_zone_low <= top1_score < match_threshold:
            chosen_id = _verify_gray_zone_match_with_llm(item, scored_cands)
            if chosen_id and chosen_id in reg.issues:
                chosen_issue = reg.issues[chosen_id]

        if chosen_issue is not None:
            isu_id = str(chosen_issue["isu_id"])
            isu_name = str(chosen_issue["isu"])
            sumber = str(chosen_issue.get("sumber_isu") or "klaster")
            # Perbarui tanggal terakhir & daftar artikel pada isu registri (idempoten)
            if art_date:
                d_str = art_date.strftime("%Y-%m-%d")
                prev_last = str(chosen_issue.get("tanggal_terakhir") or "")
                if not prev_last or d_str > prev_last:
                    chosen_issue["tanggal_terakhir"] = d_str
            _upsert_issue_member(chosen_issue, item, top1_score)

            out_item = dict(item)
            out_item["isu_id"] = isu_id
            out_item["isu"] = isu_name
            out_item["Isu"] = isu_name
            out_item["sumber_isu"] = sumber
            out_item["skor_isu"] = round(top1_score, 4)
            out_item["margin_isu"] = margin
            matched_results[item["_orig_pos"]] = out_item
        else:
            item["_best_active_score"] = round(top1_score, 4)
            item["_best_active_margin"] = margin
            unmatched_items.append(item)

    # Tahap 2: Klasterisasi sisa berita yang belum cocok ke registri aktif
    n_unm = len(unmatched_items)
    if n_unm == 1:
        only = unmatched_items[0]
        isu_name = only["_clean_title"] or "Isu Industri Agro"
        cid_hash = hashlib.sha1(only["_norm_title"].encode("utf-8")).hexdigest()[:10]
        isu_id = f"klaster_{cid_hash}"
        d_str = only["_pub_date"].strftime("%Y-%m-%d") if only["_pub_date"] else datetime.now().strftime("%Y-%m-%d")
        existing = reg.issues.get(isu_id, {})
        reg.issues[isu_id] = {
            "isu_id": isu_id,
            "isu": isu_name,
            "sumber_isu": "klaster",
            "tanggal_awal": existing.get("tanggal_awal") or d_str,
            "tanggal_terakhir": max(str(existing.get("tanggal_terakhir") or ""), d_str),
            "_norm_title": only["_norm_title"],
            "tone": existing.get("tone"),
            "tone_alasan": existing.get("tone_alasan", ""),
            "tone_keyakinan": existing.get("tone_keyakinan", ""),
            "evaluated_at": existing.get("evaluated_at"),
            "member_count_at_eval": int(existing.get("member_count_at_eval", 0) or 0),
            "member_count": int(existing.get("member_count", 0) or 0),
            "sample_titles": existing.get("sample_titles", [isu_name]),
            "sample_snippets": existing.get("sample_snippets", []),
            "matched_articles": existing.get("matched_articles", []),
        }
        _upsert_issue_member(reg.issues[isu_id], only, 1.0)
        out_item = dict(only)
        out_item["isu_id"] = isu_id
        out_item["isu"] = isu_name
        out_item["Isu"] = isu_name
        out_item["sumber_isu"] = "klaster"
        out_item["skor_isu"] = 1.0
        out_item["margin_isu"] = 1.0
        matched_results[only["_orig_pos"]] = out_item

    elif n_unm >= 2:
        sim_mat = np.eye(n_unm, dtype=np.float64)
        emb_mat = None
        if method in ("embedding", "embedding_pure"):
            emb_mat = _compute_embedding_similarity_matrix([u["_clean_title"] for u in unmatched_items])

        for i in range(n_unm):
            for j in range(i + 1, n_unm):
                base_sim = compute_pair_similarity(
                    unmatched_items[i],
                    unmatched_items[j],
                    method="rapidfuzz" if method == "rapidfuzz" else "tfidf",
                    alias_config=cfg,
                    idf_map=idf_map,
                )
                if method == "embedding_pure" and emb_mat is not None:
                    s_val = float(emb_mat[i, j])
                elif emb_mat is not None and base_sim > 0.20:
                    s_val = 0.55 * base_sim + 0.45 * float(emb_mat[i, j])
                else:
                    s_val = base_sim
                sim_mat[i, j] = s_val
                sim_mat[j, i] = s_val

        # Konversi ke jarak untuk Agglomerative Clustering
        dist_mat = np.clip(1.0 - sim_mat, 0.0, 1.0)
        np.fill_diagonal(dist_mat, 0.0)
        condensed = squareform(dist_mat, checks=False)

        # Gunakan average linkage, lalu konsolidasikan pasangan yang terhubung kuat (>= cluster_sim_threshold)
        Z = linkage(condensed, method="average")
        raw_labels = fcluster(Z, t=1.0 - cluster_sim_threshold, criterion="distance")

        # Konsolidasi jembatan antar sub-klaster yang memiliki kemiripan pasangan >= 0.44
        cluster_groups: dict[int, list[int]] = {}
        for idx_u, lbl in enumerate(raw_labels):
            cluster_groups.setdefault(int(lbl), []).append(idx_u)

        group_keys = sorted(cluster_groups.keys())
        merged_flag = True
        while merged_flag and len(group_keys) > 1:
            merged_flag = False
            for a_idx in range(len(group_keys)):
                for b_idx in range(a_idx + 1, len(group_keys)):
                    ga = cluster_groups[group_keys[a_idx]]
                    gb = cluster_groups[group_keys[b_idx]]
                    sub_sims = [sim_mat[i, j] for i in ga for j in gb]
                    max_bridge = max(sub_sims)
                    mean_bridge = sum(sub_sims) / len(sub_sims)
                    if max_bridge >= 0.44 and mean_bridge >= 0.28:
                        cluster_groups[group_keys[a_idx]] = sorted(ga + gb)
                        del cluster_groups[group_keys[b_idx]]
                        group_keys = sorted(cluster_groups.keys())
                        merged_flag = True
                        break
                if merged_flag:
                    break

        cluster_Input_list = []
        for c_idx, g_key in enumerate(sorted(cluster_groups.keys()), start=1):
            member_indices = cluster_groups[g_key]
            members = [unmatched_items[m_i] for m_i in member_indices]
            sub_sim = sim_mat[np.ix_(member_indices, member_indices)]
            cluster_Input_list.append({
                "cluster_idx": c_idx,
                "indices": member_indices,
                "members": members,
                "sub_sim": sub_sim,
            })

        do_llm_label = use_ai if label_with_llm is None else bool(label_with_llm)
        label_map = _label_clusters_with_llm(cluster_Input_list, use_ai=do_llm_label)

        # Pisahkan outlier yang ditandai oleh ISU_LABEL_PROMPT menjadi klaster tunggal tersendiri
        final_clusters: list[dict[str, Any]] = []
        for c_info in cluster_Input_list:
            c_idx = c_info["cluster_idx"]
            lbl_res = label_map.get(c_idx, {})
            outliers = set(lbl_res.get("outlier_ids") or [])
            if not outliers or len(c_info["members"]) <= 1:
                c_info["isu_name_override"] = lbl_res.get("isu")
                final_clusters.append(c_info)
                continue
            kept_pairs = [
                (idx_global, m) for idx_global, m in zip(c_info["indices"], c_info["members"])
                if m["_internal_id"] not in outliers
            ]
            out_pairs = [
                (idx_global, m) for idx_global, m in zip(c_info["indices"], c_info["members"])
                if m["_internal_id"] in outliers
            ]
            if kept_pairs:
                k_idx = [p[0] for p in kept_pairs]
                k_mem = [p[1] for p in kept_pairs]
                final_clusters.append({
                    "indices": k_idx,
                    "members": k_mem,
                    "sub_sim": sim_mat[np.ix_(k_idx, k_idx)],
                    "isu_name_override": lbl_res.get("isu"),
                })
            for o_idx, o_mem in out_pairs:
                final_clusters.append({
                    "indices": [o_idx],
                    "members": [o_mem],
                    "sub_sim": sim_mat[np.ix_([o_idx], [o_idx])],
                    "isu_name_override": o_mem["_clean_title"] or "Isu Industri Agro",
                })

        for c_info in final_clusters:
            members = c_info["members"]
            member_indices = c_info["indices"]
            isu_name = c_info.get("isu_name_override") or _select_representative_title(members, c_info["sub_sim"])

            sig_norms = sorted(m["_norm_title"] for m in members)
            cid_hash = hashlib.sha1("|".join(sig_norms).encode("utf-8")).hexdigest()[:10]
            isu_id = f"klaster_{cid_hash}"

            m_dates = [m["_pub_date"] for m in members if m["_pub_date"] is not None]
            d_min = min(m_dates).strftime("%Y-%m-%d") if m_dates else datetime.now().strftime("%Y-%m-%d")
            d_max = max(m_dates).strftime("%Y-%m-%d") if m_dates else d_min

            existing = reg.issues.get(isu_id, {})
            reg.issues[isu_id] = {
                "isu_id": isu_id,
                "isu": isu_name,
                "sumber_isu": "klaster",
                "tanggal_awal": existing.get("tanggal_awal") or d_min,
                "tanggal_terakhir": max(str(existing.get("tanggal_terakhir") or ""), d_max),
                "_norm_title": normalize_isu_text(isu_name, cfg),
                "tone": existing.get("tone"),
                "tone_alasan": existing.get("tone_alasan", ""),
                "tone_keyakinan": existing.get("tone_keyakinan", ""),
                "evaluated_at": existing.get("evaluated_at"),
                "member_count_at_eval": int(existing.get("member_count_at_eval", 0) or 0),
                "member_count": int(existing.get("member_count", 0) or 0),
                "sample_titles": existing.get("sample_titles", []),
                "sample_snippets": existing.get("sample_snippets", []),
                "matched_articles": existing.get("matched_articles", []),
            }

            for local_pos, m_item in enumerate(members):
                global_i = member_indices[local_pos]
                if len(members) > 1:
                    same_row_sims = [sim_mat[global_i, global_j] for global_j in member_indices if global_j != global_i]
                    in_score = float(max(same_row_sims)) if same_row_sims else 1.0
                else:
                    in_score = 1.0
                other_sims = [sim_mat[global_i, k] for k in range(n_unm) if k not in member_indices]
                out_score = float(max(other_sims)) if other_sims else 0.0
                margin = round(max(0.0, in_score - out_score), 4)

                _upsert_issue_member(reg.issues[isu_id], m_item, in_score)

                out_item = dict(m_item)
                out_item["isu_id"] = isu_id
                out_item["isu"] = isu_name
                out_item["Isu"] = isu_name
                out_item["sumber_isu"] = "klaster"
                out_item["skor_isu"] = round(in_score, 4)
                out_item["margin_isu"] = margin
                matched_results[m_item["_orig_pos"]] = out_item

    # Simpan registri isu aktif
    try:
        reg.save()
    except Exception:
        pass

    # Kembalikan sesuai urutan asli input articles dan bersihkan field internal sementara
    final_output: list[dict[str, Any]] = []
    for idx in range(len(articles)):
        res_it = matched_results[idx]
        for k_tmp in list(res_it.keys()):
            if k_tmp.startswith("_"):
                res_it.pop(k_tmp, None)
        final_output.append(res_it)

    # Tulis log_isu.jsonl
    write_isu_log(final_output, log_path=log_path)

    # Tulis coverage_rilis.json
    if coverage_path:
        try:
            cp = Path(coverage_path)
            cp.parent.mkdir(parents=True, exist_ok=True)
            rilis_cov = {}
            for isu_id, iss in reg.issues.items():
                if iss.get("sumber_isu") == "rilis":
                    m_arts = iss.get("matched_articles", [])
                    rilis_cov[isu_id] = {
                        "id": isu_id,
                        "judul_rilis": iss.get("isu", ""),
                        "tanggal_rilis": iss.get("tanggal_awal", ""),
                        "nama_acara": iss.get("nama_acara", ""),
                        "url_rilis": iss.get("url", ""),
                        "status": "Terbit",
                        "jumlah_coverage": len(m_arts),
                        "coverage_label": f"{len(m_arts)} berita" if m_arts else "belum tercatat",
                        "berita": m_arts,
                    }
            cp.write_text(json.dumps(rilis_cov, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return final_output
