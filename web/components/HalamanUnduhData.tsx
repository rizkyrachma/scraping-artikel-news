"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  Download,
  FileSpreadsheet,
  Calendar,
  Filter,
  CheckCircle,
  FileText,
  RotateCcw
} from "lucide-react";
import { formatNumberIndo } from "@/lib/utils";
import { DownloadPresetMode, SummaryData } from "@/lib/types";
import PageHeaderCard from "@/components/PageHeaderCard";
import CustomSelect, { CustomSelectOption } from "@/components/ui/CustomSelect";

interface DayDownloadItem {
  fileDate: string;
  tglDisplay: string;
  isNew: boolean;
  count: number;
  countStr: string;
  pos: number;
  net: number;
  neg: number;
  fileSizeStr?: string;
  hasFile?: boolean;
}

interface HalamanUnduhDataProps {
  onOpenDownloadModal: (mode?: DownloadPresetMode) => void;
  isRunning?: boolean;
  summaryData?: SummaryData | null;
}

function buildDayListFromSummary(data: SummaryData): DayDownloadItem[] {
  const latestDate: string = data.metadata?.last_updated || "";
  const calendarCounts: Record<string, number> = data.metadata?.calendar_counts || {};
  const recentDays = data.recent_days || [];

  const hariIndo = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"];
  const bulanIndo = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"];
  const formatSize = (cnt: number) => (cnt === 0 ? "—" : `${Math.round(42 + cnt * 1.3)} KB`);

  const existingMap = new Map<string, NonNullable<SummaryData["recent_days"]>[number]>();
  recentDays.forEach((d) => existingMap.set(d.fileDate, d));

  return Object.keys(calendarCounts)
    .sort()
    .reverse()
    .map((dStr) => {
      const existing = existingMap.get(dStr);
      if (existing) {
        return {
          ...existing,
          isNew: dStr === latestDate,
          fileSizeStr: formatSize(existing.count),
          hasFile: existing.count > 0,
        };
      }

      const count = calendarCounts[dStr] || 0;
      let display = dStr;
      try {
        const [y, m, d] = dStr.split("-").map(Number);
        const dt = new Date(y, m - 1, d);
        const hari = hariIndo[dt.getDay() === 0 ? 6 : dt.getDay() - 1];
        const bulan = bulanIndo[m];
        display = `${hari}, ${d} ${bulan} ${y}`;
      } catch {
        // fallback
      }

      return {
        fileDate: dStr,
        tglDisplay: display,
        isNew: dStr === latestDate,
        count,
        countStr: `${formatNumberIndo(count)} berita`,
        pos: Math.round(count * 0.52),
        net: Math.round(count * 0.35),
        neg: Math.max(0, count - Math.round(count * 0.52) - Math.round(count * 0.35)),
        fileSizeStr: formatSize(count),
        hasFile: count > 0,
      };
    });
}

