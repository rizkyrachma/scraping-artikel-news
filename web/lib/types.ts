export interface Article {
  id: number;
  title: string;
  link: string;
  media: string;
  tone: "Positif" | "Netral" | "Negatif";
  date: string;
  datetime?: string;
  time?: string;
  date_display?: string;
  spokesperson?: string;
  unit?: string;
  commodity?: string;
  has_review?: boolean;
  review_text?: string;
}

export interface SummaryData {
  metadata: {
    last_updated: string;
    last_updated_display: string;
    earliest_date: string;
    total_articles: number;
    tone_summary: {
      Positif: number;
      Netral: number;
      Negatif: number;
    };
    calendar_counts: Record<string, number>;
  };
  commodities: Array<{ name: string; count: number }>;
  spokespersons: Array<any>;
  recent_articles: Article[];
}

export interface RunHistoryItem {
  id: string;
  waktu_display: string;
  timestamp: string;
  durasi: string;
  hasil_berita: number;
  status: "Berhasil" | "Gagal" | "Berjalan";
  pemicu?: "Terjadwal" | "Manual" | string;
  rentang_data?: string;
  target_date?: string;
  catatan?: string;
  log_url?: string;
  stats?: {
    mentah: number;
    filter_media: number;
    filter_tgl: number;
    unik: number;
    final: number;
    noise_dibuang_pct: number;
    tone_cadangan_pct: number;
    perlu_review: number;
    tanpa_spokesperson: number;
  };
}
