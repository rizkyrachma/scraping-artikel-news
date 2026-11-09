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
}

export default function RingkasanCard({
  isRunning,
  dateStr = "5 Nov 2026",
  count = 158,
  posCount = 71,
  netCount = 80,
  negCount = 7,
  lastUpdatedLabel = "06 Nov, 07.12",
}: RingkasanCardProps) {
  const tot = posCount + netCount + negCount;
  const pctPos = tot > 0 ? Math.round((posCount / tot) * 100) : 0;
  const pctNet = tot > 0 ? Math.round((netCount / tot) * 100) : 0;
  const pctNeg = tot > 0 ? Math.max(0, 100 - pctPos - pctNet) : 0;

  return (
    <>
      {/* 1. Ringkasan Hari Ini (Panel Primer) */}
      <div className="card-box card-ringkasan panel-primary">
        <h3 className="card-title">Ringkasan Berita {dateStr}</h3>

        {isRunning && (
          <div className="banner-running-notice">
            <Info size={13} className="text-amber-800" strokeWidth={2} />
            <span>Run baru sedang berjalan. Angka di bawah dari run {lastUpdatedLabel}.</span>
          </div>
        )}

        <div className={`metric-headline ${isRunning ? "opacity-60" : ""}`}>
          <span className="big-num">{count}</span>
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
          <div className="tone-leg-item text-pos">
            <span className="dot dot-pos" />
            <span>Pos {posCount} ({pctPos}%)</span>
          </div>
          <div className="tone-leg-item text-net">
            <span className="dot dot-net" />
            <span>Net {netCount} ({pctNet}%)</span>
          </div>
          <div className="tone-leg-item text-neg">
            <span className="dot dot-neg" />
            <span>Neg {negCount} ({pctNeg}%)</span>
          </div>
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
              <span className="kpi-val">68%</span>
            </div>
            <div className="kpi-progress-track">
              <div className="kpi-progress-fill bg-blue" style={{ width: "68%" }} />
            </div>
          </div>

          <div className="kpi-item">
            <div className="kpi-label-row">
              <span className="kpi-label">Tone cadangan aturan</span>
              <span className="kpi-val">11%</span>
            </div>
            <div className="kpi-progress-track">
              <div className="kpi-progress-fill bg-blue" style={{ width: "11%" }} />
            </div>
          </div>

          <div className="kpi-item">
            <div className="kpi-label-row">
              <span className="kpi-label">Perlu review manual</span>
              <span className="kpi-val">8 berita</span>
            </div>
            <div className="kpi-progress-track">
              <div className="kpi-progress-fill bg-red" style={{ width: "14%" }} />
            </div>
          </div>

          <div className="kpi-item">
            <div className="kpi-label-row">
              <span className="kpi-label">Tanpa spokesperson</span>
              <span className="kpi-val">23 berita</span>
            </div>
            <div className="kpi-progress-track">
              <div className="kpi-progress-fill bg-muted" style={{ width: "24%" }} />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
