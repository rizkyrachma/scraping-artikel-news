"""
direct_crawl_kemenperin.py
Modul direct crawl siaran pers langsung dari portal resmi Kementerian Perindustrian (https://kemenperin.go.id/siaran-pers).
Sebagai sumber primer / fallback independen dari Google News RSS.
"""

import re
import requests
from datetime import date, datetime
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings()

KEMENPERIN_SIARAN_PERS_URL = "https://kemenperin.go.id/siaran-pers"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}


def parse_kemenperin_date(date_str: str) -> date | None:
    """
    Mengurai format tanggal dari teks siaran pers Kemenperin, contoh: '(08/09/2026)' atau '08/09/2026'.
    """
    if not date_str:
        return None
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", date_str)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None
    return None


def crawl_kemenperin_siaran_pers(target_date: date | None = None, max_pages: int = 2) -> list[dict]:
    """
    Mengambil daftar siaran pers dari https://kemenperin.go.id/siaran-pers.
    Jika target_date diberikan, hanya mengambil rilis yang tanggal terbitnya cocok dengan target_date.
    Mengembalikan list dictionary dengan format standar:
    [{'title': ..., 'link': ..., 'published': ..., 'text': ..., 'media_name': 'kemenperin.go.id', 'sumber_data': 'Direct Crawl'}]
    """
    results = []

    for page in range(1, max_pages + 1):
        url = KEMENPERIN_SIARAN_PERS_URL if page == 1 else f"{KEMENPERIN_SIARAN_PERS_URL}?page={page}"
        try:
            resp = requests.get(url, headers=HEADERS, verify=False, timeout=25)
            if resp.status_code != 200:
                print(f"[Direct Crawl] Gagal mengakses {url} (HTTP {resp.status_code})")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            article_links = soup.find_all("a", href=True)

            found_on_page = 0
            for a in article_links:
                href = a["href"]
                if "/artikel/" in href:
                    title = a.get_text(strip=True)
                    if not title or len(title) < 10:
                        continue

                    # Ambil elemen parent/container untuk mencari tanggal publikasi
                    parent = a.find_parent()
                    parent_text = parent.get_text(separator=" ", strip=True) if parent else ""
                    pub_date = parse_kemenperin_date(parent_text)

                    full_url = href if href.startswith("http") else f"https://kemenperin.go.id{href}"

                    if target_date is not None and pub_date != target_date:
                        continue

                    # Ekstraksi isi artikel penuh
                    article_text = title
                    try:
                        art_resp = requests.get(full_url, headers=HEADERS, verify=False, timeout=20)
                        if art_resp.status_code == 200:
                            art_soup = BeautifulSoup(art_resp.text, "html.parser")
                            # Isi teks biasanya ada dalam container konten artikel
                            content_div = art_soup.find("div", class_=re.compile(r"content|artikel|isi|detail", re.I))
                            if content_div:
                                article_text = content_div.get_text(separator="\n", strip=True)
                            else:
                                paras = art_soup.find_all("p")
                                if paras:
                                    article_text = "\n".join(p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 30)
                    except Exception as err:
                        print(f"[Direct Crawl] Gagal mengambil isi teks artikel {full_url}: {err}")

                    results.append({
                        "title": title,
                        "raw_title": f"{title} - Kemenperin",
                        "link": full_url,
                        "resolved_url": full_url,
                        "published": pub_date.strftime("%a, %d %b %Y 07:00:00 GMT") if pub_date else "",
                        "text": article_text,
                        "media_name": "kemenperin.go.id",
                        "source": "Kemenperin",
                        "sumber_data": "Direct Crawl",
                        "keyword": "kemenperin_institusi",
                        "terkait_kemenperin": "Ya",
                        "kemenperin_signal_type": "EKSPLISIT",
                        "kemenperin_signal_detail": "kemenperin.go.id (Portal Resmi)",
                    })
                    found_on_page += 1

            if found_on_page == 0 and page > 1:
                break

        except Exception as e:
            print(f"[Direct Crawl] Error crawling {url}: {e}")
            break

    return results


if __name__ == "__main__":
    print("Testing direct_crawl_kemenperin...")
    print("1. Cek semua rilis terbaru di halaman 1:")
    all_recent = crawl_kemenperin_siaran_pers(target_date=None, max_pages=1)
    print(f"Total rilis ditemukan di halaman 1: {len(all_recent)}")
    for r in all_recent[:5]:
        print(f" - {r['published']}: {r['title']}")

    print("\n2. Cek rilis tanggal kemarin (2026-09-15):")
    target = date(2026, 9, 15)
    matched = crawl_kemenperin_siaran_pers(target_date=target, max_pages=2)
    print(f"Total rilis pada {target}: {len(matched)}")
