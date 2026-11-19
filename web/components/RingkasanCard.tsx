"use client";

import React from "react";
import { Shield, Info } from "lucide-react";

interface RingkasanCardProps {
  isRunning: boolean;
  dateStr?: string;
  count?: number;
  posCount?: number;
  netCount?: number;
  negCount?: number;
  lastUpdatedLabel?: string;
  noiseDibuangPct?: number | null;
  toneCadanganPct?: number | null;
  perluReviewCount?: number | null;
  noSpokespersonCount?: number | null;
  onViewNews?: (tone?: string) => void;
}

export default function RingkasanCard({
  isRunning,
  dateStr = "—",
  count = 0,
  posCount = 0,
  netCount = 0,
  negCount = 0,
  lastUpdatedLabel = "—",
  noiseDibuangPct = null,
  toneCadanganPct = null,
  perluReviewCount = null,
  noSpokespersonCount = null,
  onViewNews,
}: RingkasanCardProps) {
  const tot = posCount + netCount + negCount;
  const pctPos = tot > 0 ? Math.round((posCount / tot) * 100) : 0;
  const pctNet = tot > 0 ? Math.round((netCount / tot) * 100) : 0;
  const pctNeg = tot > 0 ? Math.max(0, 100 - pctPos - pctNet) : 0;

  const reviewBarPct =
    perluReviewCount != null && count > 0
      ? Math.min(100, Math.round((perluReviewCount / count) * 100))
      : 0;
  const noSpBarPct =
    noSpokespersonCount != null && count > 0
      ? Math.min(100, Math.round((noSpokespersonCount / count) * 100))
      : 0;

  return (
    <>
      {/* 1. Ringkasan Hari Ini (Panel Primer) */}
      <div className="card-box card-ringkasan panel-primary">
        <div className="card-header-row">
          <h3 className="card-title">Ringkasan Berita {dateStr}</h3>
          {onViewNews && count > 0 && (
            <button
              type="button"
              onClick={() => onViewNews()}
              className="btn-link-action"
              title="Lihat seluruh berita tanggal ini di Arsip Berita"
            >
              Lihat di Berita →
            </button>
          )}
        </div>

        {isRunning && (
          <div className="banner-running-notice">
            <Info size={13} className="text-amber-800" strokeWidth={2} />
            <span>Run baru sedang berjalan. Angka di bawah dari run {lastUpdatedLabel}.</span>
          </div>
        )}

        <div className={`metric-headline ${isRunning ? "opacity-60" : ""}`}>
          <span className="big-num">{count.toLocaleString("id-ID")}</span>
          <span className="unit-label">berita terpantau</span>
        </div>

        {/* Tone Bar Container */}
        <div className="tone-bar-large-track">
          <div className="tone-large-seg seg-pos" style={{ width: `${pctPos}%` }} />
          <div className="tone-large-seg seg-net" style={{ width: `${pctNet}%` }} />
          <div className="tone-large-seg seg-neg" style={{ width: `${pctNeg}%` }} />
        </div>

        {/* Tone Legend Row */}
        <div className="tone-legend-large">
          <button
            type="button"
            onClick={() => onViewNews?.("Positif")}
            className="tone-leg-item text-pos hover:opacity-80 transition-opacity"
            title="Klik untuk memfilter berita Positif di tab Berita"
          >
            <span className="dot dot-pos" />
            <span>Pos {posCount} ({pctPos}%)</span>
          </button>
          <button
            type="button"
            onClick={() => onViewNews?.("Netral")}
            className="tone-leg-item text-net hover:opacity-80 transition-opacity"
            title="Klik untuk memfilter berita Netral di tab Berita"
          >
            <span className="dot dot-net" />
            <span>Net {netCount} ({pctNet}%)</span>
          </button>
          <button
            type="button"
            onClick={() => onViewNews?.("Negatif")}
            className="tone-leg-item text-neg hover:opacity-80 transition-opacity"
            title="Klik untuk memfilter berita Negatif di tab Berita"
          >
            <span className="dot dot-neg" />
            <span>Neg {negCount} ({pctNeg}%)</span>
          </button>
        </div>
      </div>

      {/* 2. Kualitas Data (Panel Sekunder) */}
      <div className="card-box card-kualitas-data panel-secondary">
        <div className="card-header-row">
          <h3 className="card-title">Kualitas Data</h3>
          <Shield size={14} strokeWidth={2} />
        </div>

        <div className="kpi-rows-group">
          <div className="kpi-item">
            <div className="kpi-label-row">
              <span className="kpi-label">Noise domain dibuang</span>
              <span className="kpi-val">
                {noiseDibuangPct != null ? `${noiseDibuangPct}%` : "—"}
              </span>
            </div>
            <div className="kpi-progress-track">
              <div
                className="kpi-progress-fill bg-blue"
                style={{ width: `${noiseDibuangPct ?? 0}%` }}
              />
            </div>
          </div>

          <div className="kpi-item">
            <div className="kpi-label-row">
              <span className="kpi-label">Tone cadangan aturan</span>
              <span className="kpi-val">
                {toneCadanganPct != null ? `${toneCadanganPct}%` : "—"}
              </span>
            </div>
            <div className="kpi-progress-track">
              <div
                className="kpi-progress-fill bg-blue"
                style={{ width: `${toneCadanganPct ?? 0}%` }}
              />
            </div>
          </div>

          <div className="kpi-item">
            <div className="kpi-label-row">
              <span className="kpi-label">Perlu review manual</span>
              <span className="kpi-val">
                {perluReviewCount != null ? `${perluReviewCount} berita` : "—"}
              </span>
            </div>
            <div className="kpi-progress-track">
              <div
                className="kpi-progress-fill bg-red"
                style={{ width: `${reviewBarPct}%` }}
              />
            </div>
          </div>

          <div className="kpi-item">
            <div className="kpi-label-row">
              <span className="kpi-label">Tanpa spokesperson</span>
              <span className="kpi-val">
                {noSpokespersonCount != null ? `${noSpokespersonCount} berita` : "—"}
              </span>
            </div>
            <div className="kpi-progress-track">
              <div
                className="kpi-progress-fill bg-muted"
                style={{ width: `${noSpBarPct}%` }}
              />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
