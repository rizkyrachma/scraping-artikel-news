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
        "Keywords",
    ]
    df = pd.DataFrame(records)
    if not df.empty:
        # Dukung key 'Keyword' atau 'keyword' jika 'Keywords' belum ada
        if "Keywords" not in df.columns:
            if "Keyword" in df.columns:
                df["Keywords"] = df["Keyword"]
            elif "keyword" in df.columns:
                df["Keywords"] = df["keyword"]
            else:
                df["Keywords"] = ""
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        df = df[columns]
    else:
        df = pd.DataFrame(columns=columns)

    # Konversi field Tanggal ke datetime Excel tanpa timezone
    if "Tanggal" in df.columns and not df.empty:
        import dateparser

        def _parse_date(val):
            if pd.isna(val) or not val:
                return None
            if isinstance(val, pd.Timestamp):
                return val.tz_localize(None) if val.tzinfo else val
            try:
                dt = pd.to_datetime(val, utc=True)
                if not pd.isna(dt):
                    return dt.tz_localize(None) if dt.tzinfo else dt
            except Exception:
                pass
            try:
                parsed = dateparser.parse(str(val))
                if parsed:
                    return pd.Timestamp(parsed)
            except Exception:
                pass
            return None

        df["Tanggal"] = df["Tanggal"].apply(_parse_date)

    def _write_excel(target_writer):
        df.to_excel(target_writer, index=False, sheet_name="Berita")
        ws = target_writer.sheets["Berita"]

        # Format header bold dan lebar kolom auto-fit
        for col_idx, col_name in enumerate(columns, start=1):
            ws.cell(row=1, column=col_idx).font = Font(bold=True)
            col_lengths = [len(str(v)) for v in df[col_name].dropna() if str(v).strip()]
            max_len = max(max(col_lengths) if col_lengths else 0, len(col_name))
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
