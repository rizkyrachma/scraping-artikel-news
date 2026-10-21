"""
run_reprocess_all_october.py
Pemrosesan ulang dataset berita Ditjen Industri Agro untuk periode 1 - 6 Oktober 2026
menggunakan Aturan Tambahan (Prioritas Tinggi A, B, C, D), skema kolom standar (tanpa Sub Sektor & Isu),
penyesuaian Tone, Spokesperson/Kemenperin, dan deduplikasi media monitoring.
"""

import os
import sys
import json
import re
import pandas as pd

sys.path.insert(0, "src")
from config import load_spokesperson_map
from relevance_filter import (
    is_non_article_structural_noise,
    is_kemenperin_related,
    is_entity_only_title,
    is_corporate_funding_noise
)
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel
from fetch_news import clean_title_media_suffix

# 1. ATURAN BUANG UMUM (Hanya jenis buangan yang sah sesuai Rule D & Rule E/F)
DISCARD_PATTERNS = [
    # ATURAN TAMBAHAN 2 (PRIORITAS TERTINGGI):
    # Rule E: Aksi pendanaan korporasi
    (r"\b(lontar papyrus|indah kiat|inkp).*(pelunasan|penerbitan|obligasi|sukuk|surat utang)\b", "pendanaan korporasi: pelunasan/penerbitan obligasi atau sukuk emiten kertas/agro (Rule E)"),
    (r"\b(pelunasan|penerbitan|rilis|terbitkan|lunasi|rampungkan\s+pelunasan|siapkan.*dana.*pelunasan|tuntaskan\s+pelunasan)\b.*\b(obligasi|sukuk|surat\s+utang)\b", "pendanaan korporasi: pelunasan atau penerbitan obligasi/sukuk/surat utang (Rule E)"),
    (r"\b(obligasi|sukuk|surat\s+utang)\b.*\b(pelunasan|penerbitan|jatuh\s+tempo|peringkat)\b", "pendanaan korporasi: obligasi/sukuk/surat utang jatuh tempo atau pemeringkatan (Rule E)"),
    (r"\bpefindo\b", "pendanaan korporasi: pemeringkatan utang Pefindo (Rule E)"),
    (r"\brights?\s+issue\b", "pendanaan korporasi: aksi korporasi rights issue (Rule E)"),
    (r"\b(tebar|bagikan|pembagian|jadwal)\s+dividen\b", "pendanaan korporasi: pembagian dividen perusahaan (Rule E)"),
    (r"\bdividen\s+(interim|final|tunai|saham)\b", "pendanaan korporasi: dividen perusahaan (Rule E)"),
    (r"\bbuyback\s+saham\b", "pendanaan korporasi: buyback saham perusahaan (Rule E)"),
    # Rule F: Judul kosong / nama entitas saja tanpa kalimat berita
    (r"^bca sekuritas$", "judul tidak informatif: hanya nama entitas tanpa kalimat berita (Rule F)"),
    # a. Penghargaan / award siswa / lomba non-industri
    (r"\b(siswa.*sd|gold award|juara lomba|lomba mabbetang|paras fest|harsama|lumbung karya indonesia)\b", "penghargaan/award: lomba atau penghargaan non-industri"),
    # b. Analisis saham murni & rekomendasi teknikal
    (r"\b(analisis teknikal|target harga|rekomendasi saham|saham murah sinar mas|potensi cuan|saham.*melesat.*prospeknya|saham.*bertaji)\b", "saham murni: analisis atau rekomendasi saham"),
    # c. Tips produk / how-to konsumen / resep
    (r"\b(triplek sanding|tips dapur|cara membuat|resep|kunci furniture|gigi hiu|gigi anak|susu formula|susu basi|jangan langsung buang susu)\b", "halaman promosi/tips produk: tips konsumsi atau panduan konsumen"),
    # d. Opini keagamaan / bansos / BLT / pasar murah
    (r"\b(blt dbhcht|bantuan langsung tunai|nonhalal.*dharar|bansos|sembako murah)\b", "CSR/zakat/bansos atau opini keagamaan non-industri"),
    # e. Peternakan hulu murni / satwa liar / kandang
    (r"\b(kandang komunal|orangutan|bksda|satwa liar|ular piton)\b", "satwa atau peternakan murni tanpa kaitan industri pengolahan"),
    # f. Kewajiban lahan / HGU murni perkebunan (Rule B.2)
    (r"\b(kewajiban hgu|pemenuhan kewajiban hgu)\b", "kewajiban HGU: kewajiban lahan perkebunan murni"),
    # g. Kriminalitas murni / kecelakaan lalin perorangan
    (r"\b(kena tipu|gasak.*getah|pencurian getah|truk.*terguling|pecah ban|laka lantas|penipuan|terdakwa.*bebas|fasilitas mewah.*napi)\b", "kriminal/penindakan atau kecelakaan lalu lintas umum"),
    # h. Harga pasar eceran / harga harian lokal
    (r"\b(update harga karet sumsel|harga tbs sawit kaltim|sumbar rebut puncak harga tbs)\b", "harga eceran/harian daerah: fluktuasi harga harian lokal"),
    # i. Pelatihan / sertifikasi individu / karier / beasiswa
    (r"\b(pelatihan inova|pelatihan ispo|sertifikat profesi sawit|beasiswa sdm sawit|bimtek teknologi jagung)\b", "pelatihan/karier/sertifikasi: pelatihan atau kompetensi individu"),
    # j. Profil tokoh / wirausaha perorangan / kosmetik non-agro
    (r"\b(dr\. renni yuniati|wirausaha kosmetik|skincare|pabrik kosmetik cpkb)\b", "profil tokoh/karya individu: wirausaha kosmetik non-agro"),
    # k. Seni / film / hiburan / budaya pop / olahraga
    (r"\b(madani film festival|wishful thinking|haechan|k-pop|mini soccer|f1 gp|sirkuit sepang|timnas)\b", "hiburan, seni budaya, atau olahraga non-industri"),
    # l. Lokasi geografis / iklan properti / perumahan
    (r"\b(pondok kelapa.*kabel|rumah murah komplek pondok kelapa)\b", "lokasi geografis atau iklan properti perumahan"),
    # m. Anggaran konsumsi rapat pemda (bukan industri manufaktur)
    (r"\b(anggaran mamin|pengadaan mamin|dugaan monopoli mamin)\b", "belanja konsumsi rutin rapat pemda, bukan industri manufaktur mamin"),
    # n. Perbankan mikro / BRILink non-industri
    (r"\b(brilink.*ria irawan|agen ria irawan)\b", "CSR/zakat/bansos: keagenan perbankan mikro non-industri"),
    # o. Karya ilmiah / jurnal OJS / AHP
    (r"\b(jurnal|journal|skripsi|tesis|abstrak|analytic hierarchy process|ijccs|scopus)\b", "karya ilmiah / jurnal akademik OJS"),
    # p. Rekreasi wisata / hobi nongkrong kopi / tiket
    (r"\b(wisata di ciwidey|wisata edukasi di wonosari|rakor pariwisata danau toba|tiket festival makanan)\b", "rekreasi wisata, pariwisata, atau listing tiket"),
    # q. Politik praktis / aksi unjuk rasa teaterikal
    (r"\b(mahasiswa teaterikal tanam sawit|pan kotim|fawait)\b", "politik praktis atau aksi unjuk rasa teaterikal"),
    # r. Riset murni medis/klinis tanpa kaitan agro
    (r"\b(luka kaki diabetik|hidrogel teh hijau.*diabetik)\b", "edukasi kesehatan/opini keagamaan/riset medis: riset klinis medis murni"),
    # s. Logistik / transportasi umum non-agro
    (r"\b(pembatasan truk saat nataru)\b", "energi atau logistik non-agro: pembatasan transportasi umum"),
    # t. Placeholder agregator
    (r"\b(berita.*makanan kemasan terbaru hari ini|berita biodiesel b50 terkini hari ini|sistem pencarian ikm unggulan)\b", "agregator \"terbaru hari ini\": halaman placeholder tanpa artikel"),
    # Kerajinan tangan / kriya / tips DIY / kerajinan tempurung kelapa
    (r"\b(kerajinan tangan|ide kreatif kerajinan|tempurung kelapa.*kerajinan|kerajinan.*tempurung|kriya)\b", "kerajinan tangan / kriya / tips DIY bukan industri agro"),
]

