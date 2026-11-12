"""
stable.py
Utilitas determinisme pipeline:
- Canonicalization URL (hapus parameter tracking & normalisasi host/path)
- DecisionCache persisten berbasis SHA256(canonical_url | stage | prompt_version | model)
- DateSnapshotStore per tanggal (retensi 30 hari) + union kandidat lintas jam run
- Pemangkasan ukuran cache agar tetap ramping di GitHub Actions
"""

from datetime import date, datetime, timedelta
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

DEFAULT_DECISION_CACHE_FILE = os.path.join("hasil_scrapping", "cache_decisions.json")
DEFAULT_SNAPSHOT_DIR = os.path.join("hasil_scrapping", "snapshots")
DEFAULT_SNAPSHOT_RETENTION_DAYS = 30
DEFAULT_DECISION_CACHE_MAX_ENTRIES = 15000
DEFAULT_DECODE_CACHE_MAX_ENTRIES = 25000

_TRACKING_PARAM_PREFIXES = ("utm_", "gaa_", "mtm_", "pk_", "hsa_")
_TRACKING_PARAM_EXACT = {
    "fbclid", "gclid", "dclid", "yclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "srsltid", "ref", "oc", "hl", "gl", "ceid", "_ga", "_gl",
    "spm", "si", "feature", "guccounter", "guce_referrer", "guce_referrer_sig",
}


