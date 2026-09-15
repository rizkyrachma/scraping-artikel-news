# Dokumen Teknis: Pipeline Scraping Berita Industri (Google Search + Antigravity)

## 1. Ringkasan Kebutuhan

Sistem ini akan mengambil berita dari media nasional dan situs pemerintah (.go.id) berdasarkan dua sumber kata kunci:

- `keyword_data`: istilah komoditas dan industri (gula, tepung, biodiesel, pakan ternak, dan seterusnya)
- `keyword_nama`: nama pejabat beserta jabatannya (dipakai untuk mapping Spokesperson dan Unit Eselon)

Output akhir berupa file Excel dengan kolom Tanggal, Title, Link Website, Tone, Spokesperson 1, Spokesperson 2, dan Unit Eselon.

Masalah utama yang harus diselesaikan adalah domain noise, yaitu hasil pencarian yang dipenuhi marketplace dan e-commerce padahal yang dibutuhkan hanya media berita dan situs resmi pemerintah.

---

## 2. Catatan Penting Sebelum Membangun: Status Google Custom Search API

Ini penting untuk kamu ketahui di awal karena akan mempengaruhi pilihan arsitektur. Google Custom Search JSON API (yang biasa dipakai untuk keyword search terprogram) **sudah ditutup untuk pelanggan baru sejak 2025 dan akan resmi dihentikan pada 1 Januari 2027**. Kuota gratisnya cuma 100 query per hari, dan biaya tambahannya 5 dolar per 1000 query dengan batas maksimal 10.000 query per hari.

Karena project kamu ini kemungkinan besar dipakai untuk jangka panjang (bukan cuma demo tugas akhir), aku sarankan jangan menggantungkan pipeline sepenuhnya pada Custom Search JSON API. Strategi yang lebih aman adalah pendekatan hybrid berikut:

1. **Google News RSS** sebagai sumber utama untuk media berita nasional. Ini gratis, tidak butuh API key, tidak ada kuota harian yang ketat, dan mendukung operator pencarian Google biasa di dalam parameter query.
2. **Direct crawling ke situs .go.id** (Kementerian Perindustrian dan direktorat terkait) sebagai sumber utama untuk siaran pers resmi, karena Google News kadang tidak mengindeks halaman pemerintah dengan baik.
3. **Google Custom Search JSON API sebagai pelengkap opsional** kalau kamu sudah punya API key eksisting, tapi jangan jadi tulang punggung sistem karena akan mati Januari 2027.

---

## 3. Strategi Search Query dan Google Dorking

### 3.1 Format Google News RSS

```
https://news.google.com/rss/search?q={QUERY}&hl=id&gl=ID&ceid=ID:id
```

Parameter `q` mendukung operator pencarian Google standar, jadi kamu bisa gabungkan filter domain dan exclude langsung di situ.

### 3.2 Menyusun Query dengan Domain Allowlist

Daripada mengandalkan filter kata umum yang gampang bocor ke marketplace, lebih efektif membatasi domain secara eksplisit. Buat dua daftar:

**Allowlist media nasional** (contoh, bisa kamu perluas sesuai kebutuhan):
`antaranews.com`, `kompas.com`, `detik.com`, `cnbcindonesia.com`, `bisnis.com`, `kontan.co.id`, `tempo.co`, `katadata.co.id`, `republika.co.id`, `investor.id`, `industry.co.id`, `medcom.id`

**Situs pemerintah**: gunakan operator `site:.go.id` (titik di depan go.id akan mencakup semua subdomain, misalnya `kemenperin.go.id`, `setkab.go.id`, `bkpm.go.id`)

Contoh query gabungan untuk satu keyword komoditas:

```
gula (site:antaranews.com OR site:kompas.com OR site:detik.com OR site:cnbcindonesia.com OR site:bisnis.com OR site:kontan.co.id OR site:.go.id) -site:shopee.co.id -site:tokopedia.com -site:bukalapak.com -site:lazada.co.id -site:blibli.com -site:jd.id -inurl:jual -inurl:beli -inurl:produk -inurl:harga -inurl:toko
```