# 2. ATURAN REVIEW (Minimal Review sesuai Rule B & Ketentuan Ditjen IA)
REVIEW_PATTERNS = [
    # B.1 Riset kampus, inovasi, pengabdian masyarakat agro
    (r"\b(buah mangrove jadi pengawet|ecopot biodegradable|bioproduk alga ugm|resona saintek unanda|mitos sagu|bioplastik.*singkong|enzim mikroba.*sagu|limbah kulit kopi.*mahasiswa|simulasi plant biodiesel.*undip|ipb.*sagu|olahan sagu.*ipb|inovasi teknologi produk daging dan susu)\b",
     "Riset/inovasi kampus hilirisasi komoditas agro (Rule B.1)"),
    # B.2 Program/pernyataan pemda penopang ekonomi daerah
    (r"\b(kutim dorong.*pertanian dan sawit|seno aji.*kaltim.*sawit.*b50|pemkab sekadau targetkan.*lahan sawit|pemkab sekadau salurkan.*benih|plt wali kota madiun.*umkm makanan|sentra ki dan ig kelapa dalam)\b",
     "Pernyataan/program pemda pengembangan komoditas agro penopang ekonomi (Rule B.2)"),
    # B.3 Permintaan listrik hijau / REC / RE100 dari industri
    (r"\b(pelanggan rec bertambah|listrik hijau.*industri|app group.*re100)\b",
     "Permintaan listrik hijau / REC / RE100 dari industri manufaktur (Rule B.3)"),
    # Bioenergi / Limbah agro jadi energi
    (r"\b(biocng|biomethane dari limbah sawit|limbah cair kelapa sawit|pltbg pome|limbah sawit.*energi terbarukan|bahan baku baru untuk avtur|limbah tandan kosong sawit disulap jadi helm)\b",
     "Limbah agro / POME jadi energi terbarukan atau produk bernilai tambah"),
    # Kebijakan budidaya hulu & peremajaan
    (r"\b(151\.000 hektare.*peremajaan kelapa|3 juta hektare budi daya rumput laut|tanaman karet menua.*insentif peremajaan)\b",
     "Budidaya hulu terkait program/kebijakan peremajaan pemerintah"),
    # Nilai tambah produk & kemitraan rantai pasok
    (r"\b(arang tempurung kelapa.*karbon aktif|sisa pengolahan ikan.*tepung ikan|ahmad luthfi dorong umkm.*pangan lokal|the plantationpreneurs festival|pisagro bidik pemberdayaan|minyak atsiri duskar|jabung milk|orientasi produk lokal.*amdk|fda.*kerangka pmta|tera ulang timbangan pks|kemitraan sawit berkelanjutan|moratorium sawit)\b",
     "Pengembangan nilai tambah, UMKM lokal olahan, atau regulasi rantai pasok agro"),
]


