"use client";

import React, { useState, useEffect } from "react";
import { Download } from "lucide-react";

interface UnduhHarianProps {
  onOpenDownloadModal: () => void;
}

const FALLBACK_14_DAYS = [
  { tglDisplay: "Kamis, 5 Nov 2026", fileDate: "2026-11-05", isNew: true, countStr: "148 berita", pos: 68, net: 79, neg: 1 },
  { tglDisplay: "Rabu, 4 Nov 2026", fileDate: "2026-11-04", isNew: false, countStr: "164 berita", pos: 75, net: 86, neg: 3 },
  { tglDisplay: "Selasa, 3 Nov 2026", fileDate: "2026-11-03", isNew: false, countStr: "52 berita", pos: 15, net: 37, neg: 0 },
  { tglDisplay: "Senin, 2 Nov 2026", fileDate: "2026-11-02", isNew: false, countStr: "36 berita", pos: 11, net: 24, neg: 1 },
  { tglDisplay: "Minggu, 1 Nov 2026", fileDate: "2026-11-01", isNew: false, countStr: "17 berita", pos: 8, net: 6, neg: 3 },
  { tglDisplay: "Sabtu, 31 Okt 2026", fileDate: "2026-10-31", isNew: false, countStr: "20 berita", pos: 4, net: 10, neg: 6 },
  { tglDisplay: "Jumat, 30 Okt 2026", fileDate: "2026-10-30", isNew: false, countStr: "52 berita", pos: 4, net: 31, neg: 17 },
  { tglDisplay: "Kamis, 29 Okt 2026", fileDate: "2026-10-29", isNew: false, countStr: "25 berita", pos: 3, net: 21, neg: 1 },
  { tglDisplay: "Rabu, 28 Okt 2026", fileDate: "2026-10-28", isNew: false, countStr: "21 berita", pos: 8, net: 12, neg: 1 },
  { tglDisplay: "Selasa, 27 Okt 2026", fileDate: "2026-10-27", isNew: false, countStr: "76 berita", pos: 54, net: 9, neg: 13 },
  { tglDisplay: "Senin, 26 Okt 2026", fileDate: "2026-10-26", isNew: false, countStr: "96 berita", pos: 67, net: 6, neg: 23 },
  { tglDisplay: "Minggu, 25 Okt 2026", fileDate: "2026-10-25", isNew: false, countStr: "21 berita", pos: 15, net: 6, neg: 0 },
  { tglDisplay: "Sabtu, 24 Okt 2026", fileDate: "2026-10-24", isNew: false, countStr: "12 berita", pos: 9, net: 1, neg: 2 },
  { tglDisplay: "Jumat, 23 Okt 2026", fileDate: "2026-10-23", isNew: false, countStr: "28 berita", pos: 18, net: 6, neg: 4 },
];

export default function UnduhHarianCard({ onOpenDownloadModal }: UnduhHarianProps) {
  const [harianList, setHarianList] = useState(FALLBACK_14_DAYS);

  useEffect(() => {
    fetch("/data/summary.json")
      .then((res) => res.json())
      .then((data) => {
        if (data && Array.isArray(data.recent_days) && data.recent_days.length > 0) {
          setHarianList(data.recent_days);
        }
      })
      .catch(() => {});
  }, []);

  const handleDownload = (fileDate: string) => {
    const link = document.createElement("a");
    link.href = `/files/Media_Monitoring_Agro_${fileDate}.xlsx`;
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
        {harianList.map((item, idx) => {
          const tot = item.pos + item.net + item.neg;
          const pctPos = tot > 0 ? (item.pos / tot) * 100 : 0;
          const pctNet = tot > 0 ? (item.net / tot) * 100 : 0;
          const pctNeg = tot > 0 ? (item.neg / tot) * 100 : 0;

          return (
            <div key={idx} className="harian-row">
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
        })}

        {/* Footer info tepat di bawah baris terakhir di area scroll */}
        <div className="card-scroll-footer">
          <span className="text-scroll-count">Menampilkan {harianList.length} hari terakhir</span>
          <button type="button" onClick={onOpenDownloadModal} className="btn-link-action">
            Tampilkan lebih banyak →
          </button>
        </div>
      </div>
    </div>
  );
}
