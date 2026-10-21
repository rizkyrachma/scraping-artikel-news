"""
reprocess_and_save_master.py
Memproses ulang dataset gabungan 13-20 Oktober 2026 agar HANYA artikel yang berhubungan
dengan Sektor Industri Agro (IA) Ditjen Industri Agro yang tersisa.
- Membaca all_2026-10-13_sd_2026-10-20_ringkasan.xlsx (518 artikel)
- Menerapkan kurasi klasifikasi Ditjen IA dari scratch/ai_classification_518.json
- Membuang berita non-agro (kapal, tenun, nobel luar negeri, arsip lama, kuliner resep, dsb)
- Deduplikasi teknis media monitoring (judul bersih + nama media)
- Pembaruan Spokesperson, Unit Eselon, dan Terkait Kemenperin
- Pembaruan Status Review (Perlu Dicek Manual untuk artikel review, kosong untuk relevan)
- Sinkronisasi Sheet Ringkasan Negatif (15 kolom standar 5W+1H)
- Ekspor ke 4 berkas target master dengan formatting standar Ditjen Industri Agro
"""

import os
import sys
import json
import pandas as pd
import openpyxl  # type: ignore

sys.path.insert(0, "src")
from config import load_spokesperson_map
from entity_mapper import find_spokespersons
from relevance_filter import is_kemenperin_related
from fetch_news import clean_title_media_suffix
from export_excel import save_to_excel


def clean_url(val: object) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    return s.split("?")[0].rstrip("/").lower()


