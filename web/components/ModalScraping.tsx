"use client";

import React, { useState } from "react";
import { Play, X, Calendar, CheckCircle2, Clock } from "lucide-react";

interface ModalScrapingProps {
  isOpen: boolean;
  onClose: () => void;
  onStartScraping: (mode: "auto" | "manual", skipExisting: boolean, startDate?: string, endDate?: string) => void;
}

export default function ModalScraping({ isOpen, onClose, onStartScraping }: ModalScrapingProps) {
  const [tab, setTab] = useState<"auto" | "manual">("manual");
  const [skipExisting, setSkipExisting] = useState<boolean>(true);
  const [startDate, setStartDate] = useState("2026-10-20");
  const [endDate, setEndDate] = useState("2026-10-22");

  if (!isOpen) return null;

  const handleSubmit = () => {
    onStartScraping(tab, skipExisting, startDate, endDate);
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
              Otomatis: kemarin (5 Nov)
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
          )}

          {/* Info Banner */}
          <div className="info-banner-green">
            <CheckCircle2 size={16} className="text-emerald-700" strokeWidth={2.2} />
            <span>
              {tab === "auto"
                ? "1 tanggal siap dievaluasi (5 Nov 2026)"
                : "3 tanggal belum punya data (20 s.d 22 Okt 2026)"}
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
              Perkiraan waktu sekitar 15 menit (5 menit per hari). Disarankan maksimal 7 hari, batas 31 hari.
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
            <span>Mulai Scraping ({tab === "auto" ? "1 hari" : "3 hari baru"})</span>
          </button>
        </div>
      </div>
    </div>
  );
}
