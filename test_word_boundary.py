"""
test_word_boundary.py
Unit test untuk membuktikan perbaikan bug substring matching:
1. 'gula' tidak lagi mencocokkan 'regulasi'
2. 'tar' tidak lagi mencocokkan 'pertanian'
3. 'air' tidak lagi mencocokkan 'keberlanjutan'
4. Exact match spokesperson tidak salah mencocokkan nama parsial
5. Deteksi is_recipe dan is_promotional
"""

from relevance_filter import (
    matches_word_boundary,
    is_likely_relevant,
    is_recipe,
    is_promotional,
    is_keyword_primary_topic,
    count_keyword_occurrences,
    is_industry_policy_topic,
)
from entity_mapper import find_spokespersons
from fetch_news import is_near_duplicate_title





def test_word_boundary_isolation():
    print("=== TEST 1: ISOLASI KATA DENGAN WORD BOUNDARY ===")

    # Kasus 1: gula vs regulasi
    assert not matches_word_boundary("gula", "pemerintah mengeluarkan regulasi baru"), "GAGAL: 'gula' mencocokkan 'regulasi'!"
    assert matches_word_boundary("gula", "pemerintah menetapkan harga acuan gula nasional"), "GAGAL: 'gula' gagal mencocokkan kata gula!"
    print("  [PASS] 'gula' TIDAK mencocokkan 'regulasi', dan berhasil mencocokkan 'gula nasional'")

    # Kasus 2: tar vs pertanian
    assert not matches_word_boundary("tar", "sektor pertanian indonesia tumbuh"), "GAGAL: 'tar' mencocokkan 'pertanian'!"
    assert matches_word_boundary("tar", "kandungan tar dan nikotin pada rokok"), "GAGAL: 'tar' gagal mencocokkan kata tar!"
    print("  [PASS] 'tar' TIDAK mencocokkan 'pertanian', dan berhasil mencocokkan 'tar dan nikotin'")

    # Kasus 3: air vs keberlanjutan
    assert not matches_word_boundary("air", "program industri keberlanjutan"), "GAGAL: 'air' mencocokkan 'keberlanjutan'!"
    assert matches_word_boundary("air", "industri air minum dalam kemasan"), "GAGAL: 'air' gagal mencocokkan kata air!"
    print("  [PASS] 'air' TIDAK mencocokkan 'keberlanjutan', dan berhasil mencocokkan 'air minum'")

    # Kasus 4: tebu vs menetebus / ditebus
    assert not matches_word_boundary("tebu", "surat berharga sudah ditebus oleh investor"), "GAGAL: 'tebu' mencocokkan 'ditebus'!"
    assert matches_word_boundary("tebu", "petani tebu mengirim hasil panen ke pabrik"), "GAGAL: 'tebu' gagal mencocokkan kata tebu!"
    print("  [PASS] 'tebu' TIDAK mencocokkan 'ditebus', dan berhasil mencocokkan 'petani tebu'")


def test_entity_mapper_word_boundary():
    print("\n=== TEST 2: WORD BOUNDARY PADA ENTITY MAPPER ===")
    mock_map = {
        "agus": "Menteri",
        "putu juli ardika": "Direktur Jenderal",
    }

    # Kata "bagus" tidak boleh memicu match exact untuk "agus"
    text_false = "kinerja keuangan pabrik gula ini sangat bagus sekali tahun ini."
    sp1, sp2, unit = find_spokespersons(text_false, mock_map, threshold=95)
    assert sp1 != "Agus", f"GAGAL: 'agus' mencocokkan kata 'bagus'! (hasil: {sp1})"
    print("  [PASS] Nama 'agus' TIDAK salah mencocokkan kata 'bagus'")

    # Nama utuh "Agus" harus match
    text_true = "kunjungan kerja bapak Agus ke pabrik gula madukismo."
    sp1, sp2, unit = find_spokespersons(text_true, mock_map, threshold=85)
    assert sp1 == "Agus", f"GAGAL: 'Agus' tidak terdeteksi! (hasil: {sp1})"
    print("  [PASS] Nama 'Agus' berhasil terdeteksi dengan tepat")


