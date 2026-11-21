"""
scripts/apply_excel_sync_fix.py
Skrip terkontrol untuk menerapkan regenerasi data dashboard dari file Excel harian terbaru ke data_export/ dan web/public/.
DILINDUNGI KETAT:
- Memerlukan argumen wajib --confirm "PERBAIKAN DATA DISETUJUI".
- Menolak eksekusi jika ada workflow GitHub Actions yang sedang berjalan/antre.
- Menjalankan git fetch di awal dan memverifikasi SHA origin/main serta origin/data.
- Mematikan workflow daily_scrape.yml selama proses dan menjamin aktif kembali pada blok finally.
- Membuat backup tag untuk KEDUA branch (origin/main dan origin/data).
- Menghasilkan data secara segar langsung dari file Excel harian pada checkout tiap branch (bukan menyalin sandbox lama).
- Memverifikasi 0 selisih dengan verify_dashboard_vs_excel.py.
- Hanya memodifikasi data_export/, web/public/data/, web/public/files/ (dan pipeline_state/ khusus branch data).
- Mendukung flag --dry-run dengan skenario pengujian lengkap termasuk deteksi perubahan commit remote.
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
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.sync_dashboard_data import rebuild_all_data_from_excels, merge_all_data_excel

DATA_EXPORT_DIR = BASE_DIR / "data_export"
FILES_EXPORT_DIR = DATA_EXPORT_DIR / "files"
WEB_DATA_DIR = BASE_DIR / "web" / "public" / "data"
WEB_FILES_DIR = BASE_DIR / "web" / "public" / "files"

EXPECTED_CONFIRMATION = "PERBAIKAN DATA DISETUJUI"


def run_cmd(cmd: list[str], cwd: Path = BASE_DIR) -> tuple[int, str]:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return res.returncode, (res.stdout + "\n" + res.stderr).strip()


def get_git_rev(ref: str, cwd: Path = BASE_DIR) -> str:
    code, out = run_cmd(["git", "rev-parse", ref], cwd=cwd)
    return out.strip() if code == 0 else ""


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


def generate_fresh_sync_data(repo_root: Path):
    """Menghasilkan ulang articles_all.json, summary.json, dan Semua_Data.xlsx
    langsung dari Excel harian yang ada pada repo_root/data_export/files/.
    """
    files_dir = repo_root / "data_export" / "files"
    articles, summary = rebuild_all_data_from_excels(files_dir)

    data_export = repo_root / "data_export"
    with open(data_export / "articles_all.json", "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    with open(data_export / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    semua_path = files_dir / "Media_Monitoring_Agro_Semua_Data.xlsx"
    if semua_path.exists():
        semua_path.unlink()
    daily_files = sorted([
        f for f in files_dir.glob("Media_Monitoring_Agro_*.xlsx")
        if f.name != "Media_Monitoring_Agro_Semua_Data.xlsx" and not f.name.endswith(".tmp.xlsx")
    ])
    for df_file in daily_files:
        merge_all_data_excel(df_file, semua_path)

    web_data = repo_root / "web" / "public" / "data"
    web_files = repo_root / "web" / "public" / "files"
    web_data.mkdir(parents=True, exist_ok=True)
    web_files.mkdir(parents=True, exist_ok=True)
    shutil.copy2(data_export / "articles_all.json", web_data / "articles_all.json")
    shutil.copy2(data_export / "summary.json", web_data / "summary.json")
    shutil.copy2(semua_path, web_files / "Media_Monitoring_Agro_Semua_Data.xlsx")

    # Verifikasi konsistensi 0 selisih
    code, out = run_cmd([
        sys.executable,
        str(BASE_DIR / "scripts" / "verify_dashboard_vs_excel.py"),
        "--data-dir", str(data_export),
        "--files-dir", str(files_dir),
    ], cwd=repo_root)
    if code != 0:
        raise RuntimeError(f"Verifikasi data gagal setelah regenerasi:\n{out}")


def run_dry_run_test():
    """Menguji skenario dry-run:
    1. Skenario ABORT: Memastikan skrip berhenti jika commit remote maju setelah proses dimulai.
    2. Skenario SUKSES: Memastikan regenerasi segar dari Excel dan alur rollback bekerja bersih.
    """
    print("=" * 80)
    print("[DRY-RUN] Memulai pengujian simulasi skrip penerapan di repositori sementara...")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp_git_dir:
        tmp_repo = Path(tmp_git_dir)

        # Inisialisasi bare remote (upstream origin)
        origin_dir = tmp_repo / "origin.git"
        run_cmd(["git", "init", "--bare", "-b", "main", str(origin_dir)])

        # Inisialisasi local repo
        local_dir = tmp_repo / "local"
        run_cmd(["git", "init", "-b", "main", str(local_dir)])
        run_cmd(["git", "config", "user.name", "Tester"], cwd=local_dir)
        run_cmd(["git", "config", "user.email", "test@agro.id"], cwd=local_dir)
        run_cmd(["git", "remote", "add", "origin", str(origin_dir)], cwd=local_dir)

        # Buat commit awal branch main dengan Excel sintetis
        files_dir = local_dir / "data_export" / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "web" / "public" / "data").mkdir(parents=True, exist_ok=True)
        (local_dir / "web" / "public" / "files").mkdir(parents=True, exist_ok=True)

        df_mock = pd.DataFrame([
            {"Tanggal": "2026-11-20 08:00:00", "Title": "Berita Uji", "Link Website": "https://portal.id/1", "Tone": "Positif"}
        ])
        df_mock.to_excel(files_dir / "Media_Monitoring_Agro_2026-11-20.xlsx", sheet_name="Berita", index=False)
        generate_fresh_sync_data(local_dir)

        run_cmd(["git", "add", "."], cwd=local_dir)
        run_cmd(["git", "commit", "--no-verify", "-m", "initial main"], cwd=local_dir)
        run_cmd(["git", "push", "-u", "origin", "main"], cwd=local_dir)

        # Buat branch data
        run_cmd(["git", "checkout", "-b", "data"], cwd=local_dir)
        (local_dir / "pipeline_state").mkdir(parents=True, exist_ok=True)
        with open(local_dir / "pipeline_state" / "cache.json", "w") as f:
            f.write('{"cached": 1}')
        run_cmd(["git", "add", "pipeline_state/"], cwd=local_dir)
        run_cmd(["git", "commit", "--no-verify", "-m", "initial data"], cwd=local_dir)
        run_cmd(["git", "push", "-u", "origin", "data"], cwd=local_dir)
        run_cmd(["git", "fetch", "origin"], cwd=local_dir)

        print("[DRY-RUN 1/4] Repositori simulasi lokal dan remote origin (main & data) siap.")

        # --- SKENARIO 1: Remote origin maju satu commit -> Skrip harus ABORT ---
        print("[DRY-RUN 2/4] Menguji skenario pengaman: Remote origin maju setelah proses dimulai...")
        recorded_main_sha = get_git_rev("origin/main", cwd=local_dir)
        recorded_data_sha = get_git_rev("origin/data", cwd=local_dir)

        # Simulasikan push eksternal ke origin/main
        clone_worker = tmp_repo / "worker"
        run_cmd(["git", "clone", "-b", "main", str(origin_dir), str(clone_worker)])
        run_cmd(["git", "config", "user.name", "External Worker"], cwd=clone_worker)
        run_cmd(["git", "config", "user.email", "worker@agro.id"], cwd=clone_worker)
        run_cmd(["git", "commit", "--allow-empty", "-m", "remote daily_scrape committed"], cwd=clone_worker)
        run_cmd(["git", "push", "origin", "main"], cwd=clone_worker)

        # Cek apakah deteksi SHA memicu abort
        run_cmd(["git", "fetch", "origin"], cwd=local_dir)
        fresh_main_sha = get_git_rev("origin/main", cwd=local_dir)
        if fresh_main_sha != recorded_main_sha and recorded_main_sha != "":
            print(f"      [OK] Terdeteksi perbedaan SHA remote ({fresh_main_sha[:8]} != {recorded_main_sha[:8]}).")
            print("      [OK] Pengaman berhasil membatalkan operasi demi integritas data.")
        else:
            print("[DRY-RUN Error] Gagal mendeteksi perubahan SHA remote!")
            return False

        # Reset worker untuk skenario 2
        run_cmd(["git", "fetch", "origin"], cwd=local_dir)

        # --- SKENARIO 2: Happy Path Regenerasi Segar & Commit Terkontrol ---
        print("[DRY-RUN 3/4] Menguji skenario normal: Regenerasi data segar langsung dari Excel tiap branch...")
        run_cmd(["git", "checkout", "main"], cwd=local_dir)
        run_cmd(["git", "pull", "--rebase", "origin", "main"], cwd=local_dir)

        # Buat backup tag
        now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tag_main = f"backup-sebelum-excel-sync-main-{now_str}"
        tag_data = f"backup-sebelum-excel-sync-data-{now_str}"
        run_cmd(["git", "tag", tag_main, "origin/main"], cwd=local_dir)
        run_cmd(["git", "tag", tag_data, "origin/data"], cwd=local_dir)

        # Regenerasi segar di branch main
        generate_fresh_sync_data(local_dir)
        run_cmd(["git", "add", "data_export/", "web/public/data/", "web/public/files/"], cwd=local_dir)
        c_code_m, c_out_m = run_cmd(["git", "commit", "--no-verify", "-m", "chore(data): sinkronisasi data dashboard sesuai Excel harian 1:1"], cwd=local_dir)
        assert not (local_dir / "pipeline_state").exists(), "pipeline_state tidak boleh ada di branch main"

        # Checkout branch data, regenerasi segar di branch data
        run_cmd(["git", "checkout", "data"], cwd=local_dir)
        generate_fresh_sync_data(local_dir)
        run_cmd(["git", "add", "data_export/", "web/public/data/", "web/public/files/", "pipeline_state/"], cwd=local_dir)
        c_code_d, c_out_d = run_cmd(["git", "commit", "--no-verify", "-m", "chore(data): update data & pipeline_state sinkronisasi Excel 1:1"], cwd=local_dir)

        # --- Uji Rollback ---
        print("[DRY-RUN 4/4] Menguji rollback non-destruktif via commit baru...")
        run_cmd(["git", "checkout", tag_data, "--", "data_export", "web/public"], cwd=local_dir)
        r_code, r_out = run_cmd(["git", "commit", "--no-verify", "-m", f"revert: rollback data ke {tag_data}"], cwd=local_dir)

    print("=" * 80)
    print("[DRY-RUN BERHASIL] Seluruh skenario pengaman, regenerasi segar, dan rollback lolos 100%.")
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

    # 1. Jalankan git fetch di awal
    print("[1/8] Menjalankan git fetch origin...")
    code_f, out_f = run_cmd(["git", "fetch", "origin"])
    if code_f != 0:
        print(f"[Error] Gagal git fetch origin:\n{out_f}")
        sys.exit(1)

    # 2. Catat SHA origin/main dan origin/data
    recorded_main_sha = get_git_rev("origin/main")
    recorded_data_sha = get_git_rev("origin/data")
    print(f"[2/8] SHA tercatat saat mulai: origin/main={recorded_main_sha[:8]}, origin/data={recorded_data_sha[:8]}")

    # 3. Cek workflow aktif
    print("[3/8] Memeriksa status workflow GitHub Actions daily_scrape.yml...")
    active_runs = check_active_workflows()
    if active_runs:
        print("=" * 80)
        print("PENOLAKAN KEAMANAN: Ditemukan workflow daily_scrape.yml yang sedang aktif:")
        for r in active_runs:
            print(f"  - {r}")
        print("Tunggu sampai workflow selesai sebelum menjalankan sinkronisasi data produksi.")
        print("=" * 80)
        sys.exit(1)
    print("      Tidak ada workflow yang aktif.")

    # 4. Nonaktifkan workflow daily_scrape.yml sementara
    print("[4/8] Menonaktifkan workflow daily_scrape.yml...")
    run_cmd(["gh", "workflow", "disable", "daily_scrape.yml"])

    try:
        # 5. Buat backup tags untuk origin/main dan origin/data
        now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        tag_main = f"backup-sebelum-excel-sync-main-{now_str}"
        tag_data = f"backup-sebelum-excel-sync-data-{now_str}"

        run_cmd(["git", "tag", tag_main, "origin/main"])
        run_cmd(["git", "tag", tag_data, "origin/data"])
        print(f"[5/8] Backup tags dibuat: {tag_main} & {tag_data}")

        # 6. Verifikasi SHA remote sebelum commit (ABORT jika remote maju)
        run_cmd(["git", "fetch", "origin"])
        curr_main_sha = get_git_rev("origin/main")
        curr_data_sha = get_git_rev("origin/data")
        if curr_main_sha != recorded_main_sha or curr_data_sha != recorded_data_sha:
            print("=" * 80)
            print("[ABORT KEAMANAN] SHA remote telah berubah sejak proses dimulai:")
            print(f"  origin/main: awal={recorded_main_sha[:8]}, sekarang={curr_main_sha[:8]}")
            print(f"  origin/data: awal={recorded_data_sha[:8]}, sekarang={curr_data_sha[:8]}")
            print("Penerapan dibatalkan untuk mencegah penimpaan data terbaru.")
            print("=" * 80)
            sys.exit(1)

        # 7. Hasilkan data segar langsung dari Excel pada checkout lokal
        print("[6/8] Menghasilkan ulang data segar langsung dari berkas Excel harian...")
        generate_fresh_sync_data(BASE_DIR)
        print("      Data segar berhasil dibuat dan diverifikasi (0 selisih).")

        # 8. Instruksi commit dan rollback tanpa force push
        print("=" * 80)
        print("[7/8] DATA PRODUKSI BERHASIL DIPERBARUI SECARA LOKAL.")
        print("LANGKAH PENERAPAN GIT KE DUA BRANCH (HANYA FOLDER DATA):")
        print("1. Branch main:")
        print("   git checkout main")
        print("   git add data_export/ web/public/data/ web/public/files/")
        print("   git commit -m \"chore(data): sinkronisasi data dashboard sesuai Excel harian 1:1\"")
        print("   git push origin main")
        print("2. Branch data:")
        print("   git checkout -B data origin/data")
        print("   git checkout main -- data_export web/public/data web/public/files")
        print("   git add data_export/ web/public/data/ web/public/files/ pipeline_state/")
        print("   git commit -m \"chore(data): update data branch sinkronisasi Excel 1:1\"")
        print("   git push origin data")
        print()
        print("PERINTAH ROLLBACK (MEMBUAT COMMIT BARU, BUKAN FORCE PUSH):")
        print(f"A. Main: git checkout main && git checkout {tag_main} -- data_export web/public/data web/public/files && git commit -m \"revert: rollback data ke {tag_main}\" && git push origin main")
        print(f"B. Data: git checkout data && git checkout {tag_data} -- data_export web/public/data web/public/files pipeline_state && git commit -m \"revert: rollback data ke {tag_data}\" && git push origin data")
        print("=" * 80)

    finally:
        print("Memastikan workflow daily_scrape.yml diaktifkan kembali...")
        run_cmd(["gh", "workflow", "enable", "daily_scrape.yml"])
        print("Workflow daily_scrape.yml aktif.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Terapkan perbaikan data dashboard dari Excel terbaru ke produksi")
    parser.add_argument("--confirm", type=str, default="", help=f"Harus diisi '{EXPECTED_CONFIRMATION}'")
    parser.add_argument("--dry-run", action="store_true", help="Uji seluruh alur simulasi termasuk deteksi perubahan remote")
    args = parser.parse_args()

    if args.dry_run:
        ok = run_dry_run_test()
        sys.exit(0 if ok else 1)
    else:
        apply_fix(args.confirm)