Karena URL RSS punya batas panjang karakter, jangan masukkan semua 15 domain sekaligus untuk semua keyword. Praktik yang lebih stabil:

- Pecah allowlist jadi 2 sampai 3 batch domain (misal 5-6 domain per batch)
- Jalankan query terpisah untuk batch media dan query terpisah untuk `site:.go.id`
- Gabungkan dan dedup hasilnya setelah semua batch selesai

### 3.3 Lapis Verifikasi Kedua (Post-Filter)

Jangan cuma mengandalkan dork di query. Setelah dapat daftar URL, lakukan verifikasi domain lagi di kode Python (parsing `urlparse(url).netloc`) dan cocokkan ke allowlist atau ke pola `.go.id`. Ini jaring pengaman kalau Google tetap menyelipkan hasil di luar domain yang diminta.

---

## 4. Rekomendasi Tech Stack

### 4.1 Search dan Scraping

| Kebutuhan | Rekomendasi | Alasan |
|---|---|---|
| Pencarian berita | `feedparser` + Google News RSS | Gratis, tanpa API key, tanpa kuota ketat, mendukung operator dork |
| Pencarian situs pemerintah spesifik | Crawl sitemap/halaman berita resmi Kemenperin (`kemenperin.go.id`) | Google News sering tidak lengkap mengindeks siaran pers pemerintah |
| Pencarian tambahan (opsional) | Google Custom Search JSON API | Hanya jika kamu sudah punya API key aktif, ingat batas akhir Januari 2027 |
| Ekstraksi konten artikel | `trafilatura` sebagai utama | Lebih akurat membuang boilerplate (iklan, navigasi) pada situs berita, masih aktif dikembangkan |
| Fallback ekstraksi | `newspaper3k` | Cadangan kalau trafilatura gagal pada struktur HTML tertentu |
| HTTP client | `requests` dengan `User-Agent` custom + retry/backoff | Banyak situs media memblokir request tanpa header browser |

### 4.2 NLP dan Sentiment Analysis (Tone)

Untuk kebutuhan kamu (Positif/Negatif saja), pendekatan yang paling efisien adalah dua lapis (hybrid):

1. **Lapis cepat**: lexicon-based menggunakan kamus sentimen Bahasa Indonesia (InSet Lexicon) untuk artikel yang polaritasnya jelas. Ringan, cepat, tidak butuh GPU.
2. **Lapis akurat**: model IndoBERT untuk kasus yang skornya ambigu di lapis pertama. Model yang bisa dipakai: `mdhugol/indonesia-bert-sentiment-classification` (IndoBERT yang sudah di-fine-tune 3 kelas: positif, netral, negatif) via library `transformers`.

Karena kolom Tone kamu cuma Positif/Negatif (tidak ada Netral), kelas netral dari model bisa dipetakan ke kelas terdekat berdasarkan skor confidence kedua tertinggi, atau kamu definisikan threshold sendiri (misalnya skor netral di bawah confidence tertentu dianggap default ke Negatif karena berita ekonomi/komoditas yang netral cenderung berisi data yang netral-ke-negatif seperti kenaikan harga bahan baku).

`vaderSentiment` tidak aku rekomendasikan karena itu dilatih untuk Bahasa Inggris dan tidak akan akurat untuk teks berita Bahasa Indonesia.

### 4.3 Ekstraksi Entitas (Spokesperson dan Unit Eselon)

Karena daftar nama pejabat kamu terbatas dan sudah diketahui sebelumnya (bukan open-domain NER), pendekatan yang paling efisien bukan model NER besar, tapi **matching berbasis daftar dengan toleransi variasi penulisan**:

1. Bangun dictionary dari `keyword_nama.txt`: key = nama pejabat, value = jabatan/unit eselon
2. Normalisasi teks artikel (lowercase, hapus gelar seperti Dr., Ir., S.T., M.M.)
3. Gunakan `rapidfuzz` (fuzzy string matching) untuk menangkap variasi penyebutan, misalnya artikel menyebut "Menperin Agus Gumiwang" padahal daftar kamu berisi "Menteri Perindustrian Agus Gumiwang". Fuzzy matching lebih toleran dibanding regex exact match.
4. Ambil maksimal dua nama pertama yang match sebagai Spokesperson 1 dan Spokesperson 2, lalu tarik Unit Eselon dari dictionary yang sama.

