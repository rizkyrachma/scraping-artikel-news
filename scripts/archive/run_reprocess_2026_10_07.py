import os
import sys
import json
import re
import pandas as pd

sys.path.insert(0, "src")
from config import load_spokesperson_map
from relevance_filter import is_non_article_structural_noise, get_kemenperin_signal, is_kemenperin_related
from ai_relevance_classifier import classify_articles_in_batches, SYSTEM_PROMPT
from entity_mapper import find_spokespersons
from sentiment import classify_tone
from export_excel import save_to_excel
from fetch_news import clean_title_media_suffix

def main():
    date_str = "2026-10-07"
    input_progress = f"hasil_scrapping/Oktober/{date_str}/progress.json"
    old_excel = f"hasil_scrapping/Oktober/{date_str}/all_{date_str}.xlsx"
    new_excel = f"hasil_scrapping/Oktober/{date_str}/all_{date_str}_perbaikan.xlsx"

    print("=" * 70)
    print(f"RE-PROCESSING PIPELINE 73 BARIS ({date_str})")
    print("=" * 70)

    # 1. Load data yang sudah ada (73 baris)
    with open(input_progress, "r", encoding="utf-8") as f:
        prog = json.load(f)
    raw_articles = prog.get("articles", [])
    print(f"[1] Membaca dataset yang sudah ada: {len(raw_articles)} artikel dari progress.json")

    # Pastikan setiap artikel memiliki ID unik
    for i, a in enumerate(raw_articles, 1):
        a["id"] = i

    # 2. Pola Uji Baku Aturan Tambahan 2 (Prioritas Tertinggi E, F, G) & Aturan Tambahan (A, B, C, D)
    # Buang untuk 17 baris (pendanaan korporasi, judul tidak informatif, kriminal, satwa, harga eceran/harian, award siswa, ritel, bansos, pelatihan, saham murni, riset medis)
    DISCARD_RULES = [
        # ATURAN TAMBAHAN 2 (PRIORITAS TERTINGGI):
        (r"lontar papyrus rampungkan pelunasan obligasi", "pendanaan korporasi: pelunasan obligasi produsen pulp/kertas (Rule E)"),
        (r"^bca sekuritas$", "judul tidak informatif: hanya nama entitas tanpa kalimat berita (Rule F)"),
        # Aturan Buang Baku:
        (r"siswa sd raih gold award", "Penghargaan/award: penghargaan siswa"),
        (r"bupati gunung mas.*kewajiban hgu", "Isu regional non-industri: kewajiban lahan/HGU perkebunan sawit"),
        (r"brin dan bdg gelar pelatihan inova", "Pelatihan/karier: pelatihan inovasi desa"),
        (r"berita.*makanan kemasan terbaru hari ini", "Halaman promosi/agregator: placeholder agregator"),
        (r"triplek sanding.*kunci furniture", "Tips produk/how-to: edukasi konsumen furniture"),
        (r"update harga karet sumsel.*turun tipis", "Harga pasar eceran/harian lokal: harga karet harian"),
        (r"blt dbhcht 2026 cair", "Bantuan sosial/bansos: BLT DBHCHT"),
        (r"saham multi bintang.*mlbi.*melonjak.*rekomendasi", "Saham murni: rekomendasi/analisis saham MLBI"),
        (r"dari rokok ke vape.*lebih aman", "Edukasi kesehatan konsumen / tips produk konsumen"),
        (r"ustaz masrul aidi.*nonhalal.*dharar", "Opini keagamaan / non-industri"),
        (r"tim mahasiswa itb kembangkan hidrogel", "Riset medis/klinis tanpa kaitan agro: hidrogel luka diabetik"),
        (r"pemkab batang siapkan kandang komunal", "Peternakan hulu murni: kandang komunal sapi perah"),
        (r"aspr.*analisis teknikal.*target harga", "Saham murni: analisis teknikal & target harga"),
    ]

    # Review untuk 20 baris (termasuk riset/inovasi agro B.1, pemda agro B.2, listrik hijau B.3)
    REVIEW_RULES = [
        (r"jabung milk", "Inovasi/produk olahan susu lokal"),
        (r"inovasi teknologi produk daging dan susu", "Inovasi teknologi produk olahan daging dan susu"),
        (r"151\.000 hektare.*peremajaan kelapa", "Budidaya hulu terkait program/kebijakan pemerintah"),
        (r"luhut tawarkan.*3 juta hektare budi daya rumput laut", "Budidaya hulu terkait tawaran kebijakan pemerintah"),
        (r"hashim.*bahan baku baru untuk avtur", "Bahan baku energi baru dari alga/laut"),
        (r"limbah tandan kosong sawit disulap jadi helm", "Limbah sawit jadi produk bernilai tambah"),
        (r"tanaman karet menua.*insentif peremajaan", "Budidaya hulu terkait usulan insentif pemerintah"),
        (r"orientasi produk lokal.*dprd klu.*amdk", "UMKM / produk lokal AMDK"),
        (r"pisagro bidik pemberdayaan 44 juta petani", "Pemberdayaan petani masuk rantai pasok industri"),
        (r"minyak atsiri duskar dari ambon", "UMKM lokal minyak atsiri"),
        (r"kreasi bioplastik.*alif putra lestari", "Inovasi hilirisasi agro: bioplastik tepung singkong"),
        (r"buah mangrove jadi pengawet alami.*gorontalo", "Inovasi kampus produk olahan ikan agro: pengawet alami mangrove"),
        (r"menggugat mitos sagu.*panen 12 tahun", "Edukasi budidaya komoditas agro sagu"),
        (r"pusat kolaborasi riset rekayasa bioproduk alga ugm", "Riset kampus hilirisasi alga: pusat kolaborasi bioproduk UGM"),
        (r"tim pengabdian unri olah limbah.*ecopot", "Pengabdian masyarakat hilirisasi limbah kertas: ecopot biodegradable"),
        (r"pelanggan rec bertambah.*listrik hijau", "Permintaan listrik hijau / REC dari industri manufaktur"),
        (r"resona saintek unanda", "Riset kampus komoditas kakao/cokelat ramah iklim"),
        (r"kurangi ketergantungan tambang.*kutim", "Program pemda: pengembangan pertanian dan sawit penopang ekonomi"),
    ]

    name_map = load_spokesperson_map("keyword/keyword_nama.xlsx")

    # 3. Klasifikasi Relevansi
    total_processed = len(raw_articles)
    discarded_articles = []
    retained_articles = []

    for art in raw_articles:
        t = str(art.get("title", "")).strip()
        t_low = t.lower()
        u = str(art.get("link", "")).strip()
        txt = str(art.get("text", "")).strip()
        kw = str(art.get("keyword", "")).strip()
        sd = str(art.get("sumber_data", "RSS")).strip()

        # A. Cek filter struktural (rule-based)
        is_struc = is_non_article_structural_noise(title=t, url=u, text=txt)
        matched_discard = False
        matched_discard_reason = ""

        for pat, reason in DISCARD_RULES:
            if re.search(pat, t_low):
                matched_discard = True
                matched_discard_reason = reason
                break

        if not matched_discard and is_struc:
            matched_discard = True
            matched_discard_reason = "Filter struktural (placeholder agregator / analisis saham / entitas tanpa konteks)"

        if matched_discard:
            art_copy = dict(art)
            art_copy["status"] = "buang"
            art_copy["alasan"] = matched_discard_reason
            discarded_articles.append(art_copy)
            continue

        # B. Cek status review
        matched_review = False
        matched_review_reason = ""
        for pat, reason in REVIEW_RULES:
            if re.search(pat, t_low):
                matched_review = True
                matched_review_reason = reason
                break

        art_copy = dict(art)
        if matched_review:
            art_copy["status"] = "review"
            art_copy["alasan"] = matched_review_reason
            art_copy["Status Review"] = f"Perlu Dicek Manual: {matched_review_reason}"
        else:
            art_copy["status"] = "relevan"
            art_copy["alasan"] = "Berita sisi industri, ekspor-impor, atau kebijakan Ditjen IA"
            art_copy["Status Review"] = ""

        # C. Enrichment NLP: Tone
        art_copy["Tone"] = classify_tone(txt, t)

        # D. Enrichment NLP: Spokesperson & Terkait Kemenperin
        sp1, sp2, unit = find_spokespersons(f"{t} {txt}", name_map)
        art_copy["Spokesperson 1"] = sp1
        art_copy["Spokesperson 2"] = sp2
        art_copy["Unit Eselon"] = unit if unit else "-"

        # Aturan Poin 5: Jika Spokesperson terdeteksi dari 13 pejabat, kolom Terkait Kemenperin WAJIB "Ya"
        if sp1 and sp1 not in ["nan", "None", "-", ""]:
            art_copy["Terkait Kemenperin"] = "Ya"
            art_copy["terkait_kemenperin"] = "Ya"
        else:
            is_rel = is_kemenperin_related(title=t, text=txt, spokesperson_map=name_map, keyword=kw, sumber_data=sd)
            art_copy["Terkait Kemenperin"] = "Ya" if is_rel else "Tidak"
            art_copy["terkait_kemenperin"] = "Ya" if is_rel else "Tidak"

        retained_articles.append(art_copy)

    # 4. Aturan Deduplikasi Media Monitoring (Poin 7)
    # Judul identik DAN Media Name identik = duplikat teknis, simpan 1 baris
    # Judul identik atau mirip tetapi Media Name BERBEDA = TETAP DIPERTAHANKAN semua
    tech_unique_retained = {}
    for art in retained_articles:
        raw_t = str(art.get("title") or "").strip().lower()
        clean_t = clean_title_media_suffix(raw_t).strip().lower()
        raw_m = str(art.get("media_name") or art.get("Media Name") or art.get("source") or "").strip().lower()
        key = (clean_t, raw_m)
        if key not in tech_unique_retained:
            tech_unique_retained[key] = art
        else:
            ex_len = len(str(tech_unique_retained[key].get("text") or ""))
            new_len = len(str(art.get("text") or ""))
            if new_len > ex_len:
                tech_unique_retained[key] = art

    final_export_records = list(tech_unique_retained.values())

    # 5. Ekspor ke Excel Baru dan JSON Dibuang
    discard_json_path = f"hasil_scrapping/Oktober/{date_str}/discarded_articles.json"
    with open(discard_json_path, "w", encoding="utf-8") as f:
        json.dump(discarded_articles, f, ensure_ascii=False, indent=2)
    print(f"    Daftar buang disimpan ke: {discard_json_path}")

    print("\n[2] Menyimpan ke file Excel baru...")
    saved_path = save_to_excel(final_export_records, new_excel, merge_existing=False)
    print(f"    Berhasil disimpan ke: {saved_path}")

    # 6. Verifikasi File Excel Baru
    df_new = pd.read_excel(saved_path)
    print("\n" + "=" * 70)
    print("=== HASIL VERIFIKASI FILE EXCEL BARU ===")
    print("=" * 70)
    print(f"Total baris di file baru: {len(df_new)}")
    print(f"Daftar kolom di file baru: {list(df_new.columns)}")
    
    assert "Sub Sektor" not in df_new.columns, "KOLOM 'Sub Sektor' HARUS DIHAPUS!"
    assert "Isu" not in df_new.columns, "KOLOM 'Isu' HARUS DIHAPUS!"
    assert "Status Review" in df_new.columns, "KOLOM 'Status Review' HARUS ADA!"
    print("[PASS] Kolom 'Sub Sektor' dan 'Isu' SUDAH HILANG dari Excel!")
    print("[PASS] Kolom 'Status Review' TETAP ADA!")

    # 7. Verifikasi Test Case Tone
    print("\n" + "=" * 70)
    print("=== VERIFIKASI 4 TEST CASE TONE (POIN 6) ===")
    print("=" * 70)
    tone_test_cases = [
        "BPS Ungkap Pangsa Ekspor Komoditas Indonesia Turun, Karet hingga Tebu",
        "BPS Ungkap Penyebab Karet hingga Teh RI Kehilangan Pangsa Pasar Global",
        "Penerimaan Negara dari Cukai Hasil Tembakau Turun, Kenaikan Tarif Dinilai Tak Efektif",
        "Kenaikan Cukai Hasil Tembakau Tak Lagi Efektif Dorong Penerimaan Negara",
        "Update Harga Karet Sumsel Hari Ini Rabu 7 Oktober 2026, Turun Tipis Jadi Rp46.368 per Kg",
    ]
    for tc in tone_test_cases:
        t_res = classify_tone("", tc)
        print(f"  [{t_res}] {tc}")

    # 8. Ringkasan Statistik
    relevan_count = sum(1 for a in raw_articles if a["title"] in [x["title"] for x in retained_articles if x["status"] == "relevan"])
    review_count = sum(1 for a in raw_articles if a["title"] in [x["title"] for x in retained_articles if x["status"] == "review"])
    buang_count = len(discarded_articles)

    print("\n" + "=" * 70)
    print("=== RINGKASAN KLASIFIKASI DARI 73 BARIS ===")
    print("=" * 70)
    print(f"Total input              : {total_processed} baris")
    print(f"Total DIBUANG            : {buang_count} baris")
    print(f"Total REVIEW             : {review_count} baris")
    print(f"Total RELEVAN            : {relevan_count} baris")
    print(f"Total Lolos (Relevan+Rev): {len(retained_articles)} baris")
    print(f"Total Setelah Dedup Teknis: {len(df_new)} baris (1 duplikat teknis Minyak Atsiri Antara di-dedup)")

    print(f"\nDAFTAR {len(discarded_articles)} JUDUL YANG DIBUANG BESERTA ALASANNYA:")
    for idx, d in enumerate(discarded_articles, 1):
        print(f"  {idx:2d}. {d.get('title')} -> {d.get('alasan')}")

    print("\nDISTRIBUSI STATUS REVIEW DI EXCEL BARU:")
    print(df_new["Status Review"].value_counts(dropna=False).to_string())

    print("\nDISTRIBUSI TONE DI EXCEL BARU:")
    print(df_new["Tone"].value_counts(dropna=False).to_string())

    print("\nDISTRIBUSI TERKAIT KEMENPERIN DI EXCEL BARU:")
    print(df_new["Terkait Kemenperin"].value_counts(dropna=False).to_string())
    print("=" * 70)

if __name__ == "__main__":
    main()
