"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
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

function formatShortDateId(iso?: string, fallback = "—"): string {
  if (!iso) return fallback;
  const parts = iso.slice(0, 10).split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return fallback;
  const [y, m, d] = parts;
  return `${d} ${MONTHS_SHORT_ID[m - 1] || ""} ${y}`;
}

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState("overview");
  const [isRunning, setIsRunning] = useState(false);
  const [activeRunInfo, setActiveRunInfo] = useState<{ id: number; currentStepName?: string | null } | null>(null);
  const [runningStepLabel, setRunningStepLabel] = useState<string | null>(null);
  const [isScrapeModalOpen, setIsScrapeModalOpen] = useState(false);
  const [isDownloadModalOpen, setIsDownloadModalOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState("");

  // State data
  const [summaryData, setSummaryData] = useState<SummaryData | null>(null);
  const [runsList, setRunsList] = useState<RunHistoryItem[]>([]);

  // Mencegah polling /api/status membatalkan status running tepat setelah dispatch (race 1-3 detik di GitHub API)
  const dispatchGraceUntilRef = useRef<number>(0);
  const prevRunningRef = useRef<boolean>(false);

  const loadSummary = useCallback((selectLatest = false) => {
    fetch(`/api/data/summary.json?t=${Date.now()}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data: SummaryData) => {
        setSummaryData(data);
        const latestIso = data.recent_days?.[0]?.fileDate || data.metadata?.last_updated || "";
        if (latestIso) {
          setSelectedDate((prev) => (selectLatest || !prev ? latestIso : prev));
        }
      })
      .catch((err) => {
        console.warn("Gagal memuat summary.json:", err);
      });

    fetch(`/api/data/runs.json?t=${Date.now()}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data: RunHistoryItem[]) => {
        if (Array.isArray(data)) {
          setRunsList(data);
        }
      })
      .catch(() => {});
  }, []);

  // Muat data awal dari /api/data (sinkron dengan branch data GitHub / lokal)
  useEffect(() => {
    loadSummary(true);
  }, [loadSummary]);

  // Polling status GitHub Actions dari /api/status
  useEffect(() => {
    let cancelled = false;

    const checkStatus = async () => {
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled || !data.ok) return;

        const serverRunning = Boolean(data.isRunning);
        const inGrace = !serverRunning && Date.now() < dispatchGraceUntilRef.current;

        if (serverRunning) {
          dispatchGraceUntilRef.current = 0;
          setIsRunning(true);
          setActiveRunInfo(
            data.activeRun
              ? { id: data.activeRun.id, currentStepName: data.activeRun.currentStepName }
              : null
          );
          setRunningStepLabel(
            data.activeRun?.currentStepName
              ? `Sedang berjalan: ${data.activeRun.currentStepName}`
              : "Sedang berjalan: Menunggu runner GitHub Actions"
          );
          prevRunningRef.current = true;
        } else if (inGrace) {
          prevRunningRef.current = true;
        } else {
          const wasRunning = prevRunningRef.current;
          setIsRunning(false);
          setActiveRunInfo(null);
          setRunningStepLabel(null);
          prevRunningRef.current = false;
          if (wasRunning) {
            loadSummary(true);
          }
        }
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
  }, [isRunning, loadSummary]);

  const handleStartScraping = async (
    mode: "auto" | "manual",
    skipExisting: boolean,
    startDate?: string,
    endDate?: string
  ) => {
    dispatchGraceUntilRef.current = Date.now() + 12000;
    prevRunningRef.current = true;
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
        dispatchGraceUntilRef.current = 0;
        prevRunningRef.current = false;
        setIsRunning(false);
        setRunningStepLabel(null);
      }
    } catch {
      dispatchGraceUntilRef.current = 0;
      prevRunningRef.current = false;
      setIsRunning(false);
      setRunningStepLabel(null);
    }
  };

  const handleCancelScraping = async () => {
    if (activeRunInfo?.id) {
      try {
        await fetch("/api/status", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "cancel", runId: activeRunInfo.id }),
        });
      } catch {
        // Abaikan jika gagal membatalkan
      }
    }
    dispatchGraceUntilRef.current = 0;
    prevRunningRef.current = false;
    setIsRunning(false);
    setActiveRunInfo(null);
    setRunningStepLabel(null);
  };

  const latestRun = runsList[0] || null;
  const latestDay = summaryData?.recent_days?.[0];
  const latestDateIso = latestDay?.fileDate || summaryData?.metadata?.last_updated || "";
  const targetDateStr = formatShortDateId(latestDateIso, "—");
  const lastUpdatedStr = latestRun?.waktu_display
    ? `${latestRun.waktu_display} WIB`
    : summaryData
    ? formatShortDateId(latestDateIso, "—")
    : "Memuat...";
  const latestCount =
    latestDay?.count ??
    (latestDateIso ? summaryData?.metadata?.calendar_counts?.[latestDateIso] ?? 0 : 0);
  const runCountStr = summaryData ? `${latestCount.toLocaleString("id-ID")} berita` : "—";
  const totalArchiveStr = summaryData
    ? `${(summaryData.metadata?.total_articles ?? 0).toLocaleString("id-ID")} berita`
    : "—";

  const effectiveDate = selectedDate || latestDateIso;
  const selectedDay = summaryData?.recent_days?.find((d) => d.fileDate === effectiveDate);
  const ringkasanDateStr = formatShortDateId(effectiveDate, targetDateStr);
  const ringkasanCount =
    selectedDay?.count ??
    (effectiveDate ? summaryData?.metadata?.calendar_counts?.[effectiveDate] ?? 0 : 0);
  const ringkasanPos = selectedDay?.pos ?? 0;
  const ringkasanNet = selectedDay?.net ?? 0;
  const ringkasanNeg = selectedDay?.neg ?? 0;
  const isViewingLatest = !effectiveDate || effectiveDate === latestDateIso;
  const runStats = isViewingLatest ? latestRun?.stats : undefined;

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
              <PipelineVisualizer
                isRunning={isRunning}
                activeRun={activeRunInfo}
                latestRun={latestRun}
                targetDateStr={targetDateStr}
                latestCount={latestCount}
              />

              {/* Baris Dua Kartu Bawah: Unduh Harian & Riwayat Run */}
              <div className="bottom-cards-row">
                <UnduhHarianCard
                  onOpenDownloadModal={() => setIsDownloadModalOpen(true)}
                  recentDays={summaryData?.recent_days || []}
                />
                <RiwayatRunCard
                  isRunning={isRunning}
                  runs={runsList}
                  onViewAll={() => setActiveTab("riwayat")}
                />
              </div>
            </main>

            {/* Kolom 3: Panel Kanan */}
            <aside className="right-column">
              <RingkasanCard
                isRunning={isRunning}
                dateStr={ringkasanDateStr}
                count={ringkasanCount}
                posCount={ringkasanPos}
                netCount={ringkasanNet}
                negCount={ringkasanNeg}
                lastUpdatedLabel={latestRun?.waktu_display || "—"}
                noiseDibuangPct={runStats?.noise_dibuang_pct ?? null}
                toneCadanganPct={runStats?.tone_cadangan_pct ?? null}
                perluReviewCount={runStats?.perlu_review ?? null}
                noSpokespersonCount={runStats?.tanpa_spokesperson ?? null}
              />

              <KalenderKompakCard
                summaryData={summaryData}
                selectedDate={effectiveDate}
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
          <HalamanUnduhData
            onOpenDownloadModal={() => setIsDownloadModalOpen(true)}
            isRunning={isRunning}
            summaryData={summaryData}
          />
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
        summaryData={summaryData}
      />
    </div>
  );
}
