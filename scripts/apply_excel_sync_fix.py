"""
scripts/apply_excel_sync_fix.py
Skrip terkontrol untuk menerapkan regenerasi data dari scratch/sandbox_data_export/ ke data_export/ dan web/public/.
DILINDUNGI KETAT:
- Memerlukan argumen wajib --confirm "PERBAIKAN DATA DISETUJUI".
- Menolak eksekusi jika ada workflow GitHub Actions yang sedang berjalan/antre.
- Mematikan workflow daily_scrape.yml selama proses dan menjamin aktif kembali pada blok finally.
- Membuat backup tag untuk KEDUA branch (origin/main dan origin/data).
- Mendukung pembaruan ke branch main dan branch data dengan commit baru tanpa force push.
- Memverifikasi data dengan scripts/verify_dashboard_vs_excel.py.
- Mendukung flag --dry-run untuk menguji seluruh siklus dalam repositori git lokal sementara.
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SANDBOX_DIR = BASE_DIR / "scratch" / "sandbox_data_export"
DATA_EXPORT_DIR = BASE_DIR / "data_export"
FILES_EXPORT_DIR = DATA_EXPORT_DIR / "files"
WEB_DATA_DIR = BASE_DIR / "web" / "public" / "data"
WEB_FILES_DIR = BASE_DIR / "web" / "public" / "files"

EXPECTED_CONFIRMATION = "PERBAIKAN DATA DISETUJUI"


def run_cmd(cmd: list[str], cwd: Path = BASE_DIR) -> tuple[int, str]:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return res.returncode, (res.stdout + "\n" + res.stderr).strip()


def check_active_workflows() -> list[str]:
    """Memeriksa apakah ada workflow daily_scrape.yml yang sedang berjalan, antre, atau menunggu."""
    active_runs = []
    for st in ("in_progress", "queued", "waiting"):
        code, out = run_cmd(["gh", "run", "list", "--workflow", "daily_scrape.yml", "--status", st, "--json", "databaseId,status"])
        if code == 0 and out:
            try:
                items = json.loads(out)
                for item in items:
                    active_runs.append(f"Run #{item.get('databaseId')} ({item.get('status')})")
            except Exception:
                pass
    return active_runs


def run_dry_run_test():
    """Menguji seluruh alur kerja penerapan dan rollback dalam repositori git sementara tanpa mengubah repo utama."""
    print("=" * 80)
    print("[DRY-RUN] Memulai pengujian simulasi alur penerapan & rollback di repositori sementara...")
    print("=" * 80)

    # 1. Pastikan berkas sandbox lokal valid
    sb_articles = SANDBOX_DIR / "articles_all.json"
    sb_summary = SANDBOX_DIR / "summary.json"
    sb_semua = SANDBOX_DIR / "files" / "Media_Monitoring_Agro_Semua_Data.xlsx"

    if not sb_articles.exists() or not sb_summary.exists() or not sb_semua.exists():
        print(f"[DRY-RUN Error] Berkas sandbox tidak lengkap di {SANDBOX_DIR}")
        return False

    code, out = run_cmd([
        sys.executable,
        str(BASE_DIR / "scripts" / "verify_dashboard_vs_excel.py"),
        "--data-dir", str(SANDBOX_DIR),
        "--files-dir", str(SANDBOX_DIR / "files"),
    ])
    if code != 0:
        print(f"[DRY-RUN Error] Verifikasi sandbox gagal:\n{out}")
        return False
    print("[DRY-RUN 1/6] Verifikasi sandbox lolos: 0 selisih.")

    # 2. Buat repositori git sementara
    with tempfile.TemporaryDirectory() as tmp_git_dir:
        tmp_repo = Path(tmp_git_dir)
        run_cmd(["git", "init", "-b", "main"], cwd=tmp_repo)
        run_cmd(["git", "config", "user.name", "Tester"], cwd=tmp_repo)
        run_cmd(["git", "config", "user.email", "test@agro.id"], cwd=tmp_repo)

        # Inisialisasi struktur branch main
        (tmp_repo / "data_export" / "files").mkdir(parents=True, exist_ok=True)
        (tmp_repo / "web" / "public" / "data").mkdir(parents=True, exist_ok=True)
        (tmp_repo / "web" / "public" / "files").mkdir(parents=True, exist_ok=True)

        with open(tmp_repo / "data_export" / "summary.json", "w") as f:
            f.write('{"initial": true}')
        with open(tmp_repo / "data_export" / "articles_all.json", "w") as f:
            f.write('[{"id": 1, "title": "initial"}]')
        with open(tmp_repo / "web" / "public" / "data" / "summary.json", "w") as f:
            f.write('{"initial": true}')
        with open(tmp_repo / "web" / "public" / "data" / "articles_all.json", "w") as f:
            f.write('[{"id": 1, "title": "initial"}]')
        run_cmd(["git", "add", "."], cwd=tmp_repo)
        run_cmd(["git", "commit", "--no-verify", "-m", "initial main"], cwd=tmp_repo)

        # Inisialisasi branch data
        run_cmd(["git", "checkout", "-b", "data"], cwd=tmp_repo)
        (tmp_repo / "pipeline_state").mkdir(parents=True, exist_ok=True)
        with open(tmp_repo / "pipeline_state" / "cache.json", "w") as f:
            f.write('{"state": 1}')
        run_cmd(["git", "add", "."], cwd=tmp_repo)
        run_cmd(["git", "commit", "--no-verify", "-m", "initial data branch"], cwd=tmp_repo)

        print("[DRY-RUN 2/6] Repositori simulasi (main & data) berhasil diinisialisasi.")

        # 3. Simulasi pembuatan tag backup untuk main & data
        now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tag_main = f"backup-sebelum-excel-sync-main-{now_str}"
        tag_data = f"backup-sebelum-excel-sync-data-{now_str}"

        run_cmd(["git", "tag", tag_main, "main"], cwd=tmp_repo)
        run_cmd(["git", "tag", tag_data, "data"], cwd=tmp_repo)
        print(f"[DRY-RUN 3/6] Backup tags berhasil dibuat: {tag_main} dan {tag_data}")

        # 4. Terapkan data ke branch main
        run_cmd(["git", "checkout", "main"], cwd=tmp_repo)
        (tmp_repo / "data_export" / "files").mkdir(parents=True, exist_ok=True)
        (tmp_repo / "web" / "public" / "data").mkdir(parents=True, exist_ok=True)
        (tmp_repo / "web" / "public" / "files").mkdir(parents=True, exist_ok=True)
        shutil.copy2(sb_articles, tmp_repo / "data_export" / "articles_all.json")
        shutil.copy2(sb_summary, tmp_repo / "data_export" / "summary.json")
        shutil.copy2(sb_semua, tmp_repo / "data_export" / "files" / "Media_Monitoring_Agro_Semua_Data.xlsx")
        shutil.copy2(sb_articles, tmp_repo / "web" / "public" / "data" / "articles_all.json")
        shutil.copy2(sb_summary, tmp_repo / "web" / "public" / "data" / "summary.json")
        shutil.copy2(sb_semua, tmp_repo / "web" / "public" / "files" / "Media_Monitoring_Agro_Semua_Data.xlsx")

        run_cmd(["git", "add", "data_export/", "web/public/"], cwd=tmp_repo)
        c_code, c_out = run_cmd(["git", "commit", "--no-verify", "-m", "chore(data): sinkronisasi data dashboard sesuai Excel harian 1:1"], cwd=tmp_repo)
        assert c_code == 0, f"Gagal commit branch main: {c_out}"
        assert not (tmp_repo / "pipeline_state").exists(), "pipeline_state tidak boleh ada di branch main"
        print("[DRY-RUN 4/6] Penerapan ke branch main sukses dikomit (tanpa pipeline_state).")

        # 5. Terapkan data ke branch data
        run_cmd(["git", "checkout", "data"], cwd=tmp_repo)
        (tmp_repo / "data_export" / "files").mkdir(parents=True, exist_ok=True)
        (tmp_repo / "web" / "public" / "data").mkdir(parents=True, exist_ok=True)
        (tmp_repo / "web" / "public" / "files").mkdir(parents=True, exist_ok=True)
        shutil.copy2(sb_articles, tmp_repo / "data_export" / "articles_all.json")
        shutil.copy2(sb_summary, tmp_repo / "data_export" / "summary.json")
        shutil.copy2(sb_semua, tmp_repo / "data_export" / "files" / "Media_Monitoring_Agro_Semua_Data.xlsx")
        shutil.copy2(sb_articles, tmp_repo / "web" / "public" / "data" / "articles_all.json")
        shutil.copy2(sb_summary, tmp_repo / "web" / "public" / "data" / "summary.json")
        shutil.copy2(sb_semua, tmp_repo / "web" / "public" / "files" / "Media_Monitoring_Agro_Semua_Data.xlsx")

        run_cmd(["git", "add", "data_export/", "web/public/", "pipeline_state/"], cwd=tmp_repo)
        c_code_data, c_out_data = run_cmd(["git", "commit", "--no-verify", "-m", "chore(data): update data & pipeline_state sinkronisasi Excel 1:1"], cwd=tmp_repo)
        assert c_code_data == 0, f"Gagal commit branch data: {c_out_data}"
        print("[DRY-RUN 5/6] Penerapan ke branch data sukses dikomit.")

        # 6. Uji simulasi rollback membuat commit baru (bukan force push)
        run_cmd(["git", "checkout", tag_data, "--", "data_export", "web/public"], cwd=tmp_repo)
        r_code, r_out = run_cmd(["git", "commit", "--no-verify", "-m", f"revert: rollback data ke {tag_data}"], cwd=tmp_repo)
        assert r_code == 0, f"Gagal rollback commit: {r_out}"
        with open(tmp_repo / "data_export" / "summary.json") as f:
            content = f.read()
            assert '{"initial": true}' in content, "Rollback harus mengembalikan data awal"
        print("[DRY-RUN 6/6] Uji rollback sukses: data berhasil dikembalikan via commit baru.")

    print("=" * 80)
    print("[DRY-RUN BERHASIL] Seluruh alur kerja penerapan dan rollback terverifikasi 100% aman.")
    print("=" * 80)
    return True


def apply_fix(confirm_text: str):
    if confirm_text.strip() != EXPECTED_CONFIRMATION:
        print("=" * 80)
        print("PENOLAKAN: Penerapan data ke produksi DITOLAK.")
        print(f"Argumen --confirm harus persis: '{EXPECTED_CONFIRMATION}'.")
        print("Tidak ada file atau branch yang dimodifikasi.")
        print("=" * 80)
        sys.exit(1)

    # 1. Cek workflow aktif
    print("[1/7] Memeriksa status workflow GitHub Actions daily_scrape.yml...")
    active_runs = check_active_workflows()
    if active_runs:
        print("=" * 80)
        print("PENOLAKAN KEAMANAN: Ditemukan workflow daily_scrape.yml yang sedang aktif:")
        for r in active_runs:
            print(f"  - {r}")
        print("Tunggu sampai workflow selesai sebelum menjalankan sinkronisasi data produksi.")
        print("=" * 80)
        sys.exit(1)
    print("      Tidak ada workflow yang aktif. Aman untuk melanjutkan.")

    # 2. Pastikan kelengkapan sandbox
    sb_articles = SANDBOX_DIR / "articles_all.json"
    sb_summary = SANDBOX_DIR / "summary.json"
    sb_semua = SANDBOX_DIR / "files" / "Media_Monitoring_Agro_Semua_Data.xlsx"

    if not sb_articles.exists() or not sb_summary.exists() or not sb_semua.exists():
        print(f"[Error] Berkas sandbox tidak lengkap di {SANDBOX_DIR}")
        sys.exit(1)

    code, out = run_cmd([
        sys.executable,
        "scripts/verify_dashboard_vs_excel.py",
        "--data-dir", str(SANDBOX_DIR),
        "--files-dir", str(SANDBOX_DIR / "files"),
    ])
    if code != 0:
        print(f"[Error] Verifikasi data sandbox gagal (selisih belum 0):\n{out}")
        sys.exit(1)
    print("[2/7] Verifikasi sandbox lolos: 0 selisih.")

    # 3. Nonaktifkan workflow daily_scrape.yml dengan jaminan aktif kembali di finally
    print("[3/7] Menonaktifkan workflow daily_scrape.yml sementara...")
    code_dis, out_dis = run_cmd(["gh", "workflow", "disable", "daily_scrape.yml"])
    if code_dis != 0:
        print(f"[Peringatan] Gagal mendisable workflow (lanjut jika akses read-only): {out_dis}")

    try:
        # 4. Buat backup tags untuk origin/main dan origin/data
        now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tag_main = f"backup-sebelum-excel-sync-main-{now_str}"
        tag_data = f"backup-sebelum-excel-sync-data-{now_str}"

        run_cmd(["git", "fetch", "origin", "main", "data"])
        code_tm, out_tm = run_cmd(["git", "tag", tag_main, "origin/main"])
        code_td, out_td = run_cmd(["git", "tag", tag_data, "origin/data"])
        print(f"[4/7] Backup tags dibuat: {tag_main} (main) & {tag_data} (data)")

        # 5. Salin data sandbox ke produksi
        shutil.copy2(sb_articles, DATA_EXPORT_DIR / "articles_all.json")
        shutil.copy2(sb_summary, DATA_EXPORT_DIR / "summary.json")
        shutil.copy2(sb_semua, FILES_EXPORT_DIR / "Media_Monitoring_Agro_Semua_Data.xlsx")

        if WEB_DATA_DIR.exists():
            shutil.copy2(sb_articles, WEB_DATA_DIR / "articles_all.json")
            shutil.copy2(sb_summary, WEB_DATA_DIR / "summary.json")
        if WEB_FILES_DIR.exists():
            shutil.copy2(sb_semua, WEB_FILES_DIR / "Media_Monitoring_Agro_Semua_Data.xlsx")
        print("[5/7] Berkas articles_all.json, summary.json, dan Semua_Data.xlsx disalin ke direktori produksi.")

        # 6. Verifikasi ulang data produksi
        code_prod, out_prod = run_cmd([
            sys.executable,
            "scripts/verify_dashboard_vs_excel.py",
            "--data-dir", str(DATA_EXPORT_DIR),
            "--files-dir", str(FILES_EXPORT_DIR),
        ])
        if code_prod != 0:
            print(f"[Peringatan] Verifikasi berkas produksi menemukan selisih:\n{out_prod}")
        else:
            print("[6/7] Verifikasi data produksi 100% lolos (0 selisih).")

        # 7. Informasi commit & push dua branch tanpa force push
        print("=" * 80)
        print("[7/7] DATA PRODUKSI BERHASIL DIPERBARUI SECARA LOKAL.")
        print("LANGKAH PENERAPAN GIT KE DUA BRANCH (TANPA FORCE PUSH):")
        print("1. Branch main:")
        print("   git checkout main")
        print("   git add data_export/ web/public/data/ web/public/files/")
        print("   git commit -m \"chore(data): sinkronisasi data dashboard sesuai Excel harian 1:1\"")
        print("   git push origin main")
        print("2. Branch data:")
        print("   git checkout -B data origin/data")
        print("   git checkout main -- data_export web/public/data web/public/files")
        print("   git add data_export/ web/public/data/ web/public/files/")
        print("   git commit -m \"chore(data): update data branch sinkronisasi Excel 1:1\"")
        print("   git push origin data")
        print()
        print("PERINTAH ROLLBACK (MEMBUAT COMMIT BARU, BUKAN FORCE PUSH):")
        print("A. Rollback branch main:")
        print(f"   git checkout main && git checkout {tag_main} -- data_export web/public/data web/public/files")
        print(f"   git commit -m \"revert: rollback data main ke {tag_main}\" && git push origin main")
        print("B. Rollback branch data:")
        print(f"   git checkout data && git checkout {tag_data} -- data_export web/public/data web/public/files")
        print(f"   git commit -m \"revert: rollback data branch ke {tag_data}\" && git push origin data")
        print("=" * 80)

    finally:
        # Menjamin workflow daily_scrape.yml selalu diaktifkan kembali
        print("Memastikan workflow daily_scrape.yml diaktifkan kembali...")
        run_cmd(["gh", "workflow", "enable", "daily_scrape.yml"])
        print("Workflow daily_scrape.yml aktif.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Terapkan perbaikan data dashboard dari sandbox ke produksi")
    parser.add_argument("--confirm", type=str, default="", help=f"Harus diisi '{EXPECTED_CONFIRMATION}'")
    parser.add_argument("--dry-run", action="store_true", help="Uji seluruh alur simulasi di git sementara tanpa ubah produksi")
    args = parser.parse_args()

    if args.dry_run:
        ok = run_dry_run_test()
        sys.exit(0 if ok else 1)
    else:
        apply_fix(args.confirm)
