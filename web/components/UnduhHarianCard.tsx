"use client";

import React from "react";
import { Download } from "lucide-react";

interface RecentDayItem {
  fileDate: string;
  tglDisplay: string;
  isNew?: boolean;
  count: number;
  countStr: string;
  pos: number;
  net: number;
  neg: number;
}

interface UnduhHarianProps {
  onOpenDownloadModal: () => void;
  recentDays?: RecentDayItem[];
}

export default function UnduhHarianCard({ onOpenDownloadModal, recentDays = [] }: UnduhHarianProps) {
  const handleDownload = (fileDate: string) => {
    const link = document.createElement("a");
    link.href = `/api/files/Media_Monitoring_Agro_${fileDate}.xlsx`;
    link.download = `Media_Monitoring_Agro_${fileDate}.xlsx`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="card-box unduh-harian-card panel-primary">
      <div className="card-top-section">
        {/* Header baris 1: Judul & filter cepat */}
        <div className="card-header-row">
          <h3 className="card-title">Unduh Excel Harian</h3>
          <div className="pills-group">
            <button type="button" onClick={onOpenDownloadModal} className="pill-btn">
              Bulanan
            </button>
            <button type="button" onClick={onOpenDownloadModal} className="pill-btn">
              Semua Data
            </button>
          </div>
        </div>

        {/* Header baris 2: Legenda mini */}
        <div className="legend-row">
          <div className="legend-item">
            <span className="dot dot-pos" />
            <span>Positif</span>
          </div>
          <div className="legend-item">
            <span className="dot dot-net" />
            <span>Netral</span>
          </div>
          <div className="legend-item">
            <span className="dot dot-neg" />
            <span>Negatif</span>
          </div>
        </div>
      </div>

      {/* Daftar baris tanggal - scroll internal di dalam kartu */}
      <div className="harian-list custom-scrollbar">
        {recentDays.length === 0 ? (
          <div className="p-4 text-xs text-slate-400 text-center">Memuat dataset harian...</div>
        ) : (
          recentDays.map((item, idx) => {
            const tot = item.pos + item.net + item.neg;
            const pctPos = tot > 0 ? (item.pos / tot) * 100 : 0;
            const pctNet = tot > 0 ? (item.net / tot) * 100 : 0;
            const pctNeg = tot > 0 ? (item.neg / tot) * 100 : 0;

            return (
              <div key={item.fileDate} className="harian-row">
                <div className="harian-left">
                  <span className={`harian-date ${idx === 0 ? "font-bold" : ""}`}>
                    {item.tglDisplay}
                  </span>
                  {item.isNew && <span className="badge-terbaru">Terbaru</span>}
                </div>

                <div className="harian-right">
                  <span className="harian-count">{item.countStr}</span>

                  <div
                    className="mini-tone-track"
                    title={`Pos: ${item.pos}, Net: ${item.net}, Neg: ${item.neg}`}
                  >
                    <div className="tone-seg tone-seg-pos" style={{ width: `${pctPos}%` }} />
                    <div className="tone-seg tone-seg-net" style={{ width: `${pctNet}%` }} />
                    <div className="tone-seg tone-seg-neg" style={{ width: `${pctNeg}%` }} />
                  </div>

                  <button
                    type="button"
                    onClick={() => handleDownload(item.fileDate)}
                    className="btn-download-row"
                    title={`Unduh Excel ${item.tglDisplay} (Berita & Ringkasan Negatif)`}
                    aria-label={`Unduh Excel ${item.tglDisplay}`}
                  >
                    <Download size={14} strokeWidth={2} />
                  </button>
                </div>
              </div>
            );
          })
        )}

        {/* Footer info tepat di bawah baris terakhir di area scroll */}
        <div className="card-scroll-footer">
          <span className="text-scroll-count">Menampilkan {recentDays.length} hari terakhir</span>
          <button type="button" onClick={onOpenDownloadModal} className="btn-link-action">
            Tampilkan lebih banyak →
          </button>
        </div>
      </div>
    </div>
  );
}
