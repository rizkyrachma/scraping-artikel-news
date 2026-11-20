"""
scripts/apply_excel_sync_fix.py
Skrip terkontrol untuk menerapkan regenerasi data dari sandbox/ ke data_export/ dan web/public/.
DILINDUNGI: Memerlukan konfirmasi eksplisit --confirm "PERBAIKAN DATA DISETUJUI".
"""

import argparse
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SANDBOX_DIR = BASE_DIR / "scratch" / "sandbox_data_export"
DATA_EXPORT_DIR = BASE_DIR / "data_export"
FILES_EXPORT_DIR = DATA_EXPORT_DIR / "files"
WEB_DATA_DIR = BASE_DIR / "web" / "public" / "data"
WEB_FILES_DIR = BASE_DIR / "web" / "public" / "files"

EXPECTED_CONFIRMATION = "PERBAIKAN DATA DISETUJUI"


def run_cmd(cmd: list[str]) -> tuple[int, str]:
    res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    return res.returncode, res.stdout + res.stderr


def apply_fix(confirm_text: str):
    if confirm_text.strip() != EXPECTED_CONFIRMATION:
        print("=" * 80)
        print("PERINGATAN: Penerapan data ke produksi DITOLAK.")
        print(f"Argumen --confirm harus persis '{EXPECTED_CONFIRMATION}'.")
        print("Tidak ada file produksi yang diubah.")
        print("=" * 80)
        sys.exit(1)

    print("=" * 80)
    print("MEMULAI PENERAPAN PERBAIKAN DATA DARI SANDBOX KE PRODUKSI")
    print("=" * 80)

    # 1. Pastikan berkas sandbox lengkap
    sb_articles = SANDBOX_DIR / "articles_all.json"
    sb_summary = SANDBOX_DIR / "summary.json"
    sb_semua = SANDBOX_DIR / "files" / "Media_Monitoring_Agro_Semua_Data.xlsx"

    if not sb_articles.exists() or not sb_summary.exists() or not sb_semua.exists():
        print("[Error] Berkas sandbox tidak lengkap di", SANDBOX_DIR)
        sys.exit(1)

    # 2. Verifikasi sandbox dengan verify_dashboard_vs_excel.py
    code, out = run_cmd([
        sys.executable,
        "scripts/verify_dashboard_vs_excel.py",
        "--data-dir", str(SANDBOX_DIR),
        "--files-dir", str(SANDBOX_DIR / "files"),
    ])
    if code != 0:
        print("[Error] Verifikasi data sandbox gagal (selisih belum 0):")
        print(out)
        sys.exit(1)
    print("[1/5] Verifikasi sandbox lolos: 0 selisih.")

    # 3. Buat tag backup Git baru sebelum penimpaan
    now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_tag = f"backup-sebelum-excel-sync-{now_str}"
    code_tag, out_tag = run_cmd(["git", "tag", backup_tag])
    if code_tag == 0:
        print(f"[2/5] Git backup tag berhasil dibuat: {backup_tag}")
    else:
        print(f"[2/5] Catatan tag: {out_tag.strip()}")

    # 4. Tampilkan catatan jeda workflow
    print("[3/5] Langkah jeda workflow (bila diperlukan saat proses live):")
    print("      gh workflow disable daily_scrape.yml")

    # 5. Salin berkas dari sandbox ke produksi
    shutil.copy2(sb_articles, DATA_EXPORT_DIR / "articles_all.json")
    shutil.copy2(sb_summary, DATA_EXPORT_DIR / "summary.json")
    shutil.copy2(sb_semua, FILES_EXPORT_DIR / "Media_Monitoring_Agro_Semua_Data.xlsx")

    if WEB_DATA_DIR.exists():
        shutil.copy2(sb_articles, WEB_DATA_DIR / "articles_all.json")
        shutil.copy2(sb_summary, WEB_DATA_DIR / "summary.json")
    if WEB_FILES_DIR.exists():
        shutil.copy2(sb_semua, WEB_FILES_DIR / "Media_Monitoring_Agro_Semua_Data.xlsx")
    print("[4/5] Berkas articles_all.json, summary.json, dan Semua_Data.xlsx berhasil disalin ke produksi.")

    # 6. Verifikasi ulang berkas produksi
    code_prod, out_prod = run_cmd([
        sys.executable,
        "scripts/verify_dashboard_vs_excel.py",
        "--data-dir", str(DATA_EXPORT_DIR),
        "--files-dir", str(FILES_EXPORT_DIR),
    ])
    if code_prod != 0:
        print("[Peringatan] Verifikasi berkas produksi menemukan selisih:")
        print(out_prod)
    else:
        print("[5/5] Verifikasi data produksi 100% lolos (0 selisih).")

    print("=" * 80)
    print("LANGKAH LANJUTAN:")
    print("1. Komit perubahan tanpa force push:")
    print("   git add data_export/ web/public/data/ web/public/files/")
    print("   git commit -m \"chore(data): sinkronisasi data dashboard sesuai Excel harian 1:1\"")
    print("2. Aktifkan kembali workflow:")
    print("   gh workflow enable daily_scrape.yml")
    print("3. Perintah rollback jika diperlukan:")
    print(f"   git checkout {backup_tag} -- data_export web/public/data web/public/files")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Terapkan perbaikan data dashboard dari sandbox ke produksi")
    parser.add_argument("--confirm", type=str, default="", help=f"Harus diisi '{EXPECTED_CONFIRMATION}'")
    args = parser.parse_args()
    apply_fix(args.confirm)