def canonical_url(url: str) -> str:
    """
    Menormalisasi URL menjadi bentuk kanonik stabil untuk deduplikasi & cache key:
    - Hapus pembungkus =HYPERLINK(...)
    - Lowercase scheme/host, samakan http->https, hapus prefix www.
    - Normalisasi news.google.com/rss/articles/<id> & youtu.be/<id>
    - Hapus fragment (#) dan parameter tracking (utm_*, fbclid, gclid, dll)
    - Urutkan query parameter tersisa & hapus trailing slash pada path
    """
    if not url or not isinstance(url, str):
        return ""
    raw = url.strip()
    m = re.match(r'^=HYPERLINK\("([^"]+)"', raw, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
    if not raw:
        return ""

    try:
        parsed = urlparse(raw)
    except Exception:
        return raw.split("?")[0].rstrip("/").lower()

    host = (parsed.netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return raw.split("?")[0].rstrip("/").lower()

    path = parsed.path or ""
    q_pairs = parse_qsl(parsed.query or "", keep_blank_values=False)

    # Normalisasi khusus Google News RSS
    if host == "news.google.com":
        parts = [p for p in path.split("/") if p]
        for idx, seg in enumerate(parts[:-1]):
            if seg in ("articles", "read") and parts[idx + 1]:
                return f"https://news.google.com/articles/{parts[idx + 1]}"
        return f"https://news.google.com{path.rstrip('/')}" if path.rstrip("/") else "https://news.google.com"

    # Normalisasi khusus YouTube
    if host == "youtu.be":
        vid = path.strip("/").split("/")[0]
        if vid:
            return f"https://youtube.com/watch?v={vid}"
    if host in ("youtube.com", "m.youtube.com"):
        host = "youtube.com"
        if path.startswith("/shorts/"):
            vid = path.split("/shorts/", 1)[1].strip("/").split("/")[0]
            if vid:
                return f"https://youtube.com/watch?v={vid}"

    # Hapus parameter tracking
    kept_q = []
    for k, v in q_pairs:
        kl = k.lower()
        if kl in _TRACKING_PARAM_EXACT or any(kl.startswith(p) for p in _TRACKING_PARAM_PREFIXES):
            continue
        kept_q.append((k, v))
    kept_q.sort()

    clean_path = re.sub(r"/{2,}", "/", path).rstrip("/")
    if not clean_path:
        clean_path = "/"

    return urlunparse(("https", host, clean_path, "", urlencode(kept_q), ""))


class DecisionCache:
    """
    Cache keputusan LLM persisten berbasis SHA256(canonical_url | stage | prompt_version | model).
    Memastikan artikel yang sama selalu mendapat keputusan, tone, dan flag yang identik antar run.
    """

    def __init__(
        self,
        filepath: str | None = None,
        max_entries: int = DEFAULT_DECISION_CACHE_MAX_ENTRIES,
        time_fn=None,
    ):
        self.filepath = filepath or os.environ.get("DECISION_CACHE_FILE") or DEFAULT_DECISION_CACHE_FILE
        self.max_entries = max(100, int(max_entries))
        self._time_fn = time_fn or time.time
        self._lock = threading.RLock()
        self._data: dict[str, dict] = {}
        self._loaded_mtime: float = -1.0
        self._dirty = False
        self.load()

    @staticmethod
    def make_key(url: str, stage: str, prompt_version: str, model_name: str = "") -> str:
        can = canonical_url(url) or str(url or "").strip().lower()
        payload = f"{can}|{stage.strip()}|{prompt_version.strip()}|{model_name.strip()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_locked(self) -> None:
        if not os.path.exists(self.filepath):
            self._loaded_mtime = 0.0
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                merged = {}
                for k, v in raw.items():
                    if isinstance(k, str) and isinstance(v, dict) and "value" in v:
                        merged[k] = v
                for k, v in self._data.items():
                    merged.setdefault(k, v)
                self._data = merged
            self._loaded_mtime = os.path.getmtime(self.filepath)
        except Exception:
            pass

    def _reload_if_newer_locked(self) -> None:
        try:
            if os.path.exists(self.filepath):
                mtime = os.path.getmtime(self.filepath)
                if mtime > self._loaded_mtime:
                    self._load_locked()
        except Exception:
            pass

    def _prune_locked(self) -> int:
        excess = len(self._data) - self.max_entries
        if excess <= 0:
            return 0
        # Urutkan dari timestamp paling lama
        ordered = sorted(
            self._data.items(),
            key=lambda kv: float(kv[1].get("ts", 0.0) or 0.0),
        )
        for k, _ in ordered[:excess]:
            del self._data[k]
        self._dirty = True
        return excess

    def load(self) -> None:
        with self._lock:
            self._load_locked()

    def get(self, url: str, stage: str, prompt_version: str, model_name: str = "") -> dict | None:
        if not url:
            return None
        key = self.make_key(url, stage, prompt_version, model_name)
        with self._lock:
            self._reload_if_newer_locked()
            entry = self._data.get(key)
            if isinstance(entry, dict) and isinstance(entry.get("value"), dict):
                return dict(entry["value"])
        return None

    def set(
        self,
        url: str,
        stage: str,
        prompt_version: str,
        model_name: str,
        value: dict,
    ) -> bool:
        if not url or not isinstance(value, dict):
            return False
        key = self.make_key(url, stage, prompt_version, model_name)
        with self._lock:
            self._data[key] = {
                "ts": float(self._time_fn()),
                "url": canonical_url(url),
                "stage": stage,
                "prompt_version": prompt_version,
                "model": model_name,
                "value": dict(value),
            }
            self._prune_locked()
            self._dirty = True
        return True

    def size(self) -> int:
        with self._lock:
            return len(self._data)

    def save(self, force: bool = False) -> None:
        with self._lock:
            self._prune_locked()
            if not force and not self._dirty:
                return
            snapshot = dict(self._data)
            target = self.filepath
            out_dir = os.path.dirname(target)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            tmp_path = f"{target}.tmp.{os.getpid()}.{threading.get_ident()}"
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, target)
                self._loaded_mtime = os.path.getmtime(target)
                self._dirty = False
            except Exception as e:
                print(f"  [DecisionCache Warning] Gagal menyimpan {target}: {e}", flush=True)
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass


_DEFAULT_DECISION_CACHE: DecisionCache | None = None
_DECISION_CACHE_LOCK = threading.Lock()


def get_decision_cache() -> DecisionCache:
    global _DEFAULT_DECISION_CACHE
    with _DECISION_CACHE_LOCK:
        target = os.environ.get("DECISION_CACHE_FILE") or DEFAULT_DECISION_CACHE_FILE
        if _DEFAULT_DECISION_CACHE is None or _DEFAULT_DECISION_CACHE.filepath != target:
            _DEFAULT_DECISION_CACHE = DecisionCache(target)
        return _DEFAULT_DECISION_CACHE


def save_decision_cache(force: bool = False) -> None:
    if _DEFAULT_DECISION_CACHE is not None:
        _DEFAULT_DECISION_CACHE.save(force=force)


def _merge_article_pair(existing: dict, incoming: dict) -> dict:
    """Menggabungkan dua salinan artikel ber-URL kanonik sama dengan memilih teks terlengkap dan menggabungkan keyword."""
    best = dict(existing)
    if len(str(incoming.get("text") or "")) > len(str(existing.get("text") or "")):
        best = dict(incoming)
        # Pertahankan keyword gabungan & override metadata non-kosong
        kw_prev = str(existing.get("keyword") or existing.get("Keywords") or "")
        kw_new = str(best.get("keyword") or best.get("Keywords") or "")
    else:
        kw_prev = str(existing.get("keyword") or existing.get("Keywords") or "")
        kw_new = str(incoming.get("keyword") or incoming.get("Keywords") or "")

    merged_parts = []
    seen_kw = set()
    for part in (kw_prev + "," + kw_new).split(","):
        p = part.strip()
        if p and p.lower() not in seen_kw:
            seen_kw.add(p.lower())
            merged_parts.append(p)
    if merged_parts:
        best["keyword"] = ", ".join(merged_parts)
    if not best.get("published") and incoming.get("published"):
        best["published"] = incoming.get("published")
    if not best.get("media_name") and incoming.get("media_name"):
        best["media_name"] = incoming.get("media_name")
    return best


def union_articles_by_canonical_url(articles_a: list[dict], articles_b: list[dict]) -> list[dict]:
    """Union deterministik dua daftar artikel berdasarkan canonical_url."""
    by_can: dict[str, dict] = {}
    order: list[str] = []
    for art in (articles_a or []) + (articles_b or []):
        if not isinstance(art, dict):
            continue
        raw_url = str(art.get("resolved_url") or art.get("link") or art.get("Link Website") or "").strip()
        if not raw_url:
            continue
        can = canonical_url(raw_url)
        if not can:
            continue
        if can not in by_can:
            by_can[can] = dict(art)
            order.append(can)
        else:
            by_can[can] = _merge_article_pair(by_can[can], art)
    return [by_can[k] for k in order]


class DateSnapshotStore:
    """Menyimpan dan melakukan union snapshot kandidat artikel per tanggal (retensi default 30 hari)."""

    def __init__(
        self,
        snapshot_dir: str | None = None,
        retention_days: int = DEFAULT_SNAPSHOT_RETENTION_DAYS,
        today_fn=None,
    ):
        self.snapshot_dir = snapshot_dir or os.environ.get("SNAPSHOT_DIR") or DEFAULT_SNAPSHOT_DIR
        self.retention_days = max(1, int(retention_days))
        self._today_fn = today_fn or date.today

    def path_for_date(self, date_str: str) -> str:
        clean = str(date_str).strip()[:10]
        return os.path.join(self.snapshot_dir, f"{clean}.json")

    def prune_old_snapshots(self) -> int:
        """Menghapus file snapshot yang lebih tua dari `retention_days` (default 30 hari)."""
        if not os.path.isdir(self.snapshot_dir):
            return 0
        cutoff = self._today_fn() - timedelta(days=self.retention_days)
        removed = 0
        for fname in os.listdir(self.snapshot_dir):
            if not fname.endswith(".json"):
                continue
            stem = fname[:-5]
            try:
                fdate = datetime.strptime(stem[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            if fdate < cutoff:
                try:
                    os.remove(os.path.join(self.snapshot_dir, fname))
                    removed += 1
                except Exception:
                    pass
        return removed

    def load_day(self, date_str: str) -> list[dict]:
        path = self.path_for_date(date_str)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("articles"), list):
                return data["articles"]
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def save_day(self, date_str: str, articles: list[dict]) -> list[dict]:
        """Menyimpan union snapshot existing + articles ke snapshots/YYYY-MM-DD.json dan memangkas file >30 hari."""
        existing = self.load_day(date_str)
        merged = union_articles_by_canonical_url(existing, articles)
        os.makedirs(self.snapshot_dir, exist_ok=True)
        path = self.path_for_date(date_str)
        tmp_path = f"{path}.tmp.{os.getpid()}"
        payload = {
            "date": str(date_str).strip()[:10],
            "updated_at": datetime.now().isoformat(),
            "count": len(merged),
            "articles": merged,
        }
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp_path, path)
        except Exception as e:
            print(f"  [Snapshot Warning] Gagal menyimpan snapshot {path}: {e}", flush=True)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
        self.prune_old_snapshots()
        return merged

    def merge_range_with_snapshots(
        self,
        start_d: date,
        end_d: date,
        current_articles: list[dict],
        parse_date_fn=None,
    ) -> list[dict]:
        """
        Memuat snapshot untuk setiap tanggal pada rentang [start_d, end_d],
        menggabungkannya dengan current_articles per tanggal, menyimpan ulang snapshot,
        lalu mengembalikan union keseluruhan yang deterministik.
        """
        if end_d < start_d:
            start_d, end_d = end_d, start_d

        bucket: dict[str, list[dict]] = {}
        curr = start_d
        while curr <= end_d:
            bucket[curr.isoformat()] = []
            curr += timedelta(days=1)

        fallback_day = start_d.isoformat()
        for art in current_articles or []:
            if not isinstance(art, dict):
                continue
            day_key = fallback_day
            if parse_date_fn is not None:
                try:
                    dt = parse_date_fn(art.get("published") or art.get("Tanggal"))
                    if dt is not None:
                        d_str = dt.date().isoformat()
                        if d_str in bucket:
                            day_key = d_str
                except Exception:
                    pass
            bucket.setdefault(day_key, []).append(art)

        all_merged: list[dict] = []
        for day_key in sorted(bucket.keys()):
            merged_day = self.save_day(day_key, bucket[day_key])
            all_merged = union_articles_by_canonical_url(all_merged, merged_day)
        return all_merged


def prune_pipeline_caches(
    base_dir: str = "hasil_scrapping",
    retention_days: int = DEFAULT_SNAPSHOT_RETENTION_DAYS,
    decode_max_entries: int = DEFAULT_DECODE_CACHE_MAX_ENTRIES,
    decision_max_entries: int = DEFAULT_DECISION_CACHE_MAX_ENTRIES,
    recheck_max_entries: int = DEFAULT_DECISION_CACHE_MAX_ENTRIES,
) -> dict:
    """Memangkas snapshot >30 hari dan membatasi ukuran cache JSON untuk persistensi GitHub Actions."""
    snap_dir = os.path.join(base_dir, "snapshots")
    snap_removed = DateSnapshotStore(snapshot_dir=snap_dir, retention_days=retention_days).prune_old_snapshots()

    dec_path = os.path.join(base_dir, "cache_decisions.json")
    if os.path.exists(dec_path):
        dc = DecisionCache(filepath=dec_path, max_entries=decision_max_entries)
        dc.save(force=True)

    decode_path = os.path.join(base_dir, "cache_decode.json")
    if os.path.exists(decode_path):
        try:
            with open(decode_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and len(raw) > decode_max_entries:
                keys = list(raw.keys())[-decode_max_entries:]
                trimmed = {k: raw[k] for k in keys}
                with open(decode_path, "w", encoding="utf-8") as f:
                    json.dump(trimmed, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    recheck_path = os.path.join(base_dir, "cache_ai_recheck.json")
    if os.path.exists(recheck_path):
        try:
            with open(recheck_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and len(raw) > recheck_max_entries:
                keys = list(raw.keys())[-recheck_max_entries:]
                trimmed = {k: raw[k] for k in keys}
                with open(recheck_path, "w", encoding="utf-8") as f:
                    json.dump(trimmed, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return {"snapshots_removed": snap_removed}
