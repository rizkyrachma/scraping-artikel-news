"use client";

import React from "react";
import { CheckCircle2, Download, Play, RefreshCw, X, AlertTriangle, AlertCircle, Info, ExternalLink } from "lucide-react";

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
  actionNotice?: {
    type: "info" | "warning" | "error" | "success";
    message: string;
    url?: string;
  } | null;
  onDismissNotice?: () => void;
}

export default function DataStatusBar({
  isRunning,
  onOpenScrapeModal,
  onOpenDownloadModal,
  onCancelScraping,
  runningStepLabel,
  lastUpdatedStr = "—",
  targetDateStr = "—",
  runCountStr = "—",
  totalArchiveStr = "—",
  actionNotice,
  onDismissNotice,
}: DataStatusBarProps) {
  return (
    <div className={`data-status-bar panel-primary ${isRunning ? "running" : ""}`}>
      {actionNotice && (
        <div className={`status-notice-banner notice-${actionNotice.type}`}>
          <div className="notice-content">
            {actionNotice.type === "error" && <AlertCircle size={16} className="notice-icon" />}
            {actionNotice.type === "warning" && <AlertTriangle size={16} className="notice-icon" />}
            {actionNotice.type === "success" && <CheckCircle2 size={16} className="notice-icon" />}
            {actionNotice.type === "info" && <Info size={16} className="notice-icon" />}
            <span className="notice-message">{actionNotice.message}</span>
            {actionNotice.url && (
              <a
                href={actionNotice.url}
                target="_blank"
                rel="noopener noreferrer"
                className="notice-link"
              >
                Log GitHub <ExternalLink size={12} />
              </a>
            )}
          </div>
          {onDismissNotice && (
            <button
              type="button"
              onClick={onDismissNotice}
              className="btn-notice-dismiss"
              aria-label="Tutup notifikasi"
            >
              <X size={14} />
            </button>
          )}
        </div>
      )}

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
              ? runningStepLabel || "Sedang berjalan: Menunggu runner GitHub Actions"
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
