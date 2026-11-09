"use client";

import React, { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import BottomNav from "@/components/BottomNav";
import DataStatusBar from "@/components/DataStatusBar";
import PipelineVisualizer from "@/components/PipelineVisualizer";
import UnduhHarianCard from "@/components/UnduhHarianCard";
import RiwayatRunCard from "@/components/RiwayatRunCard";
import RingkasanCard from "@/components/RingkasanCard";
import KalenderKompakCard from "@/components/KalenderKompakCard";
import ModalScraping from "@/components/ModalScraping";
import ModalUnduh from "@/components/ModalUnduh";
import HalamanBerita from "@/components/HalamanBerita";
import HalamanRiwayatRun from "@/components/HalamanRiwayatRun";
import HalamanUnduhData from "@/components/HalamanUnduhData";
import { SummaryData, RunHistoryItem } from "@/lib/types";

const MONTHS_SHORT_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"];

function formatShortDateId(iso?: string, fallback = "5 Nov 2026"): string {
  if (!iso) return fallback;
  const parts = iso.slice(0, 10).split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return fallback;
  const [y, m, d] = parts;
  return `${d} ${MONTHS_SHORT_ID[m - 1] || ""} ${y}`;
}

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState("overview");
  const [isRunning, setIsRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [runningStepLabel, setRunningStepLabel] = useState<string | null>(null);
  const [isScrapeModalOpen, setIsScrapeModalOpen] = useState(false);
  const [isDownloadModalOpen, setIsDownloadModalOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState("2026-11-05");

  // State data
  const [summaryData, setSummaryData] = useState<SummaryData | null>(null);
  const [latestRun, setLatestRun] = useState<RunHistoryItem | null>(null);

  const loadSummary = () => {
    fetch(`/data/summary.json?t=${Date.now()}`, { cache: "no-store" })
      .then((res) => res.json())
      .then((data: SummaryData) => {
        setSummaryData(data);
      })
      .catch((err) => {
        console.warn("Gagal memuat summary.json statis:", err);
      });

    fetch(`/data/runs.json?t=${Date.now()}`, { cache: "no-store" })
      .then((res) => res.json())
      .then((data: RunHistoryItem[]) => {
        if (Array.isArray(data) && data.length > 0) {
          setLatestRun(data[0]);
        }
      })
      .catch(() => {});
  };

  // Muat data awal dari public/data/summary.json
  useEffect(() => {
    loadSummary();
  }, []);

  // Polling status GitHub Actions dari /api/status
  useEffect(() => {
    let cancelled = false;
    let wasRunning = isRunning;

    const checkStatus = async () => {
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled || !data.ok) return;

        const nowRunning = Boolean(data.isRunning);
        setIsRunning(nowRunning);
        setActiveRunId(data.activeRun?.id ?? null);
        setRunningStepLabel(
          data.activeRun?.currentStepName
            ? `Sedang berjalan: ${data.activeRun.currentStepName}`
            : null
        );

        if (wasRunning && !nowRunning) {
          loadSummary();
        }
        wasRunning = nowRunning;
      } catch {
        // Abaikan error jaringan sementara
      }
    };

    checkStatus();
    const intervalMs = isRunning ? 15000 : 45000;
    const timer = setInterval(checkStatus, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [isRunning]);

  const handleStartScraping = async (
    mode: "auto" | "manual",
    skipExisting: boolean,
    startDate?: string,
    endDate?: string
  ) => {
    setIsRunning(true);
    setRunningStepLabel("Memicu workflow di GitHub Actions...");
    try {
      const res = await fetch("/api/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, skipExisting, startDate, endDate }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        setIsRunning(false);
        setRunningStepLabel(null);
      }
    } catch {
      // Biarkan state simulasi lokal bila offline
    }
  };

  const handleCancelScraping = async () => {
    if (activeRunId) {
      try {
        await fetch("/api/status", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "cancel", runId: activeRunId }),
        });
      } catch {
        // Abaikan jika gagal membatalkan
      }
    }
    setIsRunning(false);
    setActiveRunId(null);
    setRunningStepLabel(null);
  };

  const latestDay = summaryData?.recent_days?.[0];
  const targetDateStr = formatShortDateId(
    latestDay?.fileDate || summaryData?.metadata?.last_updated,
    "5 Nov 2026"
  );
  const lastUpdatedStr = latestRun?.waktu_display
    ? `${latestRun.waktu_display} WIB`
    : "6 Nov, 07.12 WIB";
  const latestCount = latestDay?.count ?? 148;
  const runCountStr = `${latestCount.toLocaleString("id-ID")} berita`;
  const totalArchiveStr = `${(summaryData?.metadata?.total_articles ?? 4127).toLocaleString("id-ID")} berita`;

  return (
    <div className="dashboard-outer">
      <div className={`dashboard-grid ${activeTab !== "overview" ? "single-content-grid" : ""}`}>
        {/* Kolom 1: Sidebar Kiri (Desktop) */}
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

        {/* Tampilan Tab Overview */}
        {activeTab === "overview" && (
          <>
            <main className="center-column">
              {/* Bar Status Data */}
              <DataStatusBar
                isRunning={isRunning}
                onOpenScrapeModal={() => setIsScrapeModalOpen(true)}
                onOpenDownloadModal={() => setIsDownloadModalOpen(true)}
                onCancelScraping={handleCancelScraping}
                runningStepLabel={runningStepLabel}
                lastUpdatedStr={lastUpdatedStr}
                targetDateStr={targetDateStr}
                runCountStr={runCountStr}
                totalArchiveStr={totalArchiveStr}
              />

              {/* Hero Visual Pipeline 8 Tahap */}
              <PipelineVisualizer isRunning={isRunning} />

              {/* Baris Dua Kartu Bawah: Unduh Harian & Riwayat Run */}
              <div className="bottom-cards-row">
                <UnduhHarianCard onOpenDownloadModal={() => setIsDownloadModalOpen(true)} />
                <RiwayatRunCard
                  isRunning={isRunning}
                  onViewAll={() => setActiveTab("riwayat")}
                />
              </div>
            </main>

            {/* Kolom 3: Panel Kanan */}
            <aside className="right-column">
              <RingkasanCard
                isRunning={isRunning}
                dateStr={targetDateStr}
                count={latestCount}
                posCount={latestDay?.pos ?? 68}
                netCount={latestDay?.net ?? 79}
                negCount={latestDay?.neg ?? 1}
                lastUpdatedLabel={latestRun?.waktu_display || "06 Nov, 07.12"}
              />

              <KalenderKompakCard
                onSelectDate={(date) => setSelectedDate(date)}
                onViewNewsTab={() => setActiveTab("berita")}
              />
            </aside>
          </>
        )}

        {/* Tampilan Tab Berita */}
        {activeTab === "berita" && (
          <HalamanBerita summaryData={summaryData} />
        )}

        {/* Tampilan Tab Riwayat Run Lengkap */}
        {activeTab === "riwayat" && (
          <HalamanRiwayatRun isRunning={isRunning} />
        )}

        {/* Tampilan Tab Unduh Data Lengkap */}
        {activeTab === "unduh" && (
          <HalamanUnduhData onOpenDownloadModal={() => setIsDownloadModalOpen(true)} />
        )}
      </div>

      {/* Bilah Navigasi Bawah (Fixed Bottom Nav di Mobile/Tablet) */}
      <BottomNav activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* Modals */}
      <ModalScraping
        isOpen={isScrapeModalOpen}
        onClose={() => setIsScrapeModalOpen(false)}
        onStartScraping={handleStartScraping}
        calendarCounts={summaryData?.metadata?.calendar_counts}
      />

      <ModalUnduh
        isOpen={isDownloadModalOpen}
        onClose={() => setIsDownloadModalOpen(false)}
      />
    </div>
  );
}