def test_recipe_and_promo_filters():
    print("\n=== TEST 3: DETEKSI RESEP DAN PROMOSI ===")

    # Resep
    recipe_title = "Resep Kue Putu Daun, Jajanan Jadul yang Lembut dan Wangi Pandan"
    recipe_snippet = "- 6 lembar daun pandan - 130 mililiter air - 250 gram tepung beras - 65 gram gula merah"
    assert is_recipe(recipe_title, recipe_snippet), "GAGAL: gagal mendeteksi resep kue putu!"
    print("  [PASS] Berhasil mendeteksi konten resep kue putu")

    # Promo
    promo_title = "Sinar Terang Supermarket Probolinggo - Dapatkan Gula Pasir 1 Kg"
    promo_snippet = "Periode promo 01 Sep - 31 Des. Dapatkan Gula Pasir 1 Kg. Syarat & Ketentuan: Minimum transaksi Rp500 ribu"
    assert is_promotional(promo_title, promo_snippet), "GAGAL: gagal mendeteksi promo supermarket!"
    print("  [PASS] Berhasil mendeteksi konten promo retail supermarket")

    # Berita Industri (harus False untuk resep & promo)
    news_title = "Serunya Naik Lori di Madukismo Bantul Sambil Melihat Produksi Gula"
    news_snippet = "Madukismo tidak hanya terkenal dengan pabrik gula (PG) dan pabrik spiritus (PS), ternyata memiliki agrowisata..."
    assert not is_recipe(news_title, news_snippet), "GAGAL: salah menandai berita industri sebagai resep!"
    assert not is_promotional(news_title, news_snippet), "GAGAL: salah menandai berita industri sebagai promo!"
    print("  [PASS] Berita industri Madukismo TIDAK tertandai sebagai resep maupun promo")


def test_is_keyword_primary_topic():
    print("\n=== TEST 4: FILTER FREKUENSI KEYWORD (PRIMARY TOPIC) ===")

    # Kasus 1: Keyword muncul di TITLE -> LOLOS
    t1 = "Serunya Naik Lori di Madukismo Sambil Melihat Pabrik Gula"
    c1 = "Madukismo adalah agrowisata berbasis industri tebu."
    assert is_keyword_primary_topic(t1, c1, "gula"), "GAGAL: keyword di title harusnya lolos!"
    print("  [PASS] Keyword muncul di title -> LOLOS")

    # Kasus 2: Keyword tidak di title, tapi muncul >= 2x di isi -> LOLOS
    t2 = "CISDI Mendorong Kebijakan Pembatasan Produk Minuman Manis Kemasan"
    c2 = "Konsumsi gula berlebih memicu diabetes. Produk ini tinggi gula dan tidak sehat."
    assert count_keyword_occurrences(c2, "gula") == 2
    assert is_keyword_primary_topic(t2, c2, "gula"), "GAGAL: keyword 2x di isi harusnya lolos!"
    print("  [PASS] Keyword muncul 2x di isi teks -> LOLOS")

    # Kasus 3: Keyword hanya muncul 1x di isi (hanya daftar sembako) & tidak di title -> DIBUANG
    t3 = "Pelayanan Homecare Puskesmas Jember Berikan Layanan untuk Lansia"
    c3 = "Bantuan diserahkan berupa sembako seperti beras, minyak, dan gula pasir satu bungkus."
    assert count_keyword_occurrences(c3, "gula") == 1
    assert not is_keyword_primary_topic(t3, c3, "gula"), "GAGAL: keyword cuma 1x di isi harusnya DIBUANG!"
    print("  [PASS] Keyword cuma muncul 1x di isi (daftar sembako) -> Berhasil DIBUANG")

    # Kasus 4: Keyword 0x di isi dan tidak di title -> DIBUANG
    t4 = "Dashboard Satu Data Perdagangan Kemendag RI"
    c4 = "Pemerintah mengatur sistem integrasi logistik nasional."
    assert not is_keyword_primary_topic(t4, c4, "gula"), "GAGAL: keyword 0x harusnya DIBUANG!"
    print("  [PASS] Keyword 0x di isi -> Berhasil DIBUANG")


