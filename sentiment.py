"""
sentiment.py
Klasifikasi tone/sentimen berita industri (Positif / Netral / Negatif)
menggunakan model IndoBERT fine-tuned (mdhugol/indonesia-bert-sentiment-classification).
"""

from transformers import pipeline  # type: ignore

_model = None


def get_model():
    """
    Lazy-loading model pipeline sentiment analysis IndoBERT.
    """
    global _model
    if _model is None:
        _model = pipeline(
            "sentiment-analysis",
            model="mdhugol/indonesia-bert-sentiment-classification",
            tokenizer="mdhugol/indonesia-bert-sentiment-classification",
        )
    return _model


# Mapping label output model IndoBERT: 3 kelas asli (Positif, Netral, Negatif)
LABEL_MAP = {"LABEL_0": "Positif", "LABEL_1": "Netral", "LABEL_2": "Negatif"}


def classify_tone(text: str) -> str:
    """
    Mengklasifikasikan tone artikel menjadi 'Positif', 'Netral', atau 'Negatif'
    sesuai label asli model IndoBERT tanpa pemaksaan ke biner.
    """
    if not text or not text.strip():
        return "Netral"

    model = get_model()
    snippet = text[:1500]

    try:
        result = model(snippet, truncation=True, max_length=512)[0]
        return LABEL_MAP.get(result["label"], "Netral")
    except Exception:
        return "Netral"
