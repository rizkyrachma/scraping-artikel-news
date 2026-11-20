# Pipeline Scraping Berita Industri Agro (Kemenperin)

Pipeline otomatisasi scraping berita, ekstraksi konten, pemfilteran relevansi Ditjen Industri Agro, analisis sentimen, pemetaan pejabat (spokesperson), dan ekspor ke dataset Excel terstruktur.

---

## Struktur Direktori

```text
data_scrapping/
├── docs/                   # Dokumentasi teknis & pedoman arsitektur
│   ├── DOKUMEN_TEKNIS_PIPELINE_SCRAPING_BERITA.md
│   └── agents.md
├── keyword/                # Kamus data kata kunci, topik, dan pejabat
│   ├── keyword_data.txt
│   ├── keyword_kemenperin.csv
│   ├── keyword_nama.xlsx
│   ├── keyword_topik_ia.csv
│   ├── pejabat_keyword_mapping.csv
│   └── pejabat_keyword_mapping_arsip_non_agro.csv
├── src/                    # Seluruh modul Python pendukung pipeline
│   ├── config.py           # Konfigurasi tanggal, blocklist domain, dan loader keyword
│   ├── fetch_news.py       # Pencarian Google News RSS, Exa.ai, Serper, YouTube
│   ├── query_builder.py    # Generator query pencarian dan Google dork
│   ├── relevance_filter.py # Filter multi-layer non-industri, promosi ritel, dan kuliner
│   ├── ai_relevance_classifier.py # Filter lapis akhir Ditjen IA via Gemini API
│   ├── entity_mapper.py    # Ekstraksi dan pemetaan pejabat Kemenperin
│   ├── tone_classifier.py  # Klasifikasi tone Humas dan isu (Gemini + fallback rule-based)
│   ├── export_excel.py     # Ekspor data ke Excel dengan styling & hyperlink aktif
│   ├── serper_search.py    # Mesin pencari Serper.dev
│   ├── exa_search.py       # Mesin pencari Exa.ai
│   ├── youtube_search.py   # Modul pencarian YouTube
│   ├── direct_crawl_kemenperin.py # Direct crawl portal resmi kemenperin.go.id
│   └── extract_content.py  # Ekstraksi konten artikel (trafilatura / newspaper3k)
├── hasil_scrapping/        # Output dataset Excel terorganisir per bulan (Agustus/, September/, Oktober/) & per tanggal
├── scratch/                # Workspace pengujian sementara
├── main.py                 # Pipeline runner utama (CLI)
└── requirements.txt        # Dependensi Python
```

---

## Panduan Penggunaan

### 1. Instalasi Dependensi
```bash
pip install -r requirements.txt
```

### 2. Menjalankan Scraping
```bash
# Scraping 1 kata kunci tertentu (contoh: gula):
python main.py gula

# Scraping batch seluruh 46 kata kunci komoditas Ditjen IA:
python main.py --all
```

---

## Dokumentasi Lengkap
- [Dokumen Teknis Pipeline](docs/DOKUMEN_TEKNIS_PIPELINE_SCRAPING_BERITA.md)
- [Konteks & Pedoman AI Agent](docs/agents.md)
