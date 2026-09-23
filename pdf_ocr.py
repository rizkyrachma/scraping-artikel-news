"""
pdf_ocr.py
Modul ekstraksi konten teks dari file PDF dan gambar kliping koran/dokumen cetak
menggunakan EasyOCR (Indonesian & English) dan pypdf.
Mendukung:
1. Ekstraksi otomatis dari URL (termasuk kliping koran stream api.digivla.id).
2. Ekstraksi otomatis dari file lokal (misal folder pdf_input/).
3. Penanganan hybrid: teks digital langsung via pypdf; gambar scan via EasyOCR.
"""

import io
import os
import re
import sys
import base64
from pathlib import Path
from PIL import Image
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Pastikan encoding console tidak error pada karakter progress bar
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    import easyocr  # type: ignore
except ImportError:
    easyocr = None

try:
    import pypdf  # type: ignore
except ImportError:
    pypdf = None

# Global cached EasyOCR reader (lazy-loaded untuk menghemat resource)
_EASYOCR_READER = None


def get_ocr_reader():
    """Mengembalikan instance singleton EasyOCR reader (id, en)."""
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        if easyocr is None:
            raise RuntimeError("Package 'easyocr' belum terpasang. Jalankan: pip install easyocr")
        _EASYOCR_READER = easyocr.Reader(["id", "en"], gpu=False)
    return _EASYOCR_READER


def extract_images_from_pdf_bytes(pdf_bytes: bytes) -> list[Image.Image]:
    """
    Mengekstrak seluruh gambar raster dari biner PDF:
    - Metode 1: Menggunakan pypdf.PdfReader (page.images)
    - Metode 2: Fallback stream ReportLab / Adobe ASCII85 (seperti kliping koran Digivla)
    """
    images: list[Image.Image] = []

    # Metode 1: pypdf page.images
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                for img_file in page.images:
                    img = Image.open(io.BytesIO(img_file.data))
                    images.append(img)
        except Exception:
            pass

    if images:
        return images

    # Metode 2: Ekstraksi fallback untuk stream Adobe ASCII85 + DCTDecode (ReportLab)
    try:
        start_idx = 0
        while True:
            pos = pdf_bytes.find(b"stream\n", start_idx)
            if pos == -1:
                break
            end_pos = pdf_bytes.find(b"~>endstream", pos)
            if end_pos != -1:
                raw_stream = pdf_bytes[pos + len(b"stream\n"):end_pos + 2]
                try:
                    jpeg_bytes = base64.a85decode(raw_stream, adobe=True)
                    img = Image.open(io.BytesIO(jpeg_bytes))
                    images.append(img)
                except Exception:
                    pass
                start_idx = end_pos + 11
            else:
                break
    except Exception:
        pass

    return images


def ocr_image(image_input) -> str:
    """Menjalankan OCR pada gambar (PIL Image, path str, atau ndarray) menggunakan EasyOCR."""
    reader = get_ocr_reader()
    results = reader.readtext(image_input, detail=0, paragraph=True)
    if not results:
        results = reader.readtext(image_input, detail=0, paragraph=False)
    return "\n\n".join(results).strip()


def extract_text_from_pdf_bytes(pdf_bytes: bytes, max_pages: int = 5) -> str:
    """
    Mengekstrak teks dari biner PDF:
    1. Cek apakah ada teks digital langsung (pypdf). Jika >= 150 karakter, gunakan langsung (cepat).
    2. Jika teks kosong / < 150 karakter (dokumen hasil scan), ekstrak gambar dan jalankan EasyOCR.
    """
    if not pdf_bytes:
        return ""

    # 1. Cek teks digital
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            pages = reader.pages[:max_pages]
            digital_text = "\n\n".join([p.extract_text() or "" for p in pages]).strip()
            if len(digital_text) >= 150:
                return digital_text
        except Exception:
            pass

    # 2. Ekstraksi gambar scan & jalankan OCR
    images = extract_images_from_pdf_bytes(pdf_bytes)
    if not images:
        return ""

    ocr_texts = []
    for img in images[:max_pages]:
        text = ocr_image(img)
        if text:
            ocr_texts.append(text)

    return "\n\n".join(ocr_texts).strip()


def extract_text_from_pdf_url(url: str, timeout: int = 20) -> str:
    """Mendownload file PDF dari URL dan mengekstrak teksnya (hybrid digital/OCR)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 200 and resp.content:
            return extract_text_from_pdf_bytes(resp.content)
    except Exception as err:
        print(f"[PDF OCR Warning] Gagal mengunduh/memproses PDF dari {url}: {err}")
    return ""


def process_pdf_input_folder(folder_path: str | Path = "pdf_input") -> list[dict]:
    """
    Membaca seluruh file PDF / gambar scan yang ditaruh manual di folder pdf_input/.
    Mengembalikan list dict: [{'filename': ..., 'path': ..., 'text': ...}].
    """
    folder = Path(folder_path)
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        return []

    results = []
    for file_path in folder.iterdir():
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext in (".pdf", ".jpg", ".jpeg", ".png"):
            print(f"[PDF Input] Memproses file manual: {file_path.name}...")
            try:
                if ext == ".pdf":
                    with open(file_path, "rb") as f:
                        text = extract_text_from_pdf_bytes(f.read())
                else:
                    text = ocr_image(str(file_path))

                if text:
                    results.append({
                        "filename": file_path.name,
                        "path": str(file_path.absolute()),
                        "text": text,
                        "sumber_data": "PDF_Manual",
                    })
            except Exception as err:
                print(f"[PDF Input Error] Gagal memproses {file_path.name}: {err}")
    return results
