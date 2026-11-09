"use client";

import React, { useState, useEffect } from "react";

interface KalenderProps {
  onSelectDate: (date: string) => void;
  onViewNewsTab: () => void;
}

const FALLBACK_NEWS = [
  { mediaDate: "Antaranews • 5 Nov", tone: "Positif", title: "Kemenperin Pacu Hilirisasi Industri Sawit Nasional" },
  { mediaDate: "Kompas • 5 Nov", tone: "Positif", title: "Implementasi B40 Perkuat Kemandirian Energi Agro" },
  { mediaDate: "Detik • 4 Nov", tone: "Netral", title: "Kesiapan Pasokan Tebu Musim Giling Pabrik Gula" },
  { mediaDate: "Bisnis Indonesia • 4 Nov", tone: "Positif", title: "Optimisme Ekspor Minyak Atsiri dan Oleokimia" },
  { mediaDate: "CNN Indonesia • 2 Nov", tone: "Negatif", title: "Investigasi Pelepasan Gas Pabrik Kertas Karawang" },
  { mediaDate: "Investor Daily • 2 Nov", tone: "Positif", title: "Percepatan Sertifikasi Halal Mamin Olahan Ekspor" },
  { mediaDate: "Kontan • 1 Nov", tone: "Netral", title: "Stabilitas Pasokan Gandum dan Tepung Industri" },
  { mediaDate: "Republika • 31 Okt", tone: "Positif", title: "Penguatan Industri Pengolahan Kakao dan Cokelat" },
];

export default function KalenderKompakCard({ onSelectDate, onViewNewsTab }: KalenderProps) {
  const [selectedDay, setSelectedDay] = useState(5);
  const [newsList, setNewsList] = useState(FALLBACK_NEWS);

  useEffect(() => {
    fetch("/data/summary.json")
      .then((res) => res.json())
      .then((data) => {
        if (data && Array.isArray(data.recent_articles) && data.recent_articles.length > 0) {
          const mapped = data.recent_articles.slice(0, 10).map((a: any) => ({
            mediaDate: `${a.media || "Media"} • ${a.date ? a.date.slice(5) : "Terbaru"}`,
            tone: a.tone || "Netral",
            title: a.title || "Berita Industri Agro",
          }));
          setNewsList(mapped);
        }
      })
      .catch(() => {});
  }, []);

  const daysHeader = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"];

  // Grid November 2026 (6 minggu)
  const monthGrid = [
    [["26", true, false, 26], ["27", true, false, 27], ["28", true, false, 28], ["29", true, false, 29], ["30", true, true, 30], ["31", true, true, 31], ["1", false, true, 1]],
    [["2", false, true, 2], ["3", false, true, 3], ["4", false, true, 4], ["5", false, true, 5], ["6", false, false, 6], ["7", false, false, 7], ["8", false, false, 8]],
    [["9", false, false, 9], ["10", false, false, 10], ["11", false, false, 11], ["12", false, false, 12], ["13", false, false, 13], ["14", false, false, 14], ["15", false, false, 15]],
    [["16", false, false, 16], ["17", false, false, 17], ["18", false, false, 18], ["19", false, false, 19], ["20", false, false, 20], ["21", false, false, 21], ["22", false, false, 22]],
    [["23", false, false, 23], ["24", false, false, 24], ["25", false, false, 25], ["26", false, false, 26], ["27", false, false, 27], ["28", false, false, 28], ["29", false, false, 29]],
    [["30", false, false, 30], ["1", true, false, 1], ["2", true, false, 2], ["3", true, false, 3], ["4", true, false, 4], ["5", true, false, 5], ["6", true, false, 6]],
  ];

  const handleDayClick = (dayNum: number, isOther: boolean, hasData: boolean) => {
    if (!isOther && hasData) {
      setSelectedDay(dayNum);
      const dateStr = `2026-11-${String(dayNum).padStart(2, "0")}`;
      onSelectDate(dateStr);
    }
  };

  return (
    <>
      {/* 1. Kalender Mini (Panel Sekunder) */}
      <div className="card-box card-kalender panel-secondary">
        <div className="card-header-row">
          <h3 className="card-title">November 2026</h3>
          <button
            type="button"
            onClick={() => {
              setSelectedDay(5);
              onSelectDate("2026-11-05");
            }}
            className="pill-dark-btn"
          >
            Ke data terbaru
          </button>
        </div>

        <div className="cal-sub-label">Pilih tanggal untuk melihat ringkasan</div>

        <div className="cal-grid">
          <div className="cal-days-header">
            {daysHeader.map((d) => (
              <span key={d} className="cal-header-cell">
                {d}
              </span>
            ))}
          </div>

          <div className="cal-weeks-body">
            {monthGrid.map((week, wIdx) => (
              <div key={wIdx} className="cal-week-row">
                {week.map(([dStr, isOther, hasData, dayNum], dIdx) => {
                  const isSelected = !isOther && dayNum === selectedDay;

                  return (
                    <button
                      key={dIdx}
                      type="button"
                      disabled={Boolean(isOther) || !Boolean(hasData)}
                      onClick={() =>
                        handleDayClick(dayNum as number, Boolean(isOther), Boolean(hasData))
                      }
                      className={`cal-day-cell ${isSelected ? "selected" : ""} ${
                        Boolean(isOther) ? "other-month" : ""
                      } ${Boolean(hasData) ? "has-data" : ""}`}
                    >
                      <span className="cal-day-num">{dStr}</span>
                      {Boolean(hasData) && !isSelected && <span className="cal-data-dot" />}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 2. Cuplikan Berita (Panel Sekunder - Internal Scrollable) */}
      <div className="card-box card-cuplikan panel-secondary">
        <div className="card-header-row">
          <h3 className="card-title">Cuplikan Berita</h3>
          <button type="button" onClick={onViewNewsTab} className="btn-link-action">
            Lihat di Berita →
          </button>
        </div>

        <div className="cuplikan-list custom-scrollbar">
          {newsList.map((item, idx) => (
            <div key={idx} className="cuplikan-item">
              <div className="cuplikan-meta">
                <span className="cuplikan-source">{item.mediaDate}</span>
                <span
                  className={`badge-tone ${
                    item.tone === "Positif"
                      ? "badge-tone-pos"
                      : item.tone === "Negatif"
                      ? "badge-tone-neg"
                      : "badge-tone-net"
                  }`}
                >
                  {item.tone}
                </span>
              </div>
              <div className="cuplikan-headline" title={item.title}>
                {item.title}
              </div>
              {idx < newsList.length - 1 && <div className="cuplikan-divider" />}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
