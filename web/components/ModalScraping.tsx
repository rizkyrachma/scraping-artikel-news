"use client";

import React, { useState, useMemo } from "react";
import { Play, X, Calendar, CheckCircle2, Clock } from "lucide-react";

interface ModalScrapingProps {
  isOpen: boolean;
  onClose: () => void;
  onStartScraping: (mode: "auto" | "manual", skipExisting: boolean, startDate?: string, endDate?: string) => void;
  calendarCounts?: Record<string, number>;
}

const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

function getYesterdayWib(): { iso: string; shortLabel: string; fullLabel: string } {
  const nowWib = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Jakarta" }));
  nowWib.setDate(nowWib.getDate() - 1);
  const y = nowWib.getFullYear();
  const m = nowWib.getMonth();
  const d = nowWib.getDate();
  const iso = `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  return {
    iso,
    shortLabel: `${d} ${MONTHS_SHORT[m]}`,
    fullLabel: `${d} ${MONTHS_SHORT[m]} ${y}`,
  };
}

function formatDateIdShort(iso: string, withYear = true): string {
  const parts = iso.split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return iso;
  const [y, m, d] = parts;
  const mon = MONTHS_SHORT[m - 1] || "";
  return withYear ? `${d} ${mon} ${y}` : `${d} ${mon}`;
}

function enumerateDates(startIso: string, endIso: string): string[] {
  const d1 = new Date(`${startIso}T00:00:00Z`);
  const d2 = new Date(`${endIso}T00:00:00Z`);
  if (Number.isNaN(d1.getTime()) || Number.isNaN(d2.getTime()) || d1 > d2) return [];
  const res: string[] = [];
  const cur = new Date(d1);
  while (cur <= d2 && res.length < 31) {
    res.push(cur.toISOString().slice(0, 10));
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  return res;
}

export default function ModalScraping({
  isOpen,
  onClose,
  onStartScraping,
  calendarCounts = {},
}: ModalScrapingProps) {
  const yesterday = useMemo(() => getYesterdayWib(), []);
  const [tab, setTab] = useState<"auto" | "manual">("auto");
  const [skipExisting, setSkipExisting] = useState<boolean>(true);
  const [startDate, setStartDate] = useState(() => {
    const d = new Date(`${yesterday.iso}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - 2);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => yesterday.iso);

  const manualStats = useMemo(() => {
    const allDates = enumerateDates(startDate, endDate);
    const totalDays = allDates.length;
    const missingDays = allDates.filter((dt) => !calendarCounts[dt]).length;
    const effectiveDays = skipExisting ? (missingDays || totalDays) : totalDays;
    const sameMonthYear =
      startDate.slice(0, 7) === endDate.slice(0, 7) && startDate !== endDate;
    const rangeLabel =
      startDate === endDate
        ? formatDateIdShort(startDate, true)
        : sameMonthYear
        ? `${Number(startDate.slice(8, 10))} s.d ${formatDateIdShort(endDate, true)}`
        : `${formatDateIdShort(startDate, false)} s.d ${formatDateIdShort(endDate, true)}`;

    return {
      totalDays,
      missingDays,
      effectiveDays: Math.max(1, effectiveDays),
      rangeLabel,
    };
  }, [startDate, endDate, skipExisting, calendarCounts]);

  if (!isOpen) return null;

  const effectiveCount = tab === "auto" ? 1 : manualStats.effectiveDays;
  const estMinutes = effectiveCount * 5;

  const handleSubmit = () => {
    if (tab === "auto") {
      onStartScraping("auto", skipExisting, yesterday.iso, yesterday.iso);
    } else {
      onStartScraping("manual", skipExisting, startDate, endDate);
    }
    onClose();
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header Modal */}
        <div className="modal-header">
          <div className="modal-title-wrap">
            <Play size={18} fill="currentColor" strokeWidth={2} />
            <span className="modal-title">Jalankan Scraping</span>
          </div>
          <button type="button" onClick={onClose} className="btn-modal-close" aria-label="Tutup">
            <X size={18} strokeWidth={2.5} />
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="modal-body-scroll custom-scrollbar">
          {/* Tab Pilihan Mode */}
          <div className="modal-tabs">
            <button
              type="button"
              onClick={() => setTab("auto")}
              className={`tab-item ${tab === "auto" ? "active" : ""}`}
            >
              Otomatis: kemarin ({yesterday.shortLabel})
            </button>
            <button
              type="button"
              onClick={() => setTab("manual")}
              className={`tab-item ${tab === "manual" ? "active" : ""}`}
            >
              Pilih tanggal manual
            </button>
          </div>

          {/* Input Rentang Tanggal Manual */}
          {tab === "manual" && (
            <div className="date-range-row">
              <div className="date-field">
                <label>Dari:</label>
                <div className="input-with-icon">
                  <Calendar size={15} />
                  <input
                    type="date"
                    value={startDate}
                    max={yesterday.iso}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="input-neo"
                  />
                </div>
              </div>

              <span className="date-arrow">→</span>

              <div className="date-field">
                <label>Sampai:</label>
                <div className="input-with-icon">
                  <Calendar size={15} />
                  <input
                    type="date"
                    value={endDate}
                    max={yesterday.iso}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="input-neo"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Info Banner */}
          <div className="info-banner-green">
            <CheckCircle2 size={16} className="text-emerald-700" strokeWidth={2.2} />
            <span>
              {tab === "auto"
                ? `1 tanggal siap dievaluasi (${yesterday.fullLabel})`
                : manualStats.missingDays > 0 && skipExisting
                ? `${manualStats.missingDays} tanggal belum punya data (${manualStats.rangeLabel})`
                : `${manualStats.totalDays} tanggal siap dievaluasi (${manualStats.rangeLabel})`}
            </span>
          </div>

          {/* Radio Opsi Filter Duplikat */}
          <div className="radio-group-container">
            <label className={`radio-card ${skipExisting ? "active" : ""}`}>
              <input
                type="radio"
                name="scrapeMode"
                checked={skipExisting}
                onChange={() => setSkipExisting(true)}
              />
              <div className="radio-text">
                <div className="radio-title">Lewati tanggal yang sudah ada data (Rekomendasi hemat kuota)</div>
              </div>
            </label>

            <label className={`radio-card ${!skipExisting ? "active" : ""}`}>
              <input
                type="radio"
                name="scrapeMode"
                checked={!skipExisting}
                onChange={() => setSkipExisting(false)}
              />
              <div className="radio-text">
                <div className="radio-title">Ambil ulang dan timpa data lama</div>
              </div>
            </label>
          </div>

          {/* Perkiraan Waktu */}
          <div className="meta-time-estimate">
            <Clock size={13} className="text-slate-500" />
            <span>
              Perkiraan waktu sekitar {estMinutes} menit (5 menit per hari). Disarankan maksimal 7 hari, batas 31 hari.
            </span>
          </div>
        </div>

        {/* Modal Footer (Pinned) */}
        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn-modal-cancel">
            Batal
          </button>
          <button type="button" onClick={handleSubmit} className="btn-modal-submit">
            <Play size={14} fill="currentColor" />
            <span>
              Mulai Scraping (
              {tab === "auto"
                ? "1 hari"
                : skipExisting && manualStats.missingDays > 0
                ? `${manualStats.missingDays} hari baru`
                : `${manualStats.totalDays} hari`}
              )
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
