"use client";

import React from "react";
import { CheckCircle2, Download, Play, RefreshCw, X } from "lucide-react";

interface DataStatusBarProps {
  isRunning: boolean;
  onOpenScrapeModal: () => void;
  onOpenDownloadModal: () => void;
  onCancelScraping?: () => void;
  runningStepLabel?: string | null;
  lastUpdatedStr?: string;
  targetDateStr?: string;
  runCountStr?: string;
  totalArchiveStr?: string;
}

export default function DataStatusBar({
  isRunning,
  onOpenScrapeModal,
  onOpenDownloadModal,
  onCancelScraping,
  runningStepLabel,
  lastUpdatedStr = "6 Nov, 07.12 WIB",
  targetDateStr = "5 Nov 2026",
  runCountStr = "158 berita",
  totalArchiveStr = "4.127 berita",
}: DataStatusBarProps) {
  return (
    <div className={`data-status-bar panel-primary ${isRunning ? "running" : ""}`}>
      {/* 1. Status Indicator & Info Utama */}
      <div className="status-meta-group">
        <div className="status-icon-bubble">
          {isRunning ? (
            <RefreshCw className="animate-spin text-amber-600" size={20} strokeWidth={2.5} />
          ) : (
            <CheckCircle2 className="text-emerald-600" size={20} strokeWidth={2} />
          )}
        </div>

        <div className="status-text-block">
          <div className="status-label">
            {isRunning ? "Status Pengambilan Data" : "Data terakhir diperbarui"}
          </div>
          <div className="status-value highlight">
            {isRunning
              ? runningStepLabel || "Sedang mengambil data (Tahap 5: 62%)"
              : lastUpdatedStr}
          </div>
        </div>

        <div className="status-vert-div desktop-only" />

        {/* 2. Grid Angka Run (Mobile: 2x2, Desktop: row) */}
        <div className="status-metrics-row">
          <div className="metric-item">
            <span className="metric-label">Berita tanggal</span>
            <span className="metric-val">{targetDateStr}</span>
          </div>

          <div className="metric-mini-div desktop-only" />

          <div className="metric-item">
            <span className="metric-label">Hasil run ini</span>
            <span className="metric-val">{isRunning ? "Sedang diproses" : runCountStr}</span>
          </div>

          <div className="metric-mini-div desktop-only" />

          <div className="metric-item">
            <span className="metric-label">Total arsip</span>
            <span className="metric-val">{totalArchiveStr}</span>
          </div>
        </div>
      </div>

      {/* 3. Tombol Aksi */}
      <div className="status-actions">
        <button
          type="button"
          onClick={onOpenDownloadModal}
          className="btn-status-action btn-white"
          title="Unduh Excel Ringkasan"
        >
          <Download size={14} strokeWidth={2} />
          <span>Unduh Excel</span>
        </button>

        {isRunning ? (
          <button
            type="button"
            onClick={onCancelScraping}
            className="btn-status-action btn-danger"
            title="Batalkan Proses"
          >
            <X size={14} strokeWidth={2.5} />
            <span>Batalkan</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={onOpenScrapeModal}
            className="btn-status-action btn-yellow"
            title="Mulai Proses Scraping Berita"
          >
            <Play size={14} strokeWidth={2.2} fill="currentColor" />
            <span>Jalankan Scraping</span>
          </button>
        )}
      </div>

      {/* Progress line if running */}
      {isRunning && <div className="status-bar-bottom-loader" />}
    </div>
  );
}