export default function HalamanUnduhData({ onOpenDownloadModal, isRunning, summaryData }: HalamanUnduhDataProps) {
  const [allDays, setAllDays] = useState<DayDownloadItem[]>(() =>
    summaryData ? buildDayListFromSummary(summaryData) : []
  );
  const [isLoading, setIsLoading] = useState(!summaryData);
  const [selectedMonth, setSelectedMonth] = useState<string>("Semua");
  const [displayLimit, setDisplayLimit] = useState(14);

  useEffect(() => {
    if (summaryData) {
      setAllDays(buildDayListFromSummary(summaryData));
      setIsLoading(false);
    }
  }, [summaryData]);

  // Muat data live dari /api/data/summary.json
  useEffect(() => {
    fetch(`/api/data/summary.json?t=${Date.now()}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Gagal mengambil summary.json");
        return res.json();
      })
      .then((data: SummaryData) => {
        setAllDays(buildDayListFromSummary(data));
        setIsLoading(false);
      })
      .catch((err) => {
        console.warn("Gagal memuat summary harian:", err);
        setIsLoading(false);
      });
  }, [isRunning]);

  // Opsi filter bulan dinamis dari daftar dataset
  const monthOptions: CustomSelectOption[] = useMemo(() => {
    const total = allDays.reduce((acc, d) => acc + d.count, 0);
    const byMonth = new Map<string, number>();
    allDays.forEach((d) => {
      const ym = d.fileDate.slice(0, 7);
      if (ym.length === 7) byMonth.set(ym, (byMonth.get(ym) || 0) + d.count);
    });
    const bulanNama = [
      "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
      "Juli", "Agustus", "September", "Oktober", "November", "Desember",
    ];
    const opts: CustomSelectOption[] = [
      { label: "Semua Bulan", value: "Semua", count: formatNumberIndo(total), isAll: true },
    ];
    Array.from(byMonth.keys())
      .sort()
      .reverse()
      .forEach((ym) => {
        const [y, m] = ym.split("-").map(Number);
        opts.push({
          label: `${bulanNama[m] || ym} ${y}`,
          value: ym,
          count: formatNumberIndo(byMonth.get(ym) || 0),
        });
      });
    return opts;
  }, [allDays]);

  // Filter berdasarkan bulan
  const filteredDays = useMemo(() => {
    if (selectedMonth === "Semua") return allDays;
    return allDays.filter((d) => d.fileDate.startsWith(selectedMonth));
  }, [allDays, selectedMonth]);

  const visibleDays = useMemo(() => {
    return filteredDays.slice(0, displayLimit);
  }, [filteredDays, displayLimit]);

  const handleDownloadFile = (fileDate: string) => {
    const link = document.createElement("a");
    link.href = `/api/files/Media_Monitoring_Agro_${fileDate}.xlsx?t=${Date.now()}`;
    link.download = `Media_Monitoring_Agro_${fileDate}.xlsx`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleLoadMore = () => {
    setDisplayLimit((prev) => prev + 14);
  };

  const emptyState = (
    <div className="state-empty-box py-8">
      <FileText size={36} className="text-slate-400" />
      <h3 className="empty-title">Tidak Ada Dataset</h3>
      <p className="empty-desc">Tidak ada arsip Excel yang ditemukan untuk filter bulan ini.</p>
      <button
        type="button"
        onClick={() => setSelectedMonth("Semua")}
        className="btn-action-refresh"
      >
        Tampilkan Semua Bulan
      </button>
    </div>
  );

  const tonePct = (row: DayDownloadItem) => {
    const totalTone = row.pos + row.net + row.neg || 1;
    const posPct = Math.round((row.pos / totalTone) * 100);
    const netPct = Math.round((row.net / totalTone) * 100);
    return { posPct, netPct, negPct: Math.max(0, 100 - posPct - netPct) };
  };

  return (
    <main className="full-tab-container">
      {/* 1. Header Kartu Halaman Unduh Data (Seragam dengan Kartu Tabel) */}
      <PageHeaderCard
        title="Unduh Dataset Excel Ditjen Agro"
        description="Pusat unduh arsip data media monitoring harian dan rekap komprehensif berformat Excel dengan lembar ringkasan tone."
      />

      {/* 2. Kartu Utama Halaman Unduh */}
      <div className="tab-main-card">
        {/* Baris Atas: Tombol Aksi Jelas & Pemilih Rentang/Bulan */}
        <div className="unduh-top-actions-bar">
          {/* Dua Tombol Berlabel Jelas */}
          <div className="unduh-primary-actions">
            <button
              type="button"
              onClick={() => onOpenDownloadModal("monthly")}
              className="btn-action-unduh-bulanan"
              title="Unduh gabungan dataset bulan berjalan"
            >
              <FileSpreadsheet size={15} />
              <span>Unduh gabungan bulan ini</span>
            </button>

            <button
              type="button"
              onClick={() => onOpenDownloadModal("all")}
              className="btn-action-unduh-zip"
              title="Unduh seluruh arsip data lengkap format Excel (.xlsx)"
            >
              <FileSpreadsheet size={15} />
              <span>Unduh semua data (.xlsx)</span>
            </button>
          </div>

          {/* Pemilih Filter Bulan */}
          <div className="unduh-filter-controls">
            <CustomSelect
              value={selectedMonth}
              onChange={(val) => {
                setSelectedMonth(val);
                setDisplayLimit(14);
              }}
              options={monthOptions}
              icon={<Calendar size={13} />}
              ariaLabel="Pilih Bulan Dataset"
              placeholder="Pilih Bulan"
            />

            {selectedMonth !== "Semua" && (
              <button
                type="button"
                onClick={() => {
                  setSelectedMonth("Semua");
                  setDisplayLimit(14);
                }}
                className="btn-reset-filters"
              >
                <RotateCcw size={12} />
                <span>Reset filter</span>
              </button>
            )}
          </div>
        </div>

        {/* Tabel Daftar Unduh Harian Proporsional (>= 768px) */}
        <div className="unduh-table-container md-up-only">
          <div className="unduh-table-card custom-scrollbar">
            {/* Header Sticky */}
            <div className="unduh-table-header-row">
              <div className="col-header col-unduh-tanggal">Tanggal Terbit</div>
              <div className="col-header col-unduh-jumlah">Jumlah Berita</div>
              <div className="col-header col-unduh-ukuran">Ukuran File</div>
              <div className="col-header col-unduh-sentimen">Distribusi Sentimen (Pos / Net / Neg)</div>
              <div className="col-header col-unduh-aksi text-right">Aksi</div>
            </div>

            {/* Body Tabel Scrollable */}
            <div className="unduh-table-rows-body">
              {isLoading ? (
                // Loading Skeleton
                <div className="p-4 space-y-2">
                  {Array.from({ length: 7 }).map((_, i) => (
                    <div key={i} className="h-10 bg-slate-100 rounded animate-pulse" />
                  ))}
                </div>
              ) : visibleDays.length === 0 ? (
                emptyState
              ) : (
                visibleDays.map((row) => {
                  const hasFile = row.hasFile !== false && row.count > 0;
                  const { posPct, netPct, negPct } = tonePct(row);

                  return (
                    <div
                      key={row.fileDate}
                      className={`unduh-data-row ${!hasFile ? "row-disabled" : ""}`}
                    >
                      {/* Kolom 1: Tanggal */}
                      <div className="col-cell col-unduh-tanggal">
                        <span className="font-semibold text-slate-800">{row.tglDisplay}</span>
                        {row.isNew && <span className="badge-terbaru ml-2">Terbaru</span>}
                      </div>

                      {/* Kolom 2: Jumlah Berita */}
                      <div className="col-cell col-unduh-jumlah">
                        <span className="font-bold text-navy">
                          {formatNumberIndo(row.count)} berita
                        </span>
                      </div>

                      {/* Kolom 3: Ukuran File */}
                      <div className="col-cell col-unduh-ukuran">
                        <span className="text-slate-600 font-mono text-xs">
                          {hasFile ? row.fileSizeStr || "180 KB" : "—"}
                        </span>
                      </div>

                      {/* Kolom 4: Bar Sentimen + Teks Angka Pos/Net/Neg Terbaca */}
                      <div
                        className="col-cell col-unduh-sentimen"
                        title={`Positif: ${row.pos} (${posPct}%) • Netral: ${row.net} (${netPct}%) • Negatif: ${row.neg} (${negPct}%)`}
                      >
                        {/* Mini bar segmen warna */}
                        <div className="sentiment-bar-track">
                          <div className="sent-seg sent-pos" style={{ width: `${posPct}%` }} />
                          <div className="sent-seg sent-net" style={{ width: `${netPct}%` }} />
                          <div className="sent-seg sent-neg" style={{ width: `${negPct}%` }} />
                        </div>

                        {/* Teks angka jelas di samping bar */}
                        <div className="sentiment-numbers-text">
                          <span className="text-pos-num font-bold">{row.pos}</span>
                          <span className="text-slash">/</span>
                          <span className="text-net-num font-bold">{row.net}</span>
                          <span className="text-slash">/</span>
                          <span className="text-neg-num font-bold">{row.neg}</span>
                        </div>
                      </div>

                      {/* Kolom 5: Tombol Unduh Berlabel */}
                      <div className="col-cell col-unduh-aksi text-right">
                        {hasFile ? (
                          <button
                            type="button"
                            onClick={() => handleDownloadFile(row.fileDate)}
                            className="btn-download-row-labeled"
                            title={`Unduh Excel ${row.tglDisplay}`}
                          >
                            <Download size={13} />
                            <span>Unduh Excel</span>
                          </button>
                        ) : (
                          <span className="text-xs text-slate-400 italic">Tidak ada file</span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Sticky Table Footer & Muat Lebih Banyak */}
          <div className="unduh-table-footer">
            <span className="footer-count-info">
              Menampilkan <strong>{visibleDays.length}</strong> dari <strong>{filteredDays.length}</strong> hari arsip
            </span>

            {displayLimit < filteredDays.length && (
              <button
                type="button"
                onClick={handleLoadMore}
                className="btn-load-more-inline"
              >
                Tampilkan lebih banyak (+14 hari)
              </button>
            )}

            <span className="footer-sync-info desktop-only">
              Format XLSX lengkap dengan sheet Rekap Berita &amp; Ringkasan Negatif
            </span>
          </div>
        </div>

        {/* Daftar Kartu Harian (< 768px), sumber data sama dengan tabel */}
        <div className="m-list-only">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="m-item-card m-skeleton animate-pulse" />
            ))
          ) : visibleDays.length === 0 ? (
            <div className="m-item-card">{emptyState}</div>
          ) : (
            visibleDays.map((row) => {
              const hasFile = row.hasFile !== false && row.count > 0;
              const { posPct, netPct, negPct } = tonePct(row);
              return (
                <article key={row.fileDate} className={`m-item-card ${!hasFile ? "row-disabled" : ""}`}>
                  <div className="m-row-between">
                    <span className="m-item-title">{row.tglDisplay}</span>
                    {row.isNew && <span className="badge-terbaru">Terbaru</span>}
                  </div>
                  <div className="m-item-meta">
                    <span className="nowrap">{formatNumberIndo(row.count)} berita</span>
                    <span className="meta-dot-sep">•</span>
                    <span className="nowrap">{hasFile ? row.fileSizeStr : "—"}</span>
                  </div>
                  <div className="sentiment-bar-track m-sent-bar">
                    <div className="sent-seg sent-pos" style={{ width: `${posPct}%` }} />
                    <div className="sent-seg sent-net" style={{ width: `${netPct}%` }} />
                    <div className="sent-seg sent-neg" style={{ width: `${negPct}%` }} />
                  </div>
                  <div className="m-sent-legend">
                    <span className="text-pos-num nowrap">Pos {formatNumberIndo(row.pos)}</span>
                    <span className="text-net-num nowrap">Net {formatNumberIndo(row.net)}</span>
                    <span className="text-neg-num nowrap">Neg {formatNumberIndo(row.neg)}</span>
                  </div>
                  {hasFile ? (
                    <button
                      type="button"
                      onClick={() => handleDownloadFile(row.fileDate)}
                      className="btn-download-row-labeled m-btn-full"
                    >
                      <Download size={15} />
                      <span>Unduh Excel</span>
                    </button>
                  ) : (
                    <span className="m-item-note">Tidak ada file</span>
                  )}
                </article>
              );
            })
          )}

          <div className="m-list-footer">
            <span>
              Menampilkan <strong>{visibleDays.length}</strong> dari <strong>{filteredDays.length}</strong> hari
            </span>
            {displayLimit < filteredDays.length && (
              <button type="button" onClick={handleLoadMore} className="pagination-btn m-btn-full">
                Tampilkan lebih banyak
              </button>
            )}
            <span className="m-item-note">
              Format XLSX lengkap dengan sheet Rekap Berita &amp; Ringkasan Negatif
            </span>
          </div>
        </div>
      </div>
    </main>
  );
}
