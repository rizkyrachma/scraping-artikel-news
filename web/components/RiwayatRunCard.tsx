"use client";

import React from "react";
import { AlertCircle, CheckCircle, RefreshCw } from "lucide-react";
import { RunHistoryItem } from "@/lib/types";

interface RiwayatRunCardProps {
  isRunning: boolean;
  runs?: RunHistoryItem[];
  onViewAll?: () => void;
}

export default function RiwayatRunCard({ isRunning, runs = [], onViewAll }: RiwayatRunCardProps) {
  const runRows = runs.slice(0, 30).map((r) => ({
    waktu: r.waktu_display || r.timestamp || "—",
    dur: r.durasi || "—",
    hasil: r.status === "Gagal" && r.catatan ? `0 (${r.catatan})` : `${r.hasil_berita || 0} berita`,
    status: r.status === "Gagal" ? "gagal" : "selesai",
  }));

  const displayRows = isRunning
    ? [{ waktu: "Saat ini", dur: "Live", hasil: "—", status: "berjalan" }, ...runRows]
    : runRows;

  return (
    <div className="card-box riwayat-run-card panel-primary">
      <div className="card-header-row">
        <h3 className="card-title">Riwayat Run</h3>
        <button type="button" onClick={onViewAll} className="btn-link-action">
          Lihat semua →
        </button>
      </div>

      <div className="run-table">
        <div className="run-table-header">
          <div className="col-waktu">Waktu (WIB)</div>
          <div className="col-durasi desktop-only">Durasi</div>
          <div className="col-hasil">Hasil</div>
          <div className="col-status">Status</div>
        </div>

        {/* Scrollable table body */}
        <div className="run-table-body custom-scrollbar">
          {displayRows.length === 0 ? (
            <div className="p-4 text-xs text-slate-400 text-center">Memuat riwayat run...</div>
          ) : (
            displayRows.map((row, idx) => (
              <div key={idx} className="run-table-row">
                <div className="col-waktu">
                  <span className="waktu-main">{row.waktu}</span>
                  <span className="durasi-sub mobile-only">{row.dur}</span>
                </div>
                <div className="col-durasi desktop-only">{row.dur}</div>
                <div className="col-hasil">{row.hasil}</div>
                <div className="col-status">
                  {row.status === "selesai" && (
                    <span className="badge-status-selesai">
                      <CheckCircle size={12} strokeWidth={2.5} />
                      <span>Berhasil</span>
                    </span>
                  )}
                  {row.status === "berjalan" && (
                    <span className="badge-status-berjalan">
                      <RefreshCw size={12} className="animate-spin" strokeWidth={2.5} />
                      <span>Berjalan</span>
                    </span>
                  )}
                  {row.status === "gagal" && (
                    <span className="badge-status-gagal">
                      <AlertCircle size={12} strokeWidth={2.5} />
                      <span>Gagal</span>
                    </span>
                  )}
                </div>
              </div>
            ))
          )}

          {/* Footer info tepat di bawah baris terakhir di area scroll */}
          <div className="card-scroll-footer">
            <span className="text-scroll-count">Menampilkan {displayRows.length} run terakhir</span>
          </div>
        </div>
      </div>
    </div>
  );
}