def classify_article(title: str, text: str = "", url: str = "") -> tuple[str, str]:
    """
    Mengklasifikasikan artikel ke status ('relevan', 'review', 'buang') dan alasannya.
    Mengikuti Aturan Tambahan 2 (Prioritas Tertinggi E, F, G) dan Aturan Tambahan (A, B, C, D).
    """
    t_clean = (title or "").strip()
    t_low = t_clean.lower()

    # Rule C (WAJIB RELEVAN): Semua berita kebijakan, pernyataan, atau program Menperin/Kemenperin
    # Termasuk non-agro seperti industri mesin/manufaktur umum.
    if any(k in t_low for k in ["sarmuji", "kemenperin", "menperin", "kementerian perindustrian"]):
        return "relevan", "Kebijakan/pernyataan Menperin/Kemenperin (Rule C)"

    # ATURAN TAMBAHAN 2 (PRIORITAS TERTINGGI, MENGALAHKAN ATURAN LAIN):
    # Rule E: Aksi pendanaan korporasi = BUANG
    # Pengecualian (tetap relevan): berita kinerja operasional emiten (penjualan, produksi, laba, margin, hedging, ekspansi pabrik, harga pulp)
    operational_exceptions = ["penjualan", "produksi", "laba", "margin", "hedging", "ekspansi pabrik", "harga pulp"]
    has_operational_exception = any(op in t_low for op in operational_exceptions)

    if not has_operational_exception:
        if is_corporate_funding_noise(t_clean):
            return "buang", "pendanaan korporasi: aksi pendanaan/permodalan perusahaan (Rule E)"

    # Rule F: Judul kosong / nama media/situs/perusahaan tanpa kalimat berita = BUANG
    if not t_clean or is_entity_only_title(t_clean) or re.search(r"^bca sekuritas$", t_low):
        return "buang", "judul tidak informatif: hanya nama entitas tanpa kalimat berita (Rule F)"

    # Rule D & Discard checks (Hanya jenis buangan yang sah)
    for pat, reason in DISCARD_PATTERNS:
        if "pendanaan korporasi" in reason and has_operational_exception:
            continue
        if re.search(pat, t_low):
            return "buang", reason

    # Filter struktural tambahan (memeriksa URL & teks juga)
    if is_non_article_structural_noise(title=t_clean, url=url, text=text):
        return "buang", "Filter struktural: placeholder agregator / listing spam"

    # Rule G: Cek ulang sebelum status "review" (Rule E & F telah dipastikan BUANG di atas)
    # Rule B & Review checks
    for pat, reason in REVIEW_PATTERNS:
        if re.search(pat, t_low):
            return "review", reason

    # Default: Relevan untuk berita industri/pengolahan/kebijakan agro
    return "relevan", "Berita industri agro, hilirisasi, ekspor-impor, atau kebijakan ekonomi"