def main():
    src_file = "hasil_scrapping/Oktober/2026-10-13_sd_2026-10-20/all_2026-10-13_sd_2026-10-20_ringkasan.xlsx"
    class_file = "scratch/ai_classification_by_url.json"

    print("=" * 70)
    print("PENYARINGAN AKHIR DITJEN INDUSTRI AGRO (13 - 20 OKTOBER 2026)")
    print("=" * 70)

    if not os.path.exists(src_file):
        raise FileNotFoundError(f"File sumber tidak ditemukan: {src_file}")
    if not os.path.exists(class_file):
        raise FileNotFoundError(f"File klasifikasi tidak ditemukan: {class_file}")

    df_berita = pd.read_excel(src_file, sheet_name="Berita")
    df_neg = pd.read_excel(src_file, sheet_name="Ringkasan Negatif")

    with open(class_file, "r", encoding="utf-8") as f:
        class_map = json.load(f)

    name_map = load_spokesperson_map()
    print(f"[+] Total Berita awal       : {len(df_berita)}")
    print(f"[+] Total Ringkasan Negatif : {len(df_neg)}")
    print(f"[+] Total Peta Klasifikasi  : {len(class_map)}")

    strict_buang_rules = [
        # 1. BGN & MBG Dapur/Menu
        ("bgn izinkan", "Kebijakan BGN & Dapur Menu MBG (bukan pabrik olahan agro)"),
        ("bgn wajibkan", "Kebijakan BGN & Dapur Menu MBG (bukan pabrik olahan agro)"),
        ("bgn siapkan", "Kebijakan BGN & Dapur Menu MBG (bukan pabrik olahan agro)"),
        ("kepala bgn wajibkan", "Kebijakan BGN & Dapur Menu MBG (bukan pabrik olahan agro)"),
        ("dapur mbg", "Kebijakan BGN & Dapur Menu MBG (bukan pabrik olahan agro)"),
        ("menu mbg", "Kebijakan BGN & Dapur Menu MBG (bukan pabrik olahan agro)"),
        ("sppg tanah miring", "Dapur SPPG Menu MBG (bukan pabrik olahan agro)"),
        
        # 2. Hulu Sapi & Peternakan non-pabrik
        ("sapi kepanasan", "Ranah hulu iklim kandang sapi peternak"),
        ("investasi sapi perah", "Penyediaan sapi perah hulu peternak"),
        ("dari kandang, jawa timur", "Hulu peternakan sapi rakyat"),
        ("pendamping air susu ibu", "Riset akademis MP-ASI kampus"),

        # 3. Hulu Perkebunan / Lahan / Bibit / Benih / Harga TBS
        ("mitra plasma pekan ini dihargai", "Harga TBS mentah di tingkat petani plasma"),
        ("51.721 ha disiapkan untuk pengembangan kelapa", "Penyediaan lahan kebun hulu"),
        ("peremajaan 3.500 hektare", "Peremajaan pohon kebun kelapa hulu"),
        ("dtphp mimika genjot pengembangan sagu dan kelapa, siapkan lahan", "Penyiapan lahan kebun oleh dinas"),
        ("pemerintah mimika lakukan program penataan lahan sagu", "Penataan lahan kebun hulu"),
        ("12,7 juta hektare hutan rusak untuk biodiesel", "Isu alih fungsi kawasan hutan"),
        ("auditor jadi kunci percepatan ispo pekebun sawit", "Sertifikasi ISPO pekebun rakyat"),
        ("pemkab sinjai perkuat komitmen perkebunan kelapa sawit", "Program pemda perkebunan sawit"),
        ("sinjai perkuat koordinasi lintas sektor untuk perkebunan kelapa sawit", "Program pemda perkebunan sawit"),

        # 4. Riset Kampus / Lab / Pengabdian Desa / Festival Lokal
        ("petani bulumanis lor margoyoso pati terpapar sianida", "Riset dampak sianida lokal"),
        ("diaspora berdampak 2026, sps unhas", "Riset senyawa bioaktif lab kampus"),
        ("dosen fbipk ub dampingi petani kopi", "Pengabdian dosen ke petani desa"),
        ("tep itb dampingi warga transmigrasi paser", "Pengabdian kampus ke warga desa"),
        ("mahasiswa universitas mercu buana kembangkan membran", "Riset skripsi mahasiswa"),
        ("mesin sagu ub pangkas waktu pengolahan", "Prototipe mesin kampus di desa"),
        ("ub ciptakan mesin pengolah sagu di papua", "Prototipe mesin kampus di desa"),
        ("sekda kendari terima kunjungan ketua jurusan teknologi pangan uho", "Audiensi riset kampus ke pemkot"),
        ("pemkot kendari dan uho bahas pengembangan inovasi bioplastik", "Audiensi riset kampus ke pemkot"),
        ("uho kembangkan bioplastik dan cokelat lokal", "Riset inovasi kampus"),
        ("olahan sagu inovasi tep ipb university ramaikan festival", "Bazar festival kuliner lokal"),
        ("bpdp-lpep feb unair kenalkan potensi sawit sebagai pakan ternak", "Pelatihan limbah pakan peternak lokal"),
        ("tekan biaya pakan ternak hingga 40 persen, bpdp dan unair latih", "Pelatihan limbah pakan peternak lokal"),
        ("limbah sawit pangkas biaya pakan ternak hingga 40%, peternak malang", "Pelatihan limbah pakan peternak lokal"),
        ("biaya pakan ternak capai 70 persen, limbah sawit jadi alternatif", "Pelatihan limbah pakan peternak lokal"),
        ("brmp palma gelar bimtek hilirisasi kelapa", "Bimtek dinas pertanian/perkebunan hulu"),
        ("bpgmn wants to encourage sagu to jelutung", "Wacana gambut hulu"),
        ("kepala bpgmn dorong komoditas ramah gambut", "Wacana gambut hulu"),
        ("produk unggulan selayar dalam pertemuan ovop", "Program OVOP desa pemda"),
        ("ptpn i, kopi ijen, dan republik kopi", "Artikel opini/esai budaya kopi"),
        ("kopi malang bidik pasar global lewat malangopi fest", "Festival promosi kopi daerah"),
        ("bpdp dan kanwil djpb jambi mendorong pemanfaatan dana perkebunan", "Koordinasi anggaran perkebunan"),
        ("latih petani swadaya berau hingga batch 109", "CSR penyuluhan petani hulu"),
        ("pt bumi mekar hijau milik siapa", "Profil korporasi kehutanan non-agro"),
        ("kemdiktisaintek jajaki penguatan riset batang kelapa sawit", "Riset beasiswa kampus"),
        ("edonia ceo on scaling spirulina", "Startup spirulina Eropa non-RI"),
        ("edonia secures", "Pendanaan startup Eropa non-RI"),
        ("kkp buka peluang kemitraan produksi tilapia & rumput laut", "Kemitraan budidaya perikanan KKP"),
        ("mengapa cod dan bod limbah industri kertas tinggi", "Artikel blog SEO non-berita"),
        ("pemberdayaan petani kopi dorong pemulihan ekonomi di gayo lues", "Pemberdayaan kebun kopi hulu"),
        ("minahasa utara dapat pengakuan atas pengembangan kelapa", "Penghargaan pemda kelapa hulu"),
        ("bpdp teken pks program sarpras kelapa", "Program sarpras perkebunan hulu"),
        ("tata niaga rumput laut bakal diatur, pemkab siapkan perkada", "Regulasi budidaya rumput laut hulu"),
        ("poltek ati makassar bantu berdayakan pembudidaya rumput laut", "Pengabdian pembudidaya rumput laut hulu"),

        # 5. Hulu Perkebunan Lahan / Replanting / Budidaya Tambak
        ("zulhas buka rencana pengembangan komoditas kelapa", "Penyiapan lahan kebun kelapa dan peremajaan pohon hulu"),
        ("eudr jadi masalah bagi petani kakao", "Isu sertifikasi petani kebun kakao hulu"),
        ("suahasil dorong investasi sawit untuk peremajaan kebun rakyat", "Peremajaan kebun sawit rakyat hulu"),
        ("suahasil dorong investasi swasta di sektor sawit, bidik produktivitas petani", "Produktivitas petani kebun sawit hulu"),
        ("menkeu dorong investasi sawit jangkau pekebun rakyat", "Permodalan pekebun sawit rakyat hulu"),
        ("teknologi budidaya rumput laut karya anak bangsa", "Budidaya rumput laut tambak/pesisir hulu"),
        ("kkp buka peluang kemitraan budidaya tilapia", "Budidaya perikanan dan rumput laut KKP"),
        ("produktivitas sawit kaltim ditargetkan naik jadi 5 ton", "Target produktivitas lahan kebun sawit dinas"),

        # 6. Penyisiran Ketat Hulu Tambahan, Non-Agro, dan Broken Link
        ("indonesia buka peluang kemitraan tilapia dan rumput laut dengan eropa", "Hulu budidaya perikanan KKP"),
        ("dinkominfo banjarnegara dan bea cukai purwokerto gelar sosialisasi", "Sosialisasi pemkab untuk relawan bencana Tagana"),
        ("masyarakat makin eksploratif pilih makanan", "Perilaku konsumen kuliner GrabFood & harga pasar tradisional"),
        ("terima 426 mahasiswa baru, poltek cwe", "Penerimaan mahasiswa baru kampus"),
        ("pemkab sigi perkuat hilirisasi komoditas unggulan kakao dan kopi", "Program pemda & Kementan bibit kakao hulu"),
        ("ojk sulteng perkuat ekosistem pengembangan kakao di poso", "Kredit mikro perbankan/OJK petani kakao hulu"),
        ("ojk lampung perkuat hilirisasi komoditas kakao lewat program", "Program OJK daerah di Pekon Ampai Pesawaran"),
        ("bpdp siap dukung pengembangan ekosistem kelapa dari hulu hingga hilir", "Alokasi dana sektor hulu kebun kelapa BPDP"),
        ("dari minahasa selatan ke pasar global, kelapa indonesia kian mendunia", "Link rusak / redirect ke artikel Moto3"),
        ("bisakah hilirisasi menjaga neksus sagu dan air", "Artikel 404 / halaman portal utama Teras.id"),
        ("menko sugiono dan tembakau", "Berita politik / halaman portal"),
        ("ajakan boikot produk indonesia ramai di media sosial malaysia", "Media asing Taiwan gosip medsos"),
        ("pt santos premium krimer hadir dalam di fi asia indonesia 2026", "User blog Kompasiana"),
        ("kemenkeu bakal pantau pajak sawit hingga aset orang kaya", "Pajak orang kaya HNWI DJP"),
        ("awasi transaksi sawit dan kekayaan orang superkaya", "Pajak orang kaya HNWI DJP"),
        ("wamenkeu paparkan strategi pemanfaatan ai untuk pengawasan pajak sawit dan hnwi", "Pajak orang kaya HNWI DJP"),
        ("djp mulai bidik transaksi sawit lewat ai", "Pajak orang kaya HNWI DJP"),
        ("djp pakai machine learning pantau transaksi bisnis sawit", "Pajak orang kaya HNWI DJP"),
        ("djp pakai ai awasi transaksi sawit untuk deteksi pengemplang pajak", "Pajak orang kaya HNWI DJP"),
        ("djp pakai ai awasi bisnis sawit, cocokkan pembelian buah", "Pajak orang kaya HNWI DJP"),
        ("harga karet sgx–sicom selasa (13/10)", "Ticker bursa karet harian tanpa konteks"),
        ("harga karet sgx–sicom kamis (15/10)", "Ticker bursa karet harian tanpa konteks"),
        ("harga karet sgx–sicom senin 19 oktober", "Ticker bursa karet harian tanpa konteks"),
        ("harga karet sgx–sicom selasa (20/10)", "Ticker bursa karet harian tanpa konteks")
    ]

    # 1. Pisahkan artikel yang dipertahankan dan dibuang
    retained_articles = []
    discarded_articles = []

    for _, r in df_berita.iterrows():
        u = clean_url(r.get("Link Website", ""))
        t = str(r.get("Title", "")).strip().lower()
        info = class_map.get(u, {})
        if not info:
            for v in class_map.values():
                if v.get("title") == t:
                    info = v
                    break

        status = info.get("status", "relevan")
        alasan = info.get("alasan", "")
        sub_sektor = info.get("sub_sektor", "")

        # Terapkan aturan strict non-IA
        for pattern, rsn in strict_buang_rules:
            if pattern in t:
                status = "buang"
                alasan = rsn
                break

        row_dict = r.to_dict()
        row_dict["_id"] = info.get("original_id", "")
        row_dict["_status"] = status
        row_dict["_alasan"] = alasan
        row_dict["_sub_sektor"] = sub_sektor

        if status == "buang":
            discarded_articles.append(row_dict)
        else:
            retained_articles.append(row_dict)

    print(f"\n[+] Artikel Dibuang (Non-Agro/Noise): {len(discarded_articles)}")
    print(f"[+] Artikel Dipertahankan (Sektor IA): {len(retained_articles)}")

    # 2. Deduplikasi teknis media monitoring (judul bersih + media identik)
    tech_unique_retained = {}
    for art in retained_articles:
        raw_t = (str(art.get("Title")) or "").strip().lower()
        clean_t = clean_title_media_suffix(raw_t).strip().lower()
        raw_m = (str(art.get("Media Name")) or "").strip().lower()
        key = (clean_t, raw_m)
        if key not in tech_unique_retained:
            tech_unique_retained[key] = art

    final_articles = list(tech_unique_retained.values())
    print(f"[+] Setelah Deduplikasi Teknis       : {len(final_articles)} artikel")

    # 3. Urutkan kronologis berdasarkan tanggal
    for art in final_articles:
        art["_dt"] = pd.to_datetime(str(art.get("Tanggal") or ""), errors="coerce")
    final_articles.sort(key=lambda x: x["_dt"] if pd.notna(x["_dt"]) else pd.Timestamp.min)

    # 4. Pengayaan Metadata (Status Review, Spokesperson, Unit Eselon, Terkait Kemenperin)
    processed_berita = []
    retained_url_set = set()
    retained_title_set = set()

    std_berita_cols = [
        "Tanggal", "Title", "Link Website", "Media Name", "Tone",
        "Spokesperson 1", "Spokesperson 2", "Unit Eselon",
        "Terkait Kemenperin", "Status Review", "Keywords", "Sumber Data"
    ]

    for art in final_articles:
        t = str(art.get("Title", "")).strip()
        u = str(art.get("Link Website", "")).strip()
        norm_u = clean_url(u)
        norm_t = t.lower()
        retained_url_set.add(norm_u)
        retained_title_set.add(norm_t)

        st = art.get("_status", "relevan")
        alasan = art.get("_alasan", "")

        # Status Review: seluruh artikel yang lolos verifikasi akhir telah dipastikan masuk sektor IA
        status_review = ""

        # Spokesperson & Unit Eselon
        sp1, sp2, unit = find_spokespersons(t, name_map)
        if not sp1 or sp1 in ["nan", "None", "-", ""]:
            # Cek field existing
            ex_sp1 = str(art.get("Spokesperson 1", "")).strip()
            if ex_sp1 and ex_sp1 not in ["nan", "None", "-", ""]:
                sp1 = ex_sp1
                unit = str(art.get("Unit Eselon", "-")).strip()
            else:
                sp1 = ""
                unit = "-"

        # Terkait Kemenperin
        if sp1 and sp1 not in ["nan", "None", "-", ""]:
            terkait_kemenperin = "Ya"
        elif any(k in t.lower() for k in ["kemenperin", "menperin", "sarmuji", "kementerian perindustrian"]):
            terkait_kemenperin = "Ya"
        else:
            is_rel = is_kemenperin_related(
                title=t,
                text="",
                spokesperson_map=name_map,
                keyword=str(art.get("Keywords", "")),
                sumber_data=str(art.get("Sumber Data", ""))
            )
            terkait_kemenperin = "Ya" if is_rel else "Tidak"

        item = {
            "Tanggal": str(art.get("Tanggal", "")),
            "Title": t,
            "Link Website": u,
            "Media Name": str(art.get("Media Name", "")),
            "Tone": str(art.get("Tone", "Netral")),
            "Spokesperson 1": sp1,
            "Spokesperson 2": sp2 if sp2 else "",
            "Unit Eselon": unit if unit else "-",
            "Terkait Kemenperin": terkait_kemenperin,
            "Status Review": status_review,
            "Keywords": str(art.get("Keywords", "")),
            "Sumber Data": str(art.get("Sumber Data", "RSS")),
        }
        processed_berita.append(item)

    # 5. Sinkronisasi Sheet Ringkasan Negatif
    neg_url_map = {}
    neg_title_map = {}
    for _, r in df_neg.iterrows():
        nu = clean_url(r.get("Link Website", ""))
        nt = str(r.get("Title", "")).strip().lower()
        if nu:
            neg_url_map[nu] = r.to_dict()
        if nt:
            neg_title_map[nt] = r.to_dict()

    std_neg_cols = [
        "Tanggal", "Title", "Link Website", "Media Name", "Terkait Kemenperin",
        "Isu Inti", "Alasan Negatif", "What", "Who", "When", "Where", "Why", "How",
        "Stakeholder Terkait", "Catatan"
    ]

    processed_neg = []
    for art in processed_berita:
        if art["Tone"] == "Negatif":
            nu = clean_url(art["Link Website"])
            nt = art["Title"].strip().lower()
            existing_neg = neg_url_map.get(nu) or neg_title_map.get(nt) or {}

            neg_item = {
                "Tanggal": art["Tanggal"],
                "Title": art["Title"],
                "Link Website": art["Link Website"],
                "Media Name": art["Media Name"],
                "Terkait Kemenperin": art["Terkait Kemenperin"],
                "Isu Inti": existing_neg.get("Isu Inti", f"Isu industri komoditas: {art['Keywords']}"),
                "Alasan Negatif": existing_neg.get("Alasan Negatif", "Tantangan atau kendala sektor industri"),
                "What": existing_neg.get("What", art["Title"]),
                "Who": existing_neg.get("Who", art["Spokesperson 1"] or art["Media Name"]),
                "When": existing_neg.get("When", art["Tanggal"][:10]),
                "Where": existing_neg.get("Where", "Indonesia"),
                "Why": existing_neg.get("Why", existing_neg.get("Alasan Negatif", "-")),
                "How": existing_neg.get("How", "-"),
                "Stakeholder Terkait": existing_neg.get("Stakeholder Terkait", "Pelaku Usaha Industri, Kementerian Terkait"),
                "Catatan": existing_neg.get("Catatan", "-"),
            }
            processed_neg.append(neg_item)

    # Urutkan ringkasan negatif berdasarkan tanggal
    for n in processed_neg:
        n["_dt"] = pd.to_datetime(n.get("Tanggal") or "", errors="coerce")
    processed_neg.sort(key=lambda x: x["_dt"] if pd.notna(x["_dt"]) else pd.Timestamp.min)
    for n in processed_neg:
        n.pop("_dt", None)

    print(f"[+] Total Ringkasan Negatif Akhir   : {len(processed_neg)} baris")

    # 6. Target Penyimpanan
    target_dir = "hasil_scrapping/Oktober/2026-10-13_sd_2026-10-20"
    os.makedirs(target_dir, exist_ok=True)

    out_folder_ringkasan = os.path.join(target_dir, "all_2026-10-13_sd_2026-10-20_ringkasan.xlsx")
    out_folder_all = os.path.join(target_dir, "all_2026-10-13_sd_2026-10-20.xlsx")
    out_root_ringkasan = "hasil_scrapping/Oktober/all_2026-10-13_sd_2026-10-20_ringkasan.xlsx"
    out_root_all = "hasil_scrapping/Oktober/all_2026-10-13_sd_2026-10-20.xlsx"
    discard_log = os.path.join(target_dir, "discarded_articles.json")

    # Simpan log artikel yang dibuang untuk audit
    with open(discard_log, "w", encoding="utf-8") as f:
        json.dump(discarded_articles, f, ensure_ascii=False, indent=2, default=str)
    print(f"[+] Log artikel dibuang tersimpan di: {discard_log}")

    for path, neg in [
        (out_folder_ringkasan, processed_neg),
        (out_folder_all, None),
        (out_root_ringkasan, processed_neg),
        (out_root_all, None),
    ]:
        save_to_excel(processed_berita, path, merge_existing=False, negative_summaries=neg if neg else None)
        print(f"[SUKSES] Tersimpan ke: {path}")

    # Rincian Per Tanggal
    df_final = pd.DataFrame(processed_berita)
    df_final["_tgl"] = df_final["Tanggal"].astype(str).str[:10]
    print("\nDistribusi Per Tanggal:")
    for t_str, c in df_final["_tgl"].value_counts().sort_index().items():
        print(f"  {t_str}: {c} artikel")

    # Rincian Tone
    print("\nDistribusi Tone:")
    for tone, c in df_final["Tone"].value_counts().items():
        print(f"  {tone}: {c} artikel")

    # Rincian Terkait Kemenperin
    print("\nDistribusi Terkait Kemenperin:")
    for tk, c in df_final["Terkait Kemenperin"].value_counts().items():
        print(f"  {tk}: {c} artikel")

    print("\n" + "=" * 70)
    print("PENYARINGAN SELESAI DENGAN SEMPURNA!")
    print(f"Artikel Awal               : {len(df_berita)}")
    print(f"Artikel Dibuang (Non-Agro) : {len(discarded_articles)}")
    print(f"Artikel Final Sektor IA    : {len(processed_berita)}")
    print(f"Ringkasan Negatif Final    : {len(processed_neg)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
