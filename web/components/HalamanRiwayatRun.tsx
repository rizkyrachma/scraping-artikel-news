"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  CheckCircle,
  AlertCircle,
  RefreshCw,
  ExternalLink,
  History,
  Activity,
  CheckCheck,
  Clock
} from "lucide-react";
import PageHeaderCard from "@/components/PageHeaderCard";
import { RunHistoryItem } from "@/lib/types";
import { formatNumberIndo } from "@/lib/utils";

interface HalamanRiwayatRunProps {
  isRunning?: boolean;
}

export default function HalamanRiwayatRun({ isRunning }: HalamanRiwayatRunProps) {
  const [runs, setRuns] = useState<RunHistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<"Semua" | "Berhasil" | "Gagal">("Semua");
  const [searchDate, setSearchDate] = useState("");

  // Muat data live dari /api/data/runs.json setiap mount atau status isRunning berubah
  useEffect(() => {
    fetch(`/api/data/runs.json?t=${Date.now()}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Gagal mengambil runs.json");
        return res.json();
      })
      .then((data: RunHistoryItem[]) => {
        if (Array.isArray(data)) setRuns(data);
        setIsLoading(false);
      })
      .catch((err) => {
        console.warn("Gagal memuat runs.json:", err);
        setIsLoading(false);
      });
  }, [isRunning]);

  // Filter runs
  const filteredRuns = useMemo(() => {
    return runs.filter((r) => {
      if (statusFilter !== "Semua" && r.status !== statusFilter) {
        return false;
      }
      if (searchDate) {
        const q = searchDate.toLowerCase();
        const wMatch = r.waktu_display.toLowerCase().includes(q);
        const rMatch = r.rentang_data ? r.rentang_data.toLowerCase().includes(q) : false;
        if (!wMatch && !rMatch) return false;
      }
      return true;
    });
  }, [runs, statusFilter, searchDate]);

  // Statistik 4 kartu KPI di atas tabel
  const stats = useMemo(() => {
    const total = runs.length;
    const successCount = runs.filter((r) => r.status === "Berhasil").length;
    const rate = total > 0 ? Math.round((successCount / total) * 100) : 100;

    // Rata-rata durasi (parsing detik kasar)
    let totalSec = 0;
    let countedDur = 0;
    runs.forEach((r) => {
      if (r.durasi && r.durasi.includes("m")) {
        const m = parseInt(r.durasi.split("m")[0], 10) || 0;
        const s = parseInt(r.durasi.split("m")[1]?.replace("s", ""), 10) || 0;
        totalSec += m * 60 + s;
        countedDur += 1;
      }
    });
    const avgSec = countedDur > 0 ? Math.round(totalSec / countedDur) : 0;
    const avgDurStr = countedDur > 0 ? `${Math.floor(avgSec / 60)}m ${avgSec % 60}s` : "—";

    const lastRun = runs[0] || null;

    return {
      total,
      successCount,
      rate,
      avgDurStr,
      lastRun,
    };
  }, [runs]);

  const statusBadge = (status: RunHistoryItem["status"]) =>
    status === "Berhasil" ? (
      <span className="badge-status-selesai">
        <CheckCircle size={12} strokeWidth={2.5} />
        <span>Berhasil</span>
      </span>
    ) : status === "Berjalan" ? (
      <span className="badge-status-berjalan">
        <RefreshCw size={12} className="animate-spin" strokeWidth={2.5} />
        <span>Berjalan</span>
      </span>
    ) : (
      <span className="badge-status-gagal">
        <AlertCircle size={12} strokeWidth={2.5} />
        <span>Gagal</span>
      </span>
    );

  const emptyState = (
    <div className="state-empty-box py-8">
      <AlertCircle size={36} className="text-slate-400" />
      <h3 className="empty-title">Tidak Ada Catatan Run</h3>
      <p className="empty-desc">Tidak ada riwayat eksekusi dengan status &ldquo;{statusFilter}&rdquo;.</p>
      <button type="button" onClick={() => setStatusFilter("Semua")} className="btn-action-refresh">
        Tampilkan Semua Run
      </button>
    </div>
  );

  return (
    <main className="full-tab-container">
      {/* 1. Header Kartu Halaman Riwayat Run */}
      <PageHeaderCard
        title="Riwayat Eksekusi Pipeline"
        description="Catatan log eksekusi otomatisasi web scraping harian dan pemantauan status ingest data ke repositori."
      />

      {/* 2. Kartu Utama Halaman Riwayat */}
      <div className="tab-main-card">
        {/* 4 Kartu Metrik Ringkasan di Atas Tabel */}
        <div className="kpi-quad-grid">
          {/* Kartu 1: Total Run */}
          <div className="kpi-mini-card">
            <div className="kpi-mini-label">
              <History size={14} className="text-slate-500" />
              <span>Total Eksekusi</span>
            </div>
            <div className="kpi-mini-val-row">
              <span className="kpi-mini-val">{formatNumberIndo(stats.total)}</span>
              <span className="kpi-mini-sub">run tercatat</span>
            </div>
          </div>

          {/* Kartu 2: Tingkat Keberhasilan */}
          <div className="kpi-mini-card">
            <div className="kpi-mini-label">
              <CheckCheck size={14} className="text-emerald-600" />
              <span>Keberhasilan</span>
            </div>
            <div className="kpi-mini-val-row">
              <span className="kpi-mini-val text-emerald-700">{stats.rate}%</span>
              <span className="kpi-mini-sub">({stats.successCount}/{stats.total} sukses)</span>
            </div>
          </div>

          {/* Kartu 3: Rata-rata Durasi */}
          <div className="kpi-mini-card">
            <div className="kpi-mini-label">
              <Clock size={14} className="text-amber-600" />
              <span>Rata-rata Durasi</span>
            </div>
            <div className="kpi-mini-val-row">
              <span className="kpi-mini-val">{stats.avgDurStr}</span>
              <span className="kpi-mini-sub">per siklus</span>
            </div>
          </div>

          {/* Kartu 4: Run Terakhir */}
          <div className="kpi-mini-card">
            <div className="kpi-mini-label">
              <Activity size={14} className="text-blue-600" />
              <span>Run Terakhir</span>
            </div>
            <div className="kpi-mini-val-row">
              <span className="kpi-mini-val text-sm font-bold">
                {stats.lastRun?.waktu_display ? (
                  <>
                    {stats.lastRun.waktu_display} <span className="kpi-wib">WIB</span>
                  </>
                ) : (
                  "—"
                )}
              </span>
              {stats.lastRun ? (
                statusBadge(isRunning ? "Berjalan" : stats.lastRun.status)
              ) : (
                <span className="text-xs text-slate-400">—</span>
              )}
            </div>
          </div>
        </div>

        {/* Toolbar Filter Status & Filter Cepat */}
        <div className="runs-toolbar-bar">
          <div className="status-filter-group">
            {(["Semua", "Berhasil", "Gagal"] as const).map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => setStatusFilter(st)}
                className={`status-filter-btn ${statusFilter === st ? "active" : ""} filter-${st.toLowerCase()}`}
              >
                {st === "Semua" && <span>Semua ({stats.total})</span>}
                {st === "Berhasil" && (
                  <>
                    <CheckCircle size={12} strokeWidth={2.5} />
                    <span>Berhasil ({stats.successCount})</span>
                  </>
                )}
                {st === "Gagal" && (
                  <>
                    <AlertCircle size={12} strokeWidth={2.5} />
                    <span>Gagal ({stats.total - stats.successCount})</span>
                  </>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Tabel Riwayat Eksekusi Proporsional (>= 768px) */}
        <div className="runs-table-container md-up-only">
          <div className="runs-table-card custom-scrollbar">
            {/* Header Sticky */}
            <div className="runs-table-header-row">
              <div className="col-header col-run-waktu">Waktu (WIB)</div>
              <div className="col-header col-run-pemicu">Pemicu</div>
              <div className="col-header col-run-rentang">Rentang Data</div>
              <div className="col-header col-run-hasil">Hasil</div>
              <div className="col-header col-run-durasi">Durasi</div>
              <div className="col-header col-run-status">Status</div>
            </div>

            {/* Body Tabel Scrollable */}
            <div className="runs-table-rows-body">
              {isLoading ? (
                // Loading Skeleton
                <div className="p-4 space-y-2">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="h-9 bg-slate-100 rounded animate-pulse" />
                  ))}
                </div>
              ) : filteredRuns.length === 0 ? (
                emptyState
              ) : (
                filteredRuns.map((row) => {
                  const isFailed = row.status === "Gagal";
                  return (
                    <div
                      key={row.id}
                      className={`runs-data-row ${isFailed ? "row-failed" : ""}`}
                    >
                      {/* Kolom 1: Waktu */}
                      <div className="col-cell col-run-waktu">
                        <span className="font-semibold text-slate-800">{row.waktu_display}</span>
                      </div>

                      {/* Kolom 2: Pemicu */}
                      <div className="col-cell col-run-pemicu">
                        <span className={`badge-pemicu ${row.pemicu === "Manual" ? "pemicu-manual" : "pemicu-cron"}`}>
                          {row.pemicu || "Terjadwal"}
                        </span>
                      </div>

                      {/* Kolom 3: Rentang Data */}
                      <div className="col-cell col-run-rentang">
                        <span className="text-slate-600 font-medium">
                          {row.rentang_data || (row.target_date ? row.target_date : "—")}
                        </span>
                      </div>

                      {/* Kolom 4: Hasil */}
                      <div className="col-cell col-run-hasil">
                        {isFailed ? (
                          <span className="text-red-700 font-bold">0 berita</span>
                        ) : (
                          <span className="font-bold text-navy">
                            {formatNumberIndo(row.hasil_berita)} berita
                          </span>
                        )}
                      </div>

                      {/* Kolom 5: Durasi */}
                      <div className="col-cell col-run-durasi">
                        <span className="text-slate-600 font-mono text-xs">{row.durasi}</span>
                      </div>

                      {/* Kolom 6: Status & Catatan/Log */}
                      <div className="col-cell col-run-status">
                        {row.status !== "Gagal" ? (
                          statusBadge(row.status)
                        ) : (
                          <div className="failed-status-wrap">
                            {statusBadge(row.status)}
                            {row.catatan && (
                              <span className="failed-reason-text" title={row.catatan}>
                                ({row.catatan})
                              </span>
                            )}
                            {row.log_url && (
                              <a
                                href={row.log_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="failed-log-link"
                                title="Buka log eksekusi GitHub Actions"
                              >
                                <span>Lihat log</span>
                                <ExternalLink size={10} />
                              </a>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Sticky Table Footer */}
          <div className="runs-table-footer">
            <span className="footer-count-info">
              Menampilkan <strong>{filteredRuns.length}</strong> dari total <strong>{runs.length}</strong> run tercatat
            </span>
            <span className="footer-sync-info">
              Semua run terverifikasi dan tersinkronisasi dengan repositori data.
            </span>
          </div>
        </div>

        {/* Daftar Kartu Run (< 768px), sumber data sama dengan tabel */}
        <div className="m-list-only">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="m-item-card m-skeleton animate-pulse" />
            ))
          ) : filteredRuns.length === 0 ? (
            <div className="m-item-card">{emptyState}</div>
          ) : (
            filteredRuns.map((row) => {
              const isFailed = row.status === "Gagal";
              return (
                <article key={row.id} className={`m-item-card ${isFailed ? "m-item-failed" : ""}`}>
                  <div className="m-row-between">
                    <span className="m-item-title nowrap">{row.waktu_display} WIB</span>
                    {statusBadge(row.status)}
                  </div>
                  <div className="m-item-meta">
                    <span className="nowrap">{formatNumberIndo(isFailed ? 0 : row.hasil_berita)} berita</span>
                    <span className="meta-dot-sep">•</span>
                    <span className="nowrap">{row.durasi}</span>
                  </div>
                  <div className="m-item-meta">
                    <span className={`badge-pemicu ${row.pemicu === "Manual" ? "pemicu-manual" : "pemicu-cron"}`}>
                      {row.pemicu || "Terjadwal"}
                    </span>
                    <span className="nowrap">Data: {row.rentang_data || row.target_date || "—"}</span>
                  </div>
                  {isFailed && (row.catatan || row.log_url) && (
                    <div className="m-row-between">
                      {row.catatan && <span className="m-failed-reason">Alasan: {row.catatan}</span>}
                      {row.log_url && (
                        <a href={row.log_url} target="_blank" rel="noopener noreferrer" className="m-log-link">
                          <span>Lihat log</span>
                          <ExternalLink size={13} />
                        </a>
                      )}
                    </div>
                  )}
                </article>
              );
            })
          )}

          <div className="m-list-footer">
            <span>
              Menampilkan <strong>{filteredRuns.length}</strong> dari <strong>{runs.length}</strong> run
            </span>
          </div>
        </div>
      </div>
    </main>
  );
}
