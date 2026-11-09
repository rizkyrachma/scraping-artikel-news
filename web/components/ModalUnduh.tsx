"use client";

import React, { useState } from "react";
import { Download, X, Calendar, CheckCircle2 } from "lucide-react";

interface ModalUnduhProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function ModalUnduh({ isOpen, onClose }: ModalUnduhProps) {
  const [format, setFormat] = useState<"zip" | "merged">("zip");
  const [startDate, setStartDate] = useState("2026-11-01");
  const [endDate, setEndDate] = useState("2026-11-02");

  if (!isOpen) return null;

  const handleDownload = () => {
    const link = document.createElement("a");
    link.href = `/files/Media_Monitoring_Agro_Semua_Data.xlsx`;
    link.download = `Media_Monitoring_Agro_${startDate}_sd_${endDate}_ringkasan.xlsx`;
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
            <span className="modal-title">Unduh Excel Harian</span>
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
            <span>2 hari dipilih (1 sampai 2 Nov 2026), total 193 berita</span>
          </div>

          {/* Format Unduhan Radio */}
          <div className="radio-group-container">
            <div className="format-section-title">Format Unduhan:</div>

            <label className={`radio-card ${format === "zip" ? "active" : ""}`}>
              <input
                type="radio"
                name="downloadFormat"
                checked={format === "zip"}
                onChange={() => setFormat("zip")}
              />
              <div className="radio-text">
                <div className="radio-title">Satu file per hari (ZIP)</div>
                <div className="radio-desc">
                  Berisi file Excel harian lengkap dengan Sheet Berita & Sheet Ringkasan Negatif
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
                <div className="radio-title">Gabung jadi satu file Excel (dengan Ringkasan)</div>
                <div className="radio-desc">
                  Mencakup Sheet Berita dan Sheet Ringkasan Negatif (.xlsx)
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
            <span>{format === "zip" ? "Unduh ZIP (2 file)" : "Unduh Excel Gabungan"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
