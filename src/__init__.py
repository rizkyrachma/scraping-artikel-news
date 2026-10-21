"""
src package
Kumpulan modul pendukung pipeline scraping berita industri agro.
"""

import sys
import os

_src_dir = os.path.abspath(os.path.dirname(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
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
