"use client";

import React from "react";
import { GitBranch, Check, RefreshCw, Clock } from "lucide-react";
import { RunHistoryItem } from "@/lib/types";

interface PipelineVisualizerProps {
  isRunning: boolean;
  activeRun?: { id: number; currentStepName?: string | null } | null;
  latestRun?: RunHistoryItem | null;
  targetDateStr?: string;
  latestCount?: number;
}

function fmtNum(n?: number | null): string {
  if (typeof n !== "number" || Number.isNaN(n)) return "—";
  return n.toLocaleString("id-ID");
}

export default function PipelineVisualizer({
  isRunning,
  activeRun,
  latestRun,
  targetDateStr = "—",
  latestCount = 0,
}: PipelineVisualizerProps) {
  const stats = latestRun?.stats;
  const stepLower = (activeRun?.currentStepName || "").toLowerCase();

  let activeStageNum = 1;
  if (stepLower.includes("sinkronisasi") || stepLower.includes("commit") || stepLower.includes("evaluasi")) {
    activeStageNum = 8;
  } else if (stepLower.includes("pipeline") || stepLower.includes("main.py")) {
    activeStageNum = 5;
  }

  const getRunningState = (num: number) => {
    if (num < activeStageNum) return "done";
    if (num === activeStageNum) return "running";
    return "waiting";
  };

  const stageNames = [
    "Google Search",
    "Filter Domain",
    "Filter Tanggal",
    "Hapus Duplikat",
    "Ambil Isi",
    "Klasifikasi Tone",
    "Spokesperson",
    "Ekspor Excel",
  ];

  const finalNum = stats?.final ?? latestRun?.hasil_berita ?? latestCount;
  const durLabel = latestRun?.durasi || "Selesai";

  const idleCounts = [
    stats?.mentah != null ? `${fmtNum(stats.mentah)} mentah` : "Selesai",
    stats?.filter_media != null
      ? `${fmtNum(stats.mentah)} → ${fmtNum(stats.filter_media)}`
      : stats?.mentah != null
      ? "Filter domain"
      : "Selesai",
    stats?.filter_tgl != null
      ? `${fmtNum(stats.filter_tgl)} lolos`
      : "Selesai",
    stats?.unik != null ? `${fmtNum(stats.unik)} unik` : "Selesai",
    stats?.unik != null ? `${fmtNum(stats.unik)} artikel` : `${fmtNum(finalNum)} berita`,
    `${fmtNum(finalNum)} berita`,
    `${fmtNum(finalNum)} berita`,
    `${fmtNum(finalNum)} baris`,
  ];

  const stages = stageNames.map((name, idx) => {
    const num = idx + 1;
    if (isRunning) {
      const state = getRunningState(num);
      return {
        num,
        name,
        counts: state === "done" ? "Selesai" : state === "running" ? "Berjalan" : "Menunggu",
        dur: state === "running" ? "Live" : "—",
        state,
        prog: undefined as string | undefined,
      };
    }
    return {
      num,
      name,
      counts: idleCounts[idx],
      dur: num === 8 ? durLabel : "✓",
      state: "done",
      prog: undefined as string | undefined,
    };
  });

  const targetTag = isRunning
    ? `GitHub Actions • Run #${activeRun?.id ?? "Aktif"}`
    : `Target: ${targetDateStr} • ${latestRun?.waktu_display || "—"}`;

  return (
    <div className="pipeline-card panel-primary">
      <div className="pipeline-header">
        <div className="pipeline-title-group">
          <GitBranch size={16} strokeWidth={2.2} />
          <span className="pipeline-title">
            Proses Pengambilan Data{isRunning ? " (Aktif)" : ""}
          </span>
        </div>
        <div className="pipeline-target-tag">{targetTag}</div>
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
          <div className="funnel-seg seg-mentah" style={{ width: isRunning ? "25%" : "45%" }} />
          <div className="funnel-seg seg-media" style={{ width: isRunning ? "20%" : "27%" }} />
          <div className="funnel-seg seg-tanggal" style={{ width: isRunning ? "15%" : "14%" }} />
          <div className="funnel-seg seg-unik" style={{ width: isRunning ? "15%" : "9%" }} />
          <div
            className={`funnel-seg ${isRunning ? "seg-running" : "seg-final"}`}
            style={{ width: isRunning ? "25%" : "5%" }}
          />
        </div>

        <div className="funnel-labels-row">
          {isRunning ? (
            <>
              <span>Tahap aktif: {activeRun?.currentStepName || "Menunggu runner GitHub Actions"}</span>
              <span className="funnel-final-label text-amber-700">Sedang berjalan...</span>
            </>
          ) : stats?.mentah ? (
            <>
              <span>Mentah: {fmtNum(stats.mentah)}</span>
              {stats.filter_media != null && <span>Filter Media: {fmtNum(stats.filter_media)}</span>}
              {stats.filter_tgl != null && <span>Filter Tgl: {fmtNum(stats.filter_tgl)}</span>}
              {stats.unik != null && <span>Unik: {fmtNum(stats.unik)}</span>}
              <span className="funnel-final-label text-emerald-700">
                Final: {fmtNum(finalNum)} ({stats.mentah > 0 ? `${((finalNum / stats.mentah) * 100).toFixed(1)}%` : "—"})
              </span>
            </>
          ) : (
            <>
              <span>Terakhir: {latestRun?.waktu_display || "—"}</span>
              <span>Durasi: {durLabel}</span>
              <span className="funnel-final-label text-emerald-700">
                Final: {fmtNum(finalNum)} berita
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