def process_dataset(folder_path: str, input_articles: list[dict], output_prefix: str, name_map: dict):
    print("=" * 70)
    print(f"MEMPROSES DATASET: {folder_path} (Total Input: {len(input_articles)} artikel)")
    print("=" * 70)

    discarded_articles = []
    retained_articles = []

    for idx, art in enumerate(input_articles, 1):
        t = str(art.get("title", "") or art.get("Title", "")).strip()
        txt = str(art.get("text", "") or art.get("Text", "") or "").strip()
        u = str(art.get("link", "") or art.get("Link Website", "") or "").strip()
        media = str(art.get("media_name", "") or art.get("Media Name", "") or art.get("source", "")).strip()
        kw = str(art.get("keyword", "") or art.get("Keywords", "")).strip()
        sd = str(art.get("sumber_data", "") or art.get("Sumber Data", "RSS")).strip()
        tgl = str(art.get("published", "") or art.get("Tanggal", "")).strip()

        status, reason = classify_article(t, txt, u)

        art_dict = {
            "Tanggal": tgl,
            "Title": t,
            "Link Website": u,
            "Media Name": media,
            "Keywords": kw,
            "Sumber Data": sd,
            "text": txt,
            "status": status,
            "alasan": reason,
        }

        if status == "buang":
            discarded_articles.append(art_dict)
            continue

        # Status Review: jika review, isi alasan verifikasi; jika relevan, kosong
        if status == "review":
            art_dict["Status Review"] = f"Perlu Dicek Manual: {reason}"
        else:
            art_dict["Status Review"] = ""

        # Enrichment NLP: Tone
        art_dict["Tone"] = classify_tone(txt, t)

        # Enrichment NLP: Spokesperson & Terkait Kemenperin
        sp1, sp2, unit = find_spokespersons(f"{t} {txt}", name_map)
        art_dict["Spokesperson 1"] = sp1
        art_dict["Spokesperson 2"] = sp2
        art_dict["Unit Eselon"] = unit if unit else "-"

        # Aturan Poin 5 & Rule C: Jika ada pejabat Kemenperin atau sinyal Kemenperin -> Terkait Kemenperin = Ya
        if sp1 and sp1 not in ["nan", "None", "-", ""]:
            art_dict["Terkait Kemenperin"] = "Ya"
        elif any(k in t.lower() for k in ["kemenperin", "menperin", "sarmuji", "kementerian perindustrian"]):
            art_dict["Terkait Kemenperin"] = "Ya"
        else:
            is_rel = is_kemenperin_related(title=t, text=txt, spokesperson_map=name_map, keyword=kw, sumber_data=sd)
            art_dict["Terkait Kemenperin"] = "Ya" if is_rel else "Tidak"

        retained_articles.append(art_dict)

    # Deduplikasi Media Monitoring:
    # Judul sama tapi beda media = TETAP DIPERTAHANKAN
    # Judul identik DAN media identik = DEDUP TEKNIS (simpan teks lebih panjang)
    tech_unique_retained = {}
    for art in retained_articles:
        raw_t = (art.get("Title") or "").strip().lower()
        clean_t = clean_title_media_suffix(raw_t).strip().lower()
        raw_m = (art.get("Media Name") or "").strip().lower()
        key = (clean_t, raw_m)
        if key not in tech_unique_retained:
            tech_unique_retained[key] = art
        else:
            ex_len = len(tech_unique_retained[key].get("text") or "")
            new_len = len(art.get("text") or "")
            if new_len > ex_len:
                tech_unique_retained[key] = art

    final_records = list(tech_unique_retained.values())

    # Simpan file perbaikan
    out_perbaikan = os.path.join(folder_path, f"{output_prefix}_perbaikan.xlsx")
    out_terbaru = os.path.join(folder_path, f"{output_prefix}_terbaru.xlsx")
    out_main = os.path.join(folder_path, f"{output_prefix}.xlsx")
    out_discard = os.path.join(folder_path, "discarded_articles.json")

    with open(out_discard, "w", encoding="utf-8") as f:
        json.dump(discarded_articles, f, ensure_ascii=False, indent=2)

    save_to_excel(final_records, out_perbaikan, merge_existing=False)
    save_to_excel(final_records, out_terbaru, merge_existing=False)
    save_to_excel(final_records, out_main, merge_existing=False)

    # Verifikasi DataFrame
    df_res = pd.read_excel(out_perbaikan)
    print(f"\n[HASIL SELESAI]")
    print(f"Total Input       : {len(input_articles)}")
    print(f"Total Dibuang     : {len(discarded_articles)}")
    print(f"Total Lolos Awal  : {len(retained_articles)} (Relevan: {sum(1 for a in retained_articles if a['status'] == 'relevan')}, Review: {sum(1 for a in retained_articles if a['status'] == 'review')})")
    print(f"Total Akhir Dedup : {len(df_res)} baris")
    print(f"Daftar Kolom      : {list(df_res.columns)}")
    assert "Sub Sektor" not in df_res.columns, "Kolom Sub Sektor harus dihapus!"
    assert "Isu" not in df_res.columns, "Kolom Isu harus dihapus!"
    assert "Status Review" in df_res.columns, "Kolom Status Review harus ada!"

    print(f"\nDistribusi Status Review:")
    print(df_res["Status Review"].value_counts(dropna=False).head(10).to_string())

    print(f"\nDistribusi Tone:")
    print(df_res["Tone"].value_counts(dropna=False).to_string())

    print(f"\nDistribusi Terkait Kemenperin:")
    print(df_res["Terkait Kemenperin"].value_counts(dropna=False).to_string())
    print("\n" + "-" * 70)
    return len(input_articles), len(df_res), len(discarded_articles)


