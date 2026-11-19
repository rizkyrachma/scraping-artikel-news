"""
scripts/isu_registry_state.py
Helper persistensi atomik dan pemulihan hasil_scrapping/isu_registry.json untuk GitHub Actions:
- restore: memilih isu_registry.json paling baru antara branch data (Lapis Utama) dan actions/cache (Lapis Kedua).
- persist: memangkas isu klaster kedaluwarsa (>14 hari) dan menulis atomik via file sementara + os.replace.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.isu_grouping import IsuRegistry


def _read_registry_meta(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("issues"), list):
            return True, str(data.get("updated_at") or "").strip()
    except Exception:
        pass
    return False, ""


def restore_isu_registry(branch_reg: Path, cache_reg: Path) -> str:
    """
    Memulihkan isu_registry.json ke cache_reg.
    Aturan prioritas:
    - Jika branch data valid dan (cache tidak valid / tanpa updated_at / branch_ts >= cache_ts): branch data menang.
    - Jika cache valid dan updated_at cache secara ketat lebih baru dari branch data: cache dipertahankan.
    - Jika keduanya tidak ada: run pertama, mulai dari registri baru.
    Mengembalikan sumber yang dipilih: 'branch', 'cache', atau 'fresh'.
    """
    b_ok, b_ts = _read_registry_meta(branch_reg)
    c_ok, c_ts = _read_registry_meta(cache_reg)

    if b_ok and (not c_ok or not c_ts or b_ts >= c_ts):
        cache_reg.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".isu_registry_", suffix=".tmp", dir=str(cache_reg.parent))
        os.close(fd)
        try:
            shutil.copy2(branch_reg, tmp_path)
            os.replace(tmp_path, cache_reg)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        print(f"[Registry] Dipulihkan dari branch data (updated_at={b_ts or '-'}, prioritas utama).")
        return "branch"

    if c_ok:
        print(f"[Registry] Mempertahankan isu_registry.json dari actions/cache (lebih baru: {c_ts} > {b_ts or 'kosong'}).")
        return "cache"

    print("[Registry] isu_registry.json belum ada (run pertama) - mulai dari registri baru.")
    return "fresh"


def persist_isu_registry(
    src: Path,
    dst: Path,
    end_date: str,
    updated_at: str | None = None,
) -> tuple[int, int]:
    """
    Memuat isu_registry.json dari src, memangkas klaster kedaluwarsa (>14 hari terhadap end_date),
    dan menulis hasilnya secara atomik (file sementara + os.replace) ke dst.
    Mengembalikan (jumlah_isu_aktif, jumlah_klaster_dipangkas).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    reg = IsuRegistry(filepath=src)
    ref_d = datetime.date.fromisoformat(end_date)
    pruned = reg.prune_expired(ref_d)
    payload = {
        "updated_at": updated_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "issues": list(reg.issues.values()),
    }
    fd, tmp_path = tempfile.mkstemp(prefix=".isu_registry_", suffix=".tmp", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, dst)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    print(f"[Registry] Disiapkan untuk persist atomik ({len(reg.issues)} isu aktif, {pruned} klaster >14 hari dipangkas).")
    return len(reg.issues), pruned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore dan persist atomik isu_registry.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rest = sub.add_parser("restore")
    p_rest.add_argument("--branch-reg", type=Path, default=Path("pipeline_state/isu_registry.json"))
    p_rest.add_argument("--cache-reg", type=Path, default=Path("hasil_scrapping/isu_registry.json"))

    p_pers = sub.add_parser("persist")
    p_pers.add_argument("--src", type=Path, default=Path("hasil_scrapping/isu_registry.json"))
    p_pers.add_argument("--dst", type=Path, required=True)
    p_pers.add_argument("--end-date", type=str, required=True)

    args = parser.parse_args(argv)
    if args.cmd == "restore":
        restore_isu_registry(args.branch_reg, args.cache_reg)
        return 0
    if args.cmd == "persist":
        persist_isu_registry(args.src, args.dst, args.end_date)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