### 4.4 Export Excel

Gunakan `pandas` untuk menyusun DataFrame, lalu `openpyxl` sebagai engine untuk styling (lebar kolom otomatis, header bold, hyperlink aktif di kolom Link Website).

---

## 5. Arsitektur Pipeline (Step by Step)

1. **Load Input** — baca `keyword_data.txt` dan `keyword_nama.txt`, parse jadi list keyword dan dictionary nama-ke-jabatan
2. **Query Builder** — susun query Google News RSS per keyword, digabung dengan allowlist domain media + `.go.id`, serta negative filter marketplace
3. **Fetch RSS** — jalankan `feedparser` untuk tiap query, kumpulkan kandidat (title, link, tanggal publish dari RSS)
4. **Domain Verification** — cek ulang domain tiap link terhadap allowlist/`.go.id` sebagai jaring pengaman kedua, buang yang tidak lolos
5. **Deduplication** — hilangkan URL duplikat (berdasarkan URL yang dinormalisasi) dan artikel yang judulnya sangat mirip (fuzzy match judul)
6. **Content Extraction** — fetch tiap URL, ekstrak isi artikel dengan `trafilatura`, fallback ke `newspaper3k` kalau gagal
7. **Entity Mapping** — jalankan fuzzy matching nama pejabat pada isi artikel, isi Spokesperson 1, Spokesperson 2, dan Unit Eselon
8. **Sentiment Classification** — jalankan lexicon-based dulu, kalau ambigu lanjut ke IndoBERT, hasilkan label Tone
9. **Assembly & Export** — susun semua ke DataFrame pandas dengan kolom sesuai spesifikasi, lalu simpan ke `.xlsx` dengan formatting rapi

---

## 6. Template Kode Python Modular

Struktur folder yang disarankan:

```
news_pipeline/
├── config.py
├── query_builder.py
├── fetch_news.py
├── extract_content.py
├── entity_mapper.py
├── sentiment.py
├── export_excel.py
└── main.py
```

### 6.1 `config.py`

```python
# config.py

MEDIA_ALLOWLIST = [
    "antaranews.com", "kompas.com", "detik.com", "cnbcindonesia.com",
    "bisnis.com", "kontan.co.id", "tempo.co", "katadata.co.id",
    "republika.co.id", "investor.id", "industry.co.id", "medcom.id",
]

GOV_DOMAIN_SUFFIX = ".go.id"

MARKETPLACE_BLOCKLIST = [
    "shopee.co.id", "tokopedia.com", "bukalapak.com",
    "lazada.co.id", "blibli.com", "jd.id",
]

BLOCKED_URL_PATTERNS = ["jual", "beli", "produk", "harga", "toko", "review"]


def load_keywords(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return lines


def load_spokesperson_map(path: str) -> dict[str, str]:
    """
    Parse baris seperti:
    'direktur jenderal industri agro putu juli ardika'
    jadi {'putu juli ardika': 'Direktur Jenderal Industri Agro'}

    Sesuaikan parsing ini dengan format asli keyword_nama.txt kamu,
    idealnya minta tim data menyusun ulang jadi format 'Nama | Jabatan'
    supaya parsing tidak rapuh.
    """
    mapping = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # placeholder logika split, sesuaikan dengan pola nyata datamu
            parts = line.rsplit(" ", 2)
            if len(parts) == 3:
                jabatan, nama_depan, nama_belakang = parts
                nama = f"{nama_depan} {nama_belakang}".lower()
                mapping[nama] = jabatan.strip().title()
    return mapping
```

### 6.2 `query_builder.py`

```python
# query_builder.py
from urllib.parse import quote

def build_media_query(keyword: str, allowlist: list[str], blocklist: list[str]) -> str:
    site_filter = " OR ".join(f"site:{d}" for d in allowlist)
    exclude_filter = " ".join(f"-site:{d}" for d in blocklist)
    query = f"{keyword} ({site_filter}) {exclude_filter}"
    return quote(query)


def build_gov_query(keyword: str) -> str:
    query = f'{keyword} site:.go.id'
    return quote(query)


def build_rss_url(encoded_query: str) -> str:
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=id&gl=ID&ceid=ID:id"
```

