"""
src package
Kumpulan modul pendukung pipeline scraping berita industri agro.
"""

import sys
import os

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from .direct_crawl_agro import (
    fetch_agro_kemenperin,
    cocokkan_rilis_resmi,
    integrate_agro_kemenperin_pipeline,
)

__all__ = [
    "fetch_agro_kemenperin",
    "cocokkan_rilis_resmi",
    "integrate_agro_kemenperin_pipeline",
]
