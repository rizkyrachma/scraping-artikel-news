"use client";

import React from "react";
import { GitBranch, Check, RefreshCw, Clock } from "lucide-react";

interface PipelineVisualizerProps {
  isRunning: boolean;
}

export default function PipelineVisualizer({ isRunning }: PipelineVisualizerProps) {
  const stages = isRunning
    ? [
        { num: 1, name: "Google Search", counts: "1.912 mentah", dur: "1m 48s", state: "done" },
        { num: 2, name: "Filter Domain", counts: "1.912 → 620", dur: "4s", state: "done" },
        { num: 3, name: "Filter Tanggal", counts: "620 → 218", dur: "1s", state: "done" },
        { num: 4, name: "Hapus Duplikat", counts: "218 → 170", dur: "2s", state: "done" },
        { num: 5, name: "Ambil Isi", counts: "105 dari 170", dur: "46s", state: "running", prog: "62%" },
        { num: 6, name: "Klasifikasi Tone", counts: "—", dur: "—", state: "waiting" },
        { num: 7, name: "Spokesperson", counts: "—", dur: "—", state: "waiting" },
        { num: 8, name: "Ekspor Excel", counts: "—", dur: "—", state: "waiting" },
      ]
    : [
        { num: 1, name: "Google Search", counts: "1.862 mentah", dur: "1m 52s", state: "done" },
        { num: 2, name: "Filter Domain", counts: "1.862 → 604", dur: "4s", state: "done" },
        { num: 3, name: "Filter Tanggal", counts: "604 → 212", dur: "1s", state: "done" },
        { num: 4, name: "Hapus Duplikat", counts: "212 → 164", dur: "2s", state: "done" },
        { num: 5, name: "Ambil Isi", counts: "164 → 148", dur: "1m 20s", state: "done" },
        { num: 6, name: "Klasifikasi Tone", counts: "148 berita", dur: "1m 08s", state: "done" },
        { num: 7, name: "Spokesperson", counts: "148 berita", dur: "6s", state: "done" },
        { num: 8, name: "Ekspor Excel", counts: "148 baris", dur: "3s", state: "done" },
      ];

  return (
    <div className="pipeline-card panel-primary">
      <div className="pipeline-header">
        <div className="pipeline-title-group">
          <GitBranch size={16} strokeWidth={2.2} />
          <span className="pipeline-title">
            Proses Pengambilan Data{isRunning ? " (Aktif)" : ""}
          </span>
        </div>
        <div className="pipeline-target-tag">
          {isRunning
            ? "Target: 5 Nov 2026 • Run #20261106-0945"
            : "Target: 5 Nov 2026 • Run #20261106-0712"}
        </div>
      </div>

      {/* Grid 8 Tahap (fleksibel minmax, 2 baris nama jika sempit) */}
      <div className="stage-cards-grid">
        {stages.map((st) => (
          <div key={st.num} className={`stage-card ${st.state}`}>
            <div className="stage-top">
              <span className="stage-num">#{st.num}</span>
              {st.prog && <span className="stage-chip-prog">{st.prog}</span>}
            </div>
            <div className="stage-name" title={st.name}>
              {st.name}
            </div>
            <div className="stage-count">{st.counts}</div>
            <div className="stage-footer">
              {st.state === "done" && (
                <Check size={12} className="text-emerald-600" strokeWidth={2.5} />
              )}
              {st.state === "running" && (
                <RefreshCw size={11} className="animate-spin text-amber-600" strokeWidth={2.5} />
              )}
              {st.state === "waiting" && (
                <Clock size={11} className="text-slate-400" strokeWidth={2} />
              )}
              <span className="stage-dur">{st.dur}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Funnel Bar Proporsional */}
      <div className="funnel-container">
        <div className="funnel-bar-track">
          <div className="funnel-seg seg-mentah" style={{ width: "45%" }} />
          <div className="funnel-seg seg-media" style={{ width: "27%" }} />
          <div className="funnel-seg seg-tanggal" style={{ width: "14%" }} />
          <div className="funnel-seg seg-unik" style={{ width: "9%" }} />
          <div
            className={`funnel-seg ${isRunning ? "seg-running" : "seg-final"}`}
            style={{ width: "5%" }}
          />
        </div>

        <div className="funnel-labels-row">
          <span>{isRunning ? "Mentah: 1.912" : "Mentah: 1.862"}</span>
          <span>{isRunning ? "Filter Media: 620" : "Filter Media: 604"}</span>
          <span>{isRunning ? "Filter Tgl: 218" : "Filter Tgl: 212"}</span>
          <span>{isRunning ? "Unik: 170" : "Unik: 164"}</span>
          <span className={`funnel-final-label ${isRunning ? "text-amber-700" : "text-emerald-700"}`}>
            {isRunning ? "Sedang Ambil Isi (62%)..." : "Final: 148 (7,9%)"}
          </span>
        </div>
      </div>
    </div>
  );
}