def test_is_near_duplicate_title():
    print("\n=== TEST 5: DEDUPLIKASI KEMIRIPAN JUDUL (RAPIDFUZZ) ===")

    # Kasus Padang: Judul identik
    p1 = "Harga Gula Pasir Kristal Putih Kota Padang - Data Oleh Database Pasarami"
    p2 = "Harga Gula Pasir Kristal Putih Kota Padang - Data Oleh Database Pasarami"
    assert is_near_duplicate_title(p1, p2, threshold=85), "GAGAL: judul Padang identik harus terdeteksi duplikat!"
    print("  [PASS] Entri ganda Harga Gula Pasir Kota Padang terdeteksi sebagai duplikat")

    # Kasus Takaran Air Kelapa: Duplikat antar media
    k1 = "Jangan Kebanyakan! Ini Takaran Air Kelapa Tiap Harinya - Website Resmi Polri"
    k2 = "Jangan Kebanyakan! Ini Takaran Air Kelapa Tiap Harinya - Tribrata News"
    assert is_near_duplicate_title(k1, k2, threshold=85), "GAGAL: duplikat Takaran Air Kelapa harus terdeteksi!"
    print("  [PASS] Duplikat Takaran Air Kelapa (Polri vs Tribrata News) terdeteksi sebagai duplikat")

    # Kasus artikel berbeda: tidak boleh salah dideteksi sebagai duplikat
    d1 = "Program Bongkar Ratoon PG Ngadiredjo Kediri Naikkan Hasil Panen Tebu"
    d2 = "Gubernur Khofifah Tinjau PG Ngadirejo Kediri Milik PT SGN"
    assert not is_near_duplicate_title(d1, d2, threshold=85), "GAGAL: artikel beda salah dideteksi sebagai duplikat!"
    print("  [PASS] Dua artikel PG Ngadiredjo yang berbeda topik TIDAK dianggap duplikat")


def test_is_industry_policy_topic():
    print("\n=== TEST 6: FILTER TOPIK INDUSTRI/KEBIJAKAN VS KESEHATAN PERSONAL ===")

    # Kasus Industri/Kebijakan (ind_score > health_score) -> LOLOS
    t1 = "Kementerian Pertanian Targetkan Swasembada Gula Nasional dan Ekspor Gula"
    c1 = "Menteri Pertanian Amran Sulaiman meninjau pabrik gula dan perkebunan tebu rakyat untuk meningkatkan produksi dan investasi."
    assert is_industry_policy_topic(t1, c1), "GAGAL: berita industri swasembada harusnya LOLOS!"
    print("  [PASS] Berita industri/kebijakan (Kementan swasembada) -> LOLOS")

    # Kasus Kesehatan/Nutrisi Pribadi (health_score > ind_score) -> DIBUANG
    t2 = "Lima Khasiat Teh Hijau tanpa Gula untuk Detoksifikasi Tubuh"
    c2 = "Manfaat teh hijau sangat baik untuk diet, menurunkan kalori, mengatasi diabetes, dan menjaga pola makan serta asupan gizi harian."
    assert not is_industry_policy_topic(t2, c2), "GAGAL: artikel kesehatan/diet harusnya DIBUANG!"
    print("  [PASS] Artikel nutrisi/diet pribadi (khasiat teh hijau detoks) -> Berhasil DIBUANG")

    # Kasus Seri / Ambigu -> LOLOS by default
    t3 = "Informasi Umum Komoditas Pangan"
    c3 = "Keterangan umum terkait bahan baku pangan."
    assert is_industry_policy_topic(t3, c3), "GAGAL: kasus seri/ambigu harusnya LOLOS by default!"
    print("  [PASS] Kasus skor seri/ambigu -> LOLOS by default")


