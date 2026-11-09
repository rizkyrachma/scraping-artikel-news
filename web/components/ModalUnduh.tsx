"use client";

import React, { useState, useEffect, useMemo } from "react";
import { Download, X, Calendar, CheckCircle2 } from "lucide-react";
import { SummaryData } from "@/lib/types";

interface ModalUnduhProps {
  isOpen: boolean;
  onClose: () => void;
  summaryData?: SummaryData | null;
}

const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"];

function fmtShort(iso: string): string {
  const parts = iso.split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return iso;
  return `${parts[2]} ${MONTHS_SHORT[parts[1] - 1] || ""} ${parts[0]}`;
}

export default function ModalUnduh({ isOpen, onClose, summaryData }: ModalUnduhProps) {
  const latestDate = summaryData?.metadata?.last_updated || "";
  const [format, setFormat] = useState<"daily" | "merged">("daily");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  useEffect(() => {
    if (latestDate && !startDate && !endDate) {
      setStartDate(latestDate);
      setEndDate(latestDate);
    }
  }, [latestDate, startDate, endDate]);

  const rangeInfo = useMemo(() => {
    const counts = summaryData?.metadata?.calendar_counts || {};
    if (!startDate || !endDate) {
      return { daysWithData: 0, totalArticles: 0, totalDays: 0 };
    }
    const d1 = new Date(`${startDate}T00:00:00Z`);
    const d2 = new Date(`${endDate}T00:00:00Z`);
    if (Number.isNaN(d1.getTime()) || Number.isNaN(d2.getTime()) || d1 > d2) {
      return { daysWithData: 0, totalArticles: 0, totalDays: 0 };
    }
    let daysWithData = 0;
    let totalArticles = 0;
    let totalDays = 0;
    const cur = new Date(d1);
    while (cur <= d2 && totalDays < 365) {
      const iso = cur.toISOString().slice(0, 10);
      const cnt = counts[iso] || 0;
      if (cnt > 0) {
        daysWithData += 1;
        totalArticles += cnt;
      }
      totalDays += 1;
      cur.setUTCDate(cur.getUTCDate() + 1);
    }
    return { daysWithData, totalArticles, totalDays };
  }, [startDate, endDate, summaryData]);

  if (!isOpen) return null;

  const isSingleDay = Boolean(startDate && startDate === endDate);

  const handleDownload = () => {
    const targetFile =
      format === "daily" && isSingleDay
        ? `Media_Monitoring_Agro_${startDate}.xlsx`
        : "Media_Monitoring_Agro_Semua_Data.xlsx";
    const link = document.createElement("a");
    link.href = `/api/files/${targetFile}`;
    link.download = targetFile;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    onClose();
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header Modal */}
        <div className="modal-header">
          <div className="modal-title-wrap">
            <Download size={18} strokeWidth={2.2} />
            <span className="modal-title">Unduh Excel Media Monitoring</span>
          </div>
          <button type="button" onClick={onClose} className="btn-modal-close" aria-label="Tutup">
            <X size={18} strokeWidth={2.5} />
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="modal-body-scroll custom-scrollbar">
          {/* Input Rentang Tanggal */}
          <div className="date-range-row">
            <div className="date-field">
              <label>Dari:</label>
              <div className="input-with-icon">
                <Calendar size={15} />
                <input
                  type="date"
                  value={startDate}
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
                  onChange={(e) => setEndDate(e.target.value)}
                  className="input-neo"
                />
              </div>
            </div>
          </div>

          {/* Info Banner */}
          <div className="info-banner-green">
            <CheckCircle2 size={16} className="text-emerald-700" strokeWidth={2.2} />
            <span>
              {startDate && endDate
                ? `${rangeInfo.daysWithData} hari berdata (${fmtShort(startDate)} – ${fmtShort(endDate)}), total ${rangeInfo.totalArticles.toLocaleString("id-ID")} berita`
                : "Pilih rentang tanggal untuk mengunduh dataset"}
            </span>
          </div>

          {/* Format Unduhan Radio */}
          <div className="radio-group-container">
            <div className="format-section-title">Pilihan Unduhan:</div>

            <label className={`radio-card ${format === "daily" ? "active" : ""}`}>
              <input
                type="radio"
                name="downloadFormat"
                checked={format === "daily"}
                onChange={() => setFormat("daily")}
              />
              <div className="radio-text">
                <div className="radio-title">
                  {isSingleDay ? `File Excel Harian (${fmtShort(startDate)})` : "File Excel Harian / Rekap Terbaru"}
                </div>
                <div className="radio-desc">
                  Berisi file Excel lengkap dengan Sheet Berita &amp; Sheet Ringkasan Negatif
                </div>
              </div>
            </label>

            <label className={`radio-card ${format === "merged" ? "active" : ""}`}>
              <input
                type="radio"
                name="downloadFormat"
                checked={format === "merged"}
                onChange={() => setFormat("merged")}
              />
              <div className="radio-text">
                <div className="radio-title">Gabung seluruh arsip dalam satu file Excel (.xlsx)</div>
                <div className="radio-desc">
                  Mencakup arsip Media_Monitoring_Agro_Semua_Data.xlsx dan Sheet Ringkasan Negatif
                </div>
              </div>
            </label>
          </div>
        </div>

        {/* Modal Footer (Pinned) */}
        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn-modal-cancel">
            Batal
          </button>
          <button type="button" onClick={handleDownload} className="btn-modal-submit">
            <Download size={14} strokeWidth={2} />
            <span>
              {format === "daily" && isSingleDay ? "Unduh Excel Harian" : "Unduh Semua Data Excel"}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