### 6.3 `fetch_news.py`

```python
# fetch_news.py
import time
import feedparser
from urllib.parse import urlparse
from query_builder import build_media_query, build_gov_query, build_rss_url
from config import MEDIA_ALLOWLIST, MARKETPLACE_BLOCKLIST, GOV_DOMAIN_SUFFIX


def is_valid_domain(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    if any(bad in netloc for bad in MARKETPLACE_BLOCKLIST):
        return False
    if netloc.endswith(GOV_DOMAIN_SUFFIX):
        return True
    return any(good in netloc for good in MEDIA_ALLOWLIST)


def search_keyword(keyword: str, delay: float = 1.0) -> list[dict]:
    results = []
    for query_fn in (build_media_query, build_gov_query):
        if query_fn is build_media_query:
            encoded = query_fn(keyword, MEDIA_ALLOWLIST, MARKETPLACE_BLOCKLIST)
        else:
            encoded = query_fn(keyword)

        rss_url = build_rss_url(encoded)
        feed = feedparser.parse(rss_url)

        for entry in feed.entries:
            link = entry.get("link", "")
            if is_valid_domain(link):
                results.append({
                    "keyword": keyword,
                    "title": entry.get("title", ""),
                    "link": link,
                    "published": entry.get("published", ""),
                })
        time.sleep(delay)  # sopan ke server, hindari rate limit
    return results


def collect_all(keywords: list[str]) -> list[dict]:
    all_results = []
    for kw in keywords:
        all_results.extend(search_keyword(kw))
    return dedup_by_link(all_results)


def dedup_by_link(items: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for item in items:
        key = item["link"].split("?")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
```

### 6.4 `extract_content.py`

```python
# extract_content.py
import trafilatura
from newspaper import Article


def extract_article_text(url: str) -> str:
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        text = trafilatura.extract(downloaded, favor_precision=True)
        if text:
            return text

    # fallback kalau trafilatura gagal
    try:
        article = Article(url, language="id")
        article.download()
        article.parse()
        return article.text
    except Exception:
        return ""
```

### 6.5 `entity_mapper.py`

```python
# entity_mapper.py
from rapidfuzz import fuzz, process

def find_spokespersons(text: str, name_map: dict[str, str], threshold: int = 85):
    text_lower = text.lower()
    candidates = list(name_map.keys())

    found = []
    for name in candidates:
        # cek exact substring dulu (lebih cepat), baru fuzzy kalau tidak ketemu
        if name in text_lower:
            found.append(name)
            continue
        score = fuzz.partial_ratio(name, text_lower)
        if score >= threshold:
            found.append(name)

    found = found[:2]  # ambil maksimal 2 sesuai kolom Spokesperson 1 & 2

    spokesperson_1 = found[0].title() if len(found) > 0 else ""
    spokesperson_2 = found[1].title() if len(found) > 1 else ""
    unit_eselon = name_map.get(found[0], "") if found else ""

    return spokesperson_1, spokesperson_2, unit_eselon
```

### 6.6 `sentiment.py`

```python
# sentiment.py
from transformers import pipeline

_model = None

def get_model():
    global _model
    if _model is None:
        _model = pipeline(
            "sentiment-analysis",
            model="mdhugol/indonesia-bert-sentiment-classification",
            tokenizer="mdhugol/indonesia-bert-sentiment-classification",
        )
    return _model


LABEL_MAP = {"LABEL_0": "Positif", "LABEL_1": "Netral", "LABEL_2": "Negatif"}


def classify_tone(text: str) -> str:
    if not text:
        return "Negatif"  # default aman kalau ekstraksi gagal, sesuaikan kebijakanmu

    model = get_model()
    # potong teks kalau kepanjangan, model BERT punya batas token
    snippet = text[:1500]
    result = model(snippet)[0]
    label = LABEL_MAP.get(result["label"], "Netral")

    if label == "Netral":
        # kebijakan mapping netral -> biner, sesuaikan dengan kebutuhan risetmu
        label = "Positif" if result["score"] < 0.6 else "Negatif"

    return label
```