def main():
    name_map = load_spokesperson_map("keyword/keyword_nama.xlsx")

    # =========================================================================
    # 1. PERIODE 6 OKTOBER 2026 (45 Artikel)
    # =========================================================================
    path_06 = "hasil_scrapping/Oktober/2026-10-06"
    with open(os.path.join(path_06, "progress.json"), "r", encoding="utf-8") as f:
        articles_06 = json.load(f).get("articles", [])
    process_dataset(path_06, articles_06, "all_2026-10-06", name_map)

    # =========================================================================
    # 2. PERIODE 5 OKTOBER 2026 (Curated Base + Genuine Rescued Articles)
    # =========================================================================
    import run_reprocess_2026_10_05
    run_reprocess_2026_10_05.main()

    # =========================================================================
    # 3. PERIODE 1 - 4 OKTOBER 2026 (229 Artikel Bersih Kandidat)
    # =========================================================================
    path_1_4 = "hasil_scrapping/Oktober/2026-10-01_sd_2026-10-04"
    # Muat teks artikel dari progress.json
    with open(os.path.join(path_1_4, "progress.json"), "r", encoding="utf-8") as f:
        p_arts = {a.get("link"): a.get("text", "") for a in json.load(f).get("articles", [])}

    df_229 = pd.read_excel(os.path.join(path_1_4, "all_2026-10-01_sd_2026-10-04_clean_229.xlsx"))
    articles_1_4 = []
    for _, r in df_229.iterrows():
        u = str(r.get("Link Website", "")).strip()
        txt = p_arts.get(u, "")
        art_dict = {
            "Tanggal": str(r.get("Tanggal", "")),
            "Title": str(r.get("Title", "")),
            "Link Website": u,
            "Media Name": str(r.get("Media Name", "")),
            "Keywords": str(r.get("Keywords", "")),
            "Sumber Data": str(r.get("Sumber Data", "RSS")),
            "text": txt,
        }
        articles_1_4.append(art_dict)

    process_dataset(path_1_4, articles_1_4, "all_2026-10-01_sd_2026-10-04", name_map)


if __name__ == "__main__":
    main()
