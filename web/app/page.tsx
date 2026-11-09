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
import { SummaryData } from "@/lib/types";

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState("overview");
  const [isRunning, setIsRunning] = useState(false);
  const [isScrapeModalOpen, setIsScrapeModalOpen] = useState(false);
  const [isDownloadModalOpen, setIsDownloadModalOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState("2026-11-05");

  // State data
  const [summaryData, setSummaryData] = useState<SummaryData | null>(null);

  // Muat data awal dari public/data/summary.json
  useEffect(() => {
    fetch("/data/summary.json")
      .then((res) => res.json())
      .then((data: SummaryData) => {
        setSummaryData(data);
      })
      .catch((err) => {
        console.warn("Gagal memuat summary.json statis:", err);
      });
  }, []);

  const handleStartScraping = async (
    mode: "auto" | "manual",
    skipExisting: boolean,
    startDate?: string,
    endDate?: string
  ) => {
    setIsRunning(true);
    try {
      await fetch("/api/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, skipExisting, startDate, endDate }),
      });
    } catch {
      // Abaikan jika route belum aktif di cloud
    }
  };

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
                lastUpdatedStr="6 Nov, 07.12 WIB"
                targetDateStr="5 Nov 2026"
                runCountStr="148 berita"
                totalArchiveStr="4.127 berita"
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
                dateStr="5 Nov 2026"
                count={148}
                posCount={68}
                netCount={79}
                negCount={1}
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
      />

      <ModalUnduh
        isOpen={isDownloadModalOpen}
        onClose={() => setIsDownloadModalOpen(false)}
      />
    </div>
  );
}