def test_clean_title_suffix():
    print("\n=== TEST 7: PEMBERSIHAN SUFFIX NAMA MEDIA DARI TITLE ===")
    from fetch_news import clean_title_suffix

    # Kasus standar: "Judul - Detikcom" dengan media "Detikcom"
    t1 = "Pemerintah Tingkatkan Produksi Gula Nasional - Detikcom"
    res1 = clean_title_suffix(t1, "Detikcom")
    assert res1 == "Pemerintah Tingkatkan Produksi Gula Nasional", f"GAGAL: {res1}"
    print("  [PASS] Suffix ' - Detikcom' berhasil dibersihkan dari judul")

    # Kasus nama media mengandung tanda strip (DINAS PERPUSTAKAAN DAN KEARSIPAN - Kabupaten Sidoarjo)
    t2 = "Pameran Dokumen Industri Gula Kuno - DINAS PERPUSTAKAAN DAN KEARSIPAN - Kabupaten Sidoarjo"
    media2 = "DINAS PERPUSTAKAAN DAN KEARSIPAN - Kabupaten Sidoarjo"
    res2 = clean_title_suffix(t2, media2)
    assert res2 == "Pameran Dokumen Industri Gula Kuno", f"GAGAL: {res2}"
    print("  [PASS] Media dengan tanda strip ('DINAS PERPUSTAKAAN DAN KEARSIPAN - Kabupaten Sidoarjo') tidak salah potong")

    # Kasus media None atau judul tidak berakhir dengan suffix nama media
    t3 = "Pabrik Gula Madukismo Beroperasi Normal"
    assert clean_title_suffix(t3, None) == t3
    assert clean_title_suffix(t3, "Antara News") == t3
    print("  [PASS] Judul tanpa suffix media tetap utuh")


def test_date_filter():
    print("\n=== TEST 8: FILTER TANGGAL HANYA KEMARIN ===")
    from config import get_date_range, is_published_yesterday
    from datetime import datetime, timedelta

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    s_yesterday = yesterday.strftime("%a, %d %b %Y 10:00:00 GMT")
    s_today = today.strftime("%a, %d %b %Y 10:00:00 GMT")
    s_two_days_ago = two_days_ago.strftime("%a, %d %b %Y 10:00:00 GMT")

    assert is_published_yesterday(s_yesterday), f"GAGAL: tanggal kemarin ({s_yesterday}) harus lolos!"
    assert not is_published_yesterday(s_today), f"GAGAL: tanggal hari ini ({s_today}) tidak boleh lolos!"
    assert not is_published_yesterday(s_two_days_ago), f"GAGAL: tanggal 2 hari lalu ({s_two_days_ago}) tidak boleh lolos!"
    print(f"  [PASS] Tanggal kemarin ({yesterday}) LOLOS, hari ini ({today}) DIBUANG, 2 hari lalu ({two_days_ago}) DIBUANG")