### 6.7 `export_excel.py`

```python
# export_excel.py
import pandas as pd
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def save_to_excel(records: list[dict], output_path: str):
    columns = [
        "Tanggal", "Title", "Link Website", "Tone",
        "Spokesperson 1", "Spokesperson 2", "Unit Eselon",
    ]
    df = pd.DataFrame(records, columns=columns)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Berita")
        ws = writer.sheets["Berita"]

        for col_idx, col_name in enumerate(columns, start=1):
            ws.cell(row=1, column=col_idx).font = Font(bold=True)
            max_len = max(df[col_name].astype(str).map(len).max() if not df.empty else 0, len(col_name))
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 60)

        # buat Link Website jadi hyperlink aktif
        link_col_idx = columns.index("Link Website") + 1
        for row_idx in range(2, len(df) + 2):
            cell = ws.cell(row=row_idx, column=link_col_idx)
            if cell.value:
                cell.hyperlink = cell.value
                cell.style = "Hyperlink"
```

### 6.8 `main.py`

```python
# main.py
from config import load_keywords, load_spokesperson_map
from fetch_news import collect_all
from extract_content import extract_article_text
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel


def run_pipeline():
    keywords = load_keywords("keyword_data.txt")
    name_map = load_spokesperson_map("keyword_nama.txt")

    raw_results = collect_all(keywords)
    print(f"Kandidat berita setelah filter domain & dedup: {len(raw_results)}")

    records = []
    for item in raw_results:
        text = extract_article_text(item["link"])
        if not text:
            continue

        sp1, sp2, unit = find_spokespersons(text, name_map)
        tone = classify_tone(text)

        records.append({
            "Tanggal": item.get("published", ""),
            "Title": item["title"],
            "Link Website": item["link"],
            "Tone": tone,
            "Spokesperson 1": sp1,
            "Spokesperson 2": sp2,
            "Unit Eselon": unit,
        })

    save_to_excel(records, "hasil_scraping_berita.xlsx")
    print(f"Selesai. {len(records)} artikel tersimpan ke hasil_scraping_berita.xlsx")


if __name__ == "__main__":
    run_pipeline()
```

Catatan penting soal `load_spokesperson_map`: fungsi di atas cuma placeholder parsing karena format `keyword_nama.txt` yang kamu upload masih dalam bentuk kalimat bebas (jabatan lalu nama di akhir). Untuk hasil yang stabil, sebaiknya kamu susun ulang file itu jadi format terstruktur, misalnya CSV dengan dua kolom `nama,jabatan`. Ini akan menghindari parsing yang rapuh dan jauh lebih gampang dipelihara ke depannya.

---

## 7. Batasan dan Risiko yang Perlu Kamu Sadari

1. **Robots.txt dan hukum scraping**: sebagian situs media punya `robots.txt` yang membatasi crawling otomatis pada path tertentu. Cek dulu sebelum scraping massal, dan tambahkan delay antar-request supaya tidak membebani server mereka.
2. **Akurasi sentiment model**: model IndoBERT publik dilatih dari data ulasan/media sosial, bukan spesifik teks berita ekonomi-industri. Untuk tugas akhir, disarankan validasi manual pada sample data (misalnya 50-100 artikel) untuk mengukur akurasi sebelum dipakai penuh, dan laporkan angka akurasinya sebagai bagian dari evaluasi sistem.
3. **Perubahan struktur HTML situs media**: `trafilatura` cukup tangguh tapi tidak 100 persen bebas dari kegagalan ekstraksi kalau situs mengubah struktur halamannya.
4. **Ketergantungan Google News RSS**: ini layanan tidak berdokumen resmi (undocumented), jadi ada risiko kecil formatnya berubah sewaktu-waktu. Untuk tugas akhir ini cukup aman dipakai, tapi kalau nanti jadi sistem produksi jangka panjang, pertimbangkan API berbayar yang lebih stabil sebagai cadangan.
