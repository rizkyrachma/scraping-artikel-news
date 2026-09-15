"""
export_excel.py
Penyusunan dataset ke DataFrame dan penyimpanan ke file Excel (.xlsx) beserta formatting styling.
"""

import os
import pandas as pd
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def save_to_excel(records: list[dict], output_path: str):
    """
    Menyimpan hasil scraping dan NLP ke file Excel dengan styling:
    - Kolom wajib: Tanggal, Title, Link Website, Media Name, Tone, Spokesperson 1, Spokesperson 2, Unit Eselon
    - Header bold dan lebar kolom auto-fit
    - Kolom Link Website berupa hyperlink aktif
    - Kolom Tanggal diformat sebagai tanggal Excel (datetime tanpa timezone)
    """
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    columns = [
        "Tanggal",
        "Title",
        "Link Website",
        "Media Name",
        "Tone",
        "Spokesperson 1",
        "Spokesperson 2",
        "Unit Eselon",
        "Terkait Kemenperin",
    ]
    df = pd.DataFrame(records, columns=columns)

    # Konversi field Tanggal ke datetime Excel tanpa timezone
    if "Tanggal" in df.columns and not df.empty:
        df["Tanggal"] = pd.to_datetime(df["Tanggal"], errors="coerce", utc=True).dt.tz_localize(None)

    def _write_excel(target_writer):
        df.to_excel(target_writer, index=False, sheet_name="Berita")
        ws = target_writer.sheets["Berita"]

        # Format header bold dan lebar kolom auto-fit
        for col_idx, col_name in enumerate(columns, start=1):
            ws.cell(row=1, column=col_idx).font = Font(bold=True)
            max_len = max(
                df[col_name].astype(str).map(len).max() if not df.empty else 0,
                len(col_name)
            )
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 60)

        # Format kolom Tanggal sebagai Date Excel
        date_col_idx = columns.index("Tanggal") + 1
        for row_idx in range(2, len(df) + 2):
            cell = ws.cell(row=row_idx, column=date_col_idx)
            if cell.value is not None:
                cell.number_format = "yyyy-mm-dd hh:mm:ss"

        # Buat Link Website jadi hyperlink aktif
        link_col_idx = columns.index("Link Website") + 1
        for row_idx in range(2, len(df) + 2):
            cell = ws.cell(row=row_idx, column=link_col_idx)
            if cell.value:
                cell.hyperlink = str(cell.value)
                cell.style = "Hyperlink"

    try:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            _write_excel(writer)
        final_path = output_path
    except PermissionError:
        base, ext = os.path.splitext(output_path)
        final_path = f"{base}_terbaru{ext}"
        print(f"[WARNING] File '{output_path}' sedang dibuka/dikunci oleh Microsoft Excel.")
        print(f"          Menyimpan ke file alternatif: '{final_path}'")
        with pd.ExcelWriter(final_path, engine="openpyxl") as writer:
            _write_excel(writer)

    return final_path