def test_is_kemenperin_related():
    print("\n=== TEST 9: FILTER INSTITUSI KEMENPERIN (EKSPLISIT & IMPLISIT) ===")
    from relevance_filter import is_kemenperin_related, get_kemenperin_signal

    sp_map = {
        "agus gumiwang": "Menteri Perindustrian",
        "putu juli ardika": "Direktur Jenderal Industri Agro",
        "merrijantij punguan": "Sekretaris Ditjen Industri Agro",
    }

    # Kasus 1: Sinyal Eksplisit (nama institusi langsung) -> True, EKSPLISIT
    t1 = "Pemerintah Tingkatkan Produksi Gula Nasional Melalui Hilirisasi"
    c1 = "Kemenperin terus mendorong hilirisasi komoditas tebu untuk mencapai kemandirian industri."
    is_rel1, sig_type1, sig_det1 = get_kemenperin_signal(t1, c1, sp_map)
    assert is_rel1 and sig_type1 == "EKSPLISIT" and sig_det1 == "kemenperin"
    assert is_kemenperin_related(t1, c1, sp_map)
    print("  [PASS] Sinyal EKSPLISIT ('kemenperin') berhasil terdeteksi")

    # Kasus 2: Sinyal Implisit (hanya sebut nama pejabat dari spokesperson_map, tanpa kata 'kemenperin') -> True, IMPLISIT
    t2 = "Strategi Peningkatan Rendemen Tebu di Jawa Timur"
    c2 = "Dalam kunjungan kerja ke pabrik gula, Putu Juli Ardika menyatakan pasokan tebu harus dijaga."
    is_rel2, sig_type2, sig_det2 = get_kemenperin_signal(t2, c2, sp_map)
    assert is_rel2 and sig_type2 == "IMPLISIT" and sig_det2 == "putu juli ardika"
    assert is_kemenperin_related(t2, c2, sp_map)
    print("  [PASS] Sinyal IMPLISIT (pejabat 'putu juli ardika') berhasil terdeteksi tanpa kata kemenperin")

    # Kasus 3: Berita instansi lain / tidak terkait -> False, NONE
    t3 = "Kemenkum Sultra Pantau Potensi Indikasi Geografis Gula Kelapa"
    c3 = "Kementerian Hukum Sulawesi Tenggara melakukan peninjauan lapangan di Pulau Kabaena."
    is_rel3, sig_type3, sig_det3 = get_kemenperin_signal(t3, c3, sp_map)
    assert not is_rel3 and sig_type3 == "NONE"
    assert not is_kemenperin_related(t3, c3, sp_map)
    print("  [PASS] Berita Kemenkum / instansi lain berhasil DIBUANG (bukan Kemenperin)")

    # Kasus 4: Word boundary protection (substring tidak boleh match) -> False
    t4 = "Pengumuman Semenperingatan Hari Kemerdekaan"
    c4 = "Peringatan hari kemerdekaan diadakan serentak."
    assert not is_kemenperin_related(t4, c4, sp_map)
    print("  [PASS] Word boundary protection mencegah substring 'semenperingatan' mencocokkan 'menperin'")


def test_kertas_context_filter():
    from relevance_filter import is_kertas_context_valid, is_keyword_primary_topic
    print("\n=== TEST 10: FILTER MAKNA GANDA KERTAS (KERTAS KERJA / DI ATAS KERTAS) ===")

    # 1. Kertas kerja dokumen/penilaian (DJKN) -> Harus False
    t1 = "Artikel Kanwil DJKN Jawa Barat"
    c1 = "Kertas kerja penilaian merupakan dokumen penting bagi penilai pemerintah. Kertas kerja ini memuat analisis."
    assert not is_kertas_context_valid(t1, c1)
    assert not is_keyword_primary_topic(t1, c1, "kertas")
    print("  [PASS] Dokumen 'kertas kerja' berhasil dibuang (bukan komoditas kertas)")

    # 2. Idiom 'di atas kertas' (Kompas/Suara) -> Harus False
    t2 = "Standar Keselamatan Jangan Cuma di Atas Kertas"
    c2 = "Pemerintah harus memastikan implementasi lapangan tidak hanya di atas kertas."
    assert not is_kertas_context_valid(t2, c2)
    assert not is_keyword_primary_topic(t2, c2, "kertas")
    print("  [PASS] Idiom 'di atas kertas' berhasil dibuang")

    # 3. Industri/komoditas kertas asli -> Harus True
    t3 = "Pabrik Kertas Tjiwi Kimia Perluas Pangsa Ekspor"
    c3 = "Produksi kertas dan bahan baku kertas terus ditingkatkan untuk memenuhi permintaan pasar global."
    assert is_kertas_context_valid(t3, c3)
    assert is_keyword_primary_topic(t3, c3, "kertas")
    print("  [PASS] Berita industri komoditas kertas asli berhasil LOLOS")


if __name__ == "__main__":
    test_word_boundary_isolation()
    test_entity_mapper_word_boundary()
    test_recipe_and_promo_filters()
    test_is_keyword_primary_topic()
    test_is_near_duplicate_title()
    test_is_industry_policy_topic()
    test_clean_title_suffix()
    test_date_filter()
    test_is_kemenperin_related()
    test_kertas_context_filter()
    print("\n" + "=" * 50)
    print("SEMUA UNIT TEST BERHASIL LULUS 100%!")
    print("=" * 50)




