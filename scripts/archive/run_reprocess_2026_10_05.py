"""
run_reprocess_2026_10_05.py
Pemrosesan ulang dan standardisasi dataset berita Ditjen Industri Agro untuk tanggal 5 Oktober 2026.
Menerapkan:
1. Aturan Tambahan 2 (Prioritas Tertinggi E, F, G) dan Aturan Tambahan Ditjen IA (A, B, C, D).
2. Skema 12 kolom standar (tanpa Sub Sektor dan Isu, dengan Status Review).
3. Penyelamatan berita riset kampus (Rule B.1), program pemda (Rule B.2), bioenergi/limbah agro, kemitraan rantai pasok.
4. Pembuangan noise: katalog profil perusahaan, penindakan hukum rokok ilegal murni, judi online, brand awards, tips gaya hidup.
5. Deduplikasi teknis media monitoring (judul sama + media sama -> teks terpanjang; media berbeda -> dipertahankan).
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

DISCARD_PATTERNS = [
    # Rule E: Aksi pendanaan korporasi
    (r"\b(pelunasan|penerbitan|rilis|terbitkan|lunasi|rampungkan\s+pelunasan|siapkan.*dana.*pelunasan|tuntaskan\s+pelunasan)\b.*\b(obligasi|sukuk|surat\s+utang)\b", "pendanaan korporasi: pelunasan/penerbitan obligasi atau sukuk (Rule E)"),
    (r"\b(obligasi|sukuk|surat\s+utang)\b.*\b(pelunasan|penerbitan|jatuh\s+tempo|peringkat)\b", "pendanaan korporasi: obligasi jatuh tempo/peringkat (Rule E)"),
    (r"\bpefindo\b", "pendanaan korporasi: pemeringkatan utang Pefindo (Rule E)"),
    (r"\brights?\s+issue\b", "pendanaan korporasi: rights issue (Rule E)"),
    (r"\b(tebar|bagikan|pembagian|jadwal)\s+dividen\b", "pendanaan korporasi: pembagian dividen (Rule E)"),
    (r"\bdividen\s+(interim|final|tunai|saham)\b", "pendanaan korporasi: dividen (Rule E)"),
    (r"\bbuyback\s+saham\b", "pendanaan korporasi: buyback saham (Rule E)"),

    # Rule F: Judul tidak informatif / nama entitas saja
    (r"^bca sekuritas$", "judul tidak informatif: hanya nama entitas tanpa kalimat berita (Rule F)"),
    (r"^(detail produk|tepung maizena|susu kurma 33|desa berdaya.*)$", "judul tidak informatif / halaman katalog produk"),

    # Judi / slot / togel
    (r"\b(rtp\s*nexus|slot|judi|jppoker|raja89)\b", "judi online / slot spam"),

    # Kriminal / sidang / penindakan hukum murni / razia / penipuan
    (r"\b(rokok ilegal digagalkan|pengiriman.*rokok ilegal|terdakwa.*budiman bayu prasodjo|sidang cpo.*pt green products|terdakwa direktur pt teo|pengadilan singapura perpanjang penyitaan.*bos sawit|gasak.*getah karet|kena tipu.*gula dan minyak goreng|lapas cibinong.*miras|ombudsman.*lapas)\b",
     "kriminalitas / persidangan pidana / penindakan hukum murni"),

    # Bencana alam / kecelakaan lalin
    (r"\b(terguling|pecah ban|laka lantas|banjir bandang|kabut asap)\b", "kecelakaan lalu lintas / bencana alam / kabut asap"),

    # Sengketa agraria / sengketa lahan murni
    (r"\b(sengketa lahan|sengketa batas lahan|sengketa tanah|sengketa kemitraan sawit 143 hektare)\b", "sengketa lahan / agraria murni"),

    # Satwa liar / konservasi
    (r"\b(orangutan|bksda|satwa liar)\b", "satwa liar / konservasi"),

    # Belanja mamin konsumsi rapat pemda (bukan industri mamin)
    (r"\b(anggaran mamin|monopoli mamin)\b", "belanja konsumsi rutin rapat pemda"),

    # Keagenan perbankan mikro (BRILink dll)
    (r"\b(brilink|agen ria irawan)\b", "keagenan perbankan mikro"),

    # Lokasi geografis / nama tempat / iklan properti
    (r"\b(pondok kelapa|ex pabrik biskuit dijual|rumah murah)\b", "lokasi geografis atau listing properti"),

    # Bansos / bantuan bencana / program sosial kemiskinan murni
    (r"\b(blt dbhcht|bantuan susu|masker dan susu|susu dan masker|susu bantuan|lepas susu bantuan|dinas sosial.*salurkan|pascabencana)\b", "bansos atau bantuan bencana non-industri"),

    # Promosi brand awards / lomba siswa / pameran siswa
    (r"\b(trusted & popular brand|juara satu kmi expo|pln uip klt raih penghargaan|juara lomba|lomba mabbetang|harsama|hadiah nobel)\b", "penghargaan brand / award siswa / lomba"),

    # Jurnal OJS / skripsi / karya ilmiah akademik
    (r"\b(analytic hierarchy process|ahp|jurnal|journal|scopus|ijccs|skripsi|tesis|abstrak)\b", "jurnal akademik OJS / skripsi"),

    # Tips konsumen / gaya hidup / resep / medis / anak
    (r"\b(waktu terbaik minum|tips |susu basi|jangan langsung buang|gigi anak|rekomendasi kulkas|replika makanan|permen karet|timing belt|makanan pemicu mules|penikmat kopi|dirty latte|cara menikmati|minum kopi setelah|panduan memilih|silicone vs|lauk awet.*anak kos|sajian ini bikin momen hujan|secangkir kopi dengan penuh kesadaran)\b",
     "tips konsumen, edukasi kesehatan, atau gaya hidup"),

    # Hiburan / olahraga / seni / K-pop / politik praktis / seremonial
    (r"\b(madani film festival|haechan|wishful thinking|nonton bareng|f1 gp|mini soccer|tiket festival|boikot produk ri|pan kotim|fawait|teaterikal|pelantikan paguyuban|art jakarta|mobil kopi pasar aceh|kopi tumpah|segelas kopi, seribu urusan|kopi demokrasi|tos kopi barista|slow bar coffee|tempat ngopi baru)\b",
     "hiburan, seni budaya, olahraga, politik praktis, atau seremonial"),

    # Toko mebel lokal / produk e-commerce / catalog / suku cadang
    (r"\b(set meja garden|kursi cafe jati|jt sprockets|slurry: wmag30|daur ulang ban bekas|methow fishing|sewa panggung kayu|rental tenda roder|regal marie duo|flow meter)\b",
     "katalog produk / toko lokal / alat non-agro"),

    # Halaman profil / company solution vendor
    (r"\b(pabrik minyak kelapa sawit|escolifesciences|esco\b)\b", "profil perusahaan / halaman katalog solusi vendor"),

    # Harga pasar eceran harian / foto getah karet / analisis saham murni
    (r"\b(harga getah karet|harga tbs sawit kaltim|sumbar rebut puncak harga tbs|saham murah sinar mas|saham sinar mas agro.*prospeknya)\b",
     "harga eceran/harian pasar lokal atau analisis saham murni"),

    # Agregator / pencarian / placeholder
    (r"\b(sistem pencarian ikm unggulan|berita terbaru)\b", "placeholder agregator / pencarian"),

    # Berita non-agro umum / infrastruktur umum / sanitasi lokal
    (r"\b(prakiraan cuaca|masker.*pdrn|anatomi kepuasan|arah baru bisnis dan ham|pelatihan mtu|penataan tempat usaha|bendung karet|pembatasan truk saat nataru|sejarah dunia|mesin giling kopi.*paltv|baliem brewing|jago coffee|kopi di kendal|agenda pelatihan|pendaftaran pelatihan vokasi|607 ribu kendaraan|jalan jelek menuju kawasan industri|anggaran kemenko hilirisasi|limbah makanan.*kompos|kumpulan hoaks bantuan|bahaya agp|stok jagung menipis|harga penyediaan makanan|5 alasan bioskop|bpom kunjungi mtsn|data bps 2026|ekonomi paser tumbuh|harga makanan di sirkuit sepang|belanja masyarakat indonesia|hutan adat.*ekspansi sawit|ironi 20 raksasa sawit|ibu kota nusantara|rutan barru|18 depot air minum|jenis air untuk tanaman|buah restan menumpuk)\b",
     "berita non-industri agro / regulasi umum / opini non-industri"),

    # Kerajinan tangan / kriya / tips DIY / kerajinan tempurung kelapa
    (r"\b(kerajinan tangan|ide kreatif kerajinan|tempurung kelapa.*kerajinan|kerajinan.*tempurung|kriya)\b",
     "kerajinan tangan / kriya / tips DIY bukan industri agro"),
]

REVIEW_PATTERNS = [
    # B.1 Riset kampus, inovasi, pengabdian masyarakat agro
    (r"\b(simulasi plant biodiesel.*undip|limbah kulit kopi.*umm|limbah kulit kopi.*mahasiswa|tep ipb.*hutan sagu.*jamur|potensi teh dan serbuk kayu.*ugm)\b",
     "Riset/inovasi kampus hilirisasi komoditas agro (Rule B.1)"),

    # B.2 Program/pernyataan pemda penopang ekonomi daerah
    (r"\b(plt wali kota madiun.*apmmj|plt wali kota madiun.*umkm makanan|sentra ki dan ig kelapa dalam|pemkab sekadau targetkan.*lahan sawit|pemkab sekadau salurkan.*benih|tambrauw kembangkan minyak goreng kelapa|press gathering bondowoso republik kopi|bank jatim dorong brk reborn|pemkab mukomuko tera ulang timbangan pks|panen kakao di kebun dinas waikadada|sukabumi gaspol kembangkan 30\.000 hektare jagung dan singkong untuk bioethanol)\b",
     "Pernyataan/program pemda pengembangan komoditas agro penopang ekonomi (Rule B.2)"),

    # B.3 Permintaan listrik hijau / REC / RE100 dari industri manufaktur
    (r"\b(pelanggan rec bertambah|listrik hijau.*industri|app group.*re100)\b",
     "Permintaan listrik hijau / REC / RE100 dari industri manufaktur (Rule B.3)"),

    # Bioenergi / Limbah agro jadi energi
    (r"\b(biocng|biomethane dari limbah sawit|limbah sawit.*energi terbarukan|pabrik pengelolaan limbah cair kelapa sawit biocng|enam ptbg ptpn iv.*tekan emisi|ptpn iv palmco komitmen optimalisasi ebt|perkembangan bioavtur)\b",
     "Limbah agro / POME jadi energi terbarukan atau bioenergi"),

    # Nilai tambah produk, hilirisasi UMKM & rantai pasok
    (r"\b(sisa pengolahan ikan.*tepung ikan|ahmad luthfi dorong umkm.*pangan lokal|the plantationpreneurs festival|program sawit terampil|gandeng ukindo.*sinar mas.*sawit terampil|kepercayaan kunci kemitraan sawit berkelanjutan|perkuat hilirisasi perkebunan.*kakao dan kelapa|ojk perkuat hilirisasi sabut kelapa|bpdp dukung umkm sawit-kelapa peroleh sertifikat halal|kemitraan sawit berkelanjutan|international coffee day.*regenerative agriculture|laboratorium pembudidayaan rumput laut|pemkab lombok timur mendukung pengembangan rumput laut|luhut dorong hilirisasi rumput laut|satpol pp lumajang.*cukai dan dbhcht|akselerasi program pengembangan komoditas unggulan kakao)\b",
     "Pengembangan nilai tambah, UMKM lokal olahan, atau kemitraan rantai pasok agro"),
]

def classify_article(title: str, text: str = "", url: str = "", source: str = "") -> tuple[str, str]:
    t_clean = (title or "").strip()
    t_low = t_clean.lower()
    u_low = (url or "").lower()

    # Rule C (WAJIB RELEVAN): Kebijakan/pernyataan Menperin/Kemenperin
    if any(k in t_low for k in ["sarmuji", "kemenperin", "menperin", "kementerian perindustrian"]):
        return "relevan", "Kebijakan/pernyataan Menperin/Kemenperin (Rule C)"

    # Rule E: Aksi pendanaan korporasi = BUANG
    operational_exceptions = ["penjualan", "produksi", "laba", "margin", "hedging", "ekspansi pabrik", "harga pulp", "inovasi", "pasar ekspor"]
    has_operational_exception = any(op in t_low for op in operational_exceptions)
    if not has_operational_exception:
        if is_corporate_funding_noise(t_clean):
            return "buang", "pendanaan korporasi: aksi pendanaan/permodalan perusahaan (Rule E)"

    # Rule F: Judul tidak informatif = BUANG
    if not t_clean or is_entity_only_title(t_clean) or re.search(r"^bca sekuritas$", t_low):
        return "buang", "judul tidak informatif: hanya nama entitas tanpa kalimat berita (Rule F)"

    # Special check: Vendor catalog / company profile URL
    if "escolifesciences" in u_low or "ciptafutura" in u_low or "dodolan.jogjakota" in u_low:
        return "buang", "halaman profil perusahaan / katalog solusi vendor"

    # Rule D & Discard checks
    for pat, reason in DISCARD_PATTERNS:
        if "pendanaan korporasi" in reason and has_operational_exception:
            continue
        if re.search(pat, t_low):
            return "buang", reason

    # Filter struktural tambahan
    if is_non_article_structural_noise(title=t_clean, url=url, text=text):
        return "buang", "Filter struktural: placeholder agregator / listing spam"

    # Rule B & Review checks
    for pat, reason in REVIEW_PATTERNS:
        if re.search(pat, t_low):
            return "review", reason

    # Pengecekan komoditas / sektor Ditjen Industri Agro
    agro_commodities = [
        "sawit", "cpo", "kelapa", "kakao", "kopi", "karet", "teh", "tebu", "gula",
        "pulp", "kertas", "mebel", "furnitur", "kayu", "rotan", "rokok", "tembakau",
        "mbdk", "cukai", "susu", "biodiesel", "bioetanol", "bioavtur", "biocng", "pome",
        "bambu", "tapioka", "singkong", "sagu", "rumput laut", "makanan", "minuman",
        "mayora", "chocolatos", "garudafood", "halal", "eudr", "pp kesehatan", "rtmm",
        "sektor industri", "trade expo"
    ]
    if any(c in t_low for c in agro_commodities):
        return "relevan", "Berita industri agro, hilirisasi, ekspor-impor, atau kebijakan ekonomi"

    return "buang", "Bukan isu industri agro atau Ditjen IA"


def main():
    folder_path = "hasil_scrapping/Oktober/2026-10-05"
    print("=" * 70)
    print("MEMPROSES DATASET: 5 OKTOBER 2026")
    print("=" * 70)

    # 1. Load progress.json untuk full text dan metadata
    with open(os.path.join(folder_path, "progress.json"), "r", encoding="utf-8") as f:
        prog_arts = json.load(f).get("articles", [])

    prog_by_url = {a.get("link", "").strip(): a for a in prog_arts}
    prog_by_tit = {a.get("title", "").strip().lower(): a for a in prog_arts}

    # 2. Base candidate articles dari clean_final (70 artikel)
    df_clean = pd.read_excel(os.path.join(folder_path, "all_2026-10-05_clean_final.xlsx"))
    candidates = []
    seen_urls = set()
    seen_titles = set()

    for _, r in df_clean.iterrows():
        u = str(r.get("Link Website", "")).strip()
        t = str(r.get("Title", "")).strip()
        matched = prog_by_url.get(u) or prog_by_tit.get(t.lower()) or {}
        txt = matched.get("text", "")
        kw = str(r.get("Keywords", "") or matched.get("keyword", ""))
        sd = str(r.get("Sumber Data", "") or matched.get("sumber_data", "RSS"))
        media = str(r.get("Media Name", "") or matched.get("media_name", "") or matched.get("source", ""))
        tgl = str(r.get("Tanggal", "") or matched.get("published", "2026-10-05"))

        item = {
            "Tanggal": tgl,
            "Title": t,
            "Link Website": u,
            "Media Name": media,
            "Keywords": kw,
            "Sumber Data": sd,
            "text": txt,
        }
        candidates.append(item)
        if u:
            seen_urls.add(u)
        if t:
            seen_titles.add(t.lower())

    # 3. Penambahan artikel yang sah dari progress.json sesuai Kriteria Selamatkan Ditjen IA
    GENUINE_ADDITIONS_PATTERNS = [
        # Riset kampus inovasi agro (Rule B.1)
        r"simulasi plant biodiesel.*undip",
        r"limbah kulit kopi.*umm",
        r"limbah kulit kopi.*mahasiswa",
        r"tep ipb.*hutan sagu.*jamur",
        r"potensi teh dan serbuk kayu.*ugm",
        # Pemda komoditas agro penopang ekonomi (Rule B.2)
        r"plt wali kota madiun.*apmmj",
        r"plt wali kota madiun.*umkm makanan",
        r"pemkab sekadau targetkan.*lahan sawit",
        r"pemkab sekadau salurkan.*benih",
        r"tambrauw kembangkan minyak goreng kelapa",
        r"sentra ki dan ig kelapa dalam",
        r"perketat pengawasan, pemkab mukomuko tera ulang timbangan pks",
        r"panen kakao di kebun dinas waikadada",
        r"press gathering bondowoso republik kopi",
        r"bank jatim dorong brk reborn",
        # Bioenergi / Hilirisasi / Nilai tambah / Kemitraan
        r"limbah sawit di muratara kini disulap jadi energi terbarukan",
        r"program sawit terampil",
        r"laboratorium pembudidayaan rumput laut di wakatobi",
        r"pemkab lombok timur mendukung pengembangan rumput laut",
        r"sisa pengolahan ikan.*tepung ikan",
        r"ahmad luthfi dorong umkm.*pangan lokal",
        r"perkuat hilirisasi perkebunan.*kakao dan kelapa di kolaka utara",
        r"international coffee day.*regenerative agriculture",
        r"pemerintah evaluasi jelang ekspor batu bara-cpo via dsi",
    ]

    added_count = 0
    for a in prog_arts:
        t = str(a.get("title", "")).strip()
        u = str(a.get("link", "")).strip()
        t_low = t.lower()

        if u in seen_urls or t_low in seen_titles:
            continue

        if any(re.search(pat, t_low) for pat in GENUINE_ADDITIONS_PATTERNS):
            media = str(a.get("source") or a.get("media_name", "")).strip()
            kw = str(a.get("keyword", "")).strip()
            sd = str(a.get("sumber_data", "RSS")).strip()
            tgl = str(a.get("published", "2026-10-05")).strip()
            txt = str(a.get("text", "")).strip()

            item = {
                "Tanggal": tgl,
                "Title": t,
                "Link Website": u,
                "Media Name": media,
                "Keywords": kw,
                "Sumber Data": sd,
                "text": txt,
            }
            candidates.append(item)
            seen_urls.add(u)
            seen_titles.add(t_low)
            added_count += 1

    print(f"Total kandidat sebelum klasifikasi: {len(candidates)} (Base: {len(df_clean)}, Tambahan Sah: {added_count})")

    # 4. Load spokesperson map
    name_map = load_spokesperson_map("keyword/keyword_nama.xlsx")

    # 5. Klasifikasi & Enrichment
    discarded_articles = []
    retained_articles = []

    for art in candidates:
        t = art.get("Title", "")
        txt = art.get("text", "")
        u = art.get("Link Website", "")
        media = art.get("Media Name", "")
        kw = art.get("Keywords", "")
        sd = art.get("Sumber Data", "RSS")
        tgl = art.get("Tanggal", "2026-10-05")

        status, reason = classify_article(t, txt, u, media)

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

        # Status Review: jika review, isi alasan verifikasi; jika relevan, string kosong
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

    # 6. Deduplikasi Media Monitoring:
    # Judul identik DAN media identik = DEDUP TEKNIS (simpan teks lebih panjang)
    # Judul sama tapi beda media = TETAP DIPERTAHANKAN
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

    # 7. Simpan File Output
    out_perbaikan = os.path.join(folder_path, "all_2026-10-05_perbaikan.xlsx")
    out_terbaru = os.path.join(folder_path, "all_2026-10-05_terbaru.xlsx")
    out_main = os.path.join(folder_path, "all_2026-10-05.xlsx")
    out_discard = os.path.join(folder_path, "discarded_articles.json")

    with open(out_discard, "w", encoding="utf-8") as f:
        json.dump(discarded_articles, f, ensure_ascii=False, indent=2)

    save_to_excel(final_records, out_perbaikan, merge_existing=False)
    save_to_excel(final_records, out_terbaru, merge_existing=False)
    save_to_excel(final_records, out_main, merge_existing=False)

    # 8. Verifikasi DataFrame
    df_res = pd.read_excel(out_perbaikan)
    print("\n" + "=" * 70)
    print("[HASIL SELESAI]")
    print(f"Total Input       : {len(candidates)}")
    print(f"Total Dibuang     : {len(discarded_articles)}")
    print(f"Total Lolos Awal  : {len(retained_articles)} (Relevan: {sum(1 for a in retained_articles if a['status'] == 'relevan')}, Review: {sum(1 for a in retained_articles if a['status'] == 'review')})")
    print(f"Total Akhir Dedup : {len(df_res)} baris")
    print(f"Daftar Kolom ({len(df_res.columns)}): {list(df_res.columns)}")
    assert "Sub Sektor" not in df_res.columns, "Kolom Sub Sektor harus dihapus!"
    assert "Isu" not in df_res.columns, "Kolom Isu harus dihapus!"
    assert "Status Review" in df_res.columns, "Kolom Status Review harus ada!"
    assert len(df_res.columns) == 12, f"Kolom harus tepat 12, bukan {len(df_res.columns)}"

    print(f"\nDistribusi Status Review:")
    print(df_res["Status Review"].value_counts(dropna=False).head(10).to_string())

    print(f"\nDistribusi Tone:")
    print(df_res["Tone"].value_counts(dropna=False).to_string())

    print(f"\nDistribusi Terkait Kemenperin:")
    print(df_res["Terkait Kemenperin"].value_counts(dropna=False).to_string())
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()
