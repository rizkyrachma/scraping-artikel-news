"use client";

import React, { useState, useEffect, useMemo } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { SummaryData } from "@/lib/types";

interface KalenderProps {
  summaryData: SummaryData | null;
  selectedDate: string;
  onSelectDate: (date: string) => void;
  onViewNewsTab: () => void;
}

const MONTHS_FULL_ID = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember",
];

function formatMiniDate(iso?: string): string {
  if (!iso || iso.length < 10) return "Terbaru";
  const m = Number(iso.slice(5, 7));
  const d = Number(iso.slice(8, 10));
  const shortM = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"];
  return `${d} ${shortM[m] || ""}`;
}

export default function KalenderKompakCard({
  summaryData,
  selectedDate,
  onSelectDate,
  onViewNewsTab,
}: KalenderProps) {
  const latestDate = summaryData?.metadata?.last_updated || "";
  const [viewYearMonth, setViewYearMonth] = useState<string>("2026-11");

  useEffect(() => {
    if (selectedDate && selectedDate.length >= 7) {
      setViewYearMonth(selectedDate.slice(0, 7));
    } else if (latestDate && latestDate.length >= 7) {
      setViewYearMonth(latestDate.slice(0, 7));
    }
  }, [selectedDate, latestDate]);

  const calendarCounts = useMemo(
    () => summaryData?.metadata?.calendar_counts || {},
    [summaryData]
  );

  const [viewYear, viewMonth] = useMemo(() => {
    const parts = viewYearMonth.split("-").map(Number);
    if (parts.length === 2 && !Number.isNaN(parts[0]) && !Number.isNaN(parts[1])) {
      return [parts[0], parts[1]];
    }
    return [2026, 11];
  }, [viewYearMonth]);

  const monthTitle = `${MONTHS_FULL_ID[viewMonth - 1] || "Bulan"} ${viewYear}`;

  const shiftMonth = (delta: number) => {
    const dt = new Date(Date.UTC(viewYear, viewMonth - 1 + delta, 1));
    setViewYearMonth(`${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}`);
  };

  const monthGrid = useMemo(() => {
    const firstDayUtc = new Date(Date.UTC(viewYear, viewMonth - 1, 1));
    const startOffset = (firstDayUtc.getUTCDay() + 6) % 7; // Senin = 0 .. Minggu = 6
    const daysInMonth = new Date(Date.UTC(viewYear, viewMonth, 0)).getUTCDate();
    const totalCells = startOffset + daysInMonth <= 35 ? 35 : 42;

    const weeks: Array<Array<{ iso: string; day: number; isOther: boolean; hasData: boolean }>> = [];
    let currentWeek: Array<{ iso: string; day: number; isOther: boolean; hasData: boolean }> = [];

    for (let i = 0; i < totalCells; i++) {
      const dt = new Date(Date.UTC(viewYear, viewMonth - 1, 1 - startOffset + i));
      const y = dt.getUTCFullYear();
      const m = dt.getUTCMonth() + 1;
      const d = dt.getUTCDate();
      const iso = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const isOther = y !== viewYear || m !== viewMonth;
      const hasData = !isOther && (calendarCounts[iso] || 0) > 0;
      currentWeek.push({ iso, day: d, isOther, hasData });
      if (currentWeek.length === 7) {
        weeks.push(currentWeek);
        currentWeek = [];
      }
    }
    return weeks;
  }, [viewYear, viewMonth, calendarCounts]);

  const newsList = useMemo(() => {
    const allRecent = summaryData?.recent_articles || [];
    const forSelected = allRecent.filter((a) => a.date === selectedDate);
    const chosen = forSelected.length > 0 ? forSelected : allRecent;
    return chosen.slice(0, 10).map((a) => ({
      mediaDate: `${a.media || "Media"} • ${formatMiniDate(a.date)}`,
      tone: a.tone || "Netral",
      title: a.title || "Berita Industri Agro",
    }));
  }, [summaryData, selectedDate]);

  const daysHeader = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"];

  return (
    <>
      {/* 1. Kalender Mini (Panel Sekunder) */}
      <div className="card-box card-kalender panel-secondary">
        <div className="card-header-row">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => shiftMonth(-1)}
              className="p-0.5 rounded hover:bg-slate-100 text-slate-600"
              aria-label="Bulan sebelumnya"
            >
              <ChevronLeft size={14} />
            </button>
            <h3 className="card-title">{monthTitle}</h3>
            <button
              type="button"
              onClick={() => shiftMonth(1)}
              className="p-0.5 rounded hover:bg-slate-100 text-slate-600"
              aria-label="Bulan berikutnya"
            >
              <ChevronRight size={14} />
            </button>
          </div>
          {latestDate && (
            <button
              type="button"
              onClick={() => {
                setViewYearMonth(latestDate.slice(0, 7));
                onSelectDate(latestDate);
              }}
              className="pill-dark-btn"
            >
              Ke data terbaru
            </button>
          )}
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
                {week.map((cell) => {
                  const isSelected = !cell.isOther && cell.iso === selectedDate;
                  return (
                    <button
                      key={cell.iso}
                      type="button"
                      disabled={cell.isOther || !cell.hasData}
                      onClick={() => onSelectDate(cell.iso)}
                      className={`cal-day-cell ${isSelected ? "selected" : ""} ${
                        cell.isOther ? "other-month" : ""
                      } ${cell.hasData ? "has-data" : ""}`}
                    >
                      <span className="cal-day-num">{cell.day}</span>
                      {cell.hasData && !isSelected && <span className="cal-data-dot" />}
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
          {newsList.length === 0 ? (
            <div className="p-3 text-xs text-slate-400 text-center">Memuat cuplikan berita...</div>
          ) : (
            newsList.map((item, idx) => (
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
            ))
          )}
        </div>
      </div>
    </>
  );
}
