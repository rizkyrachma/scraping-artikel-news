"use client";

import React, { useState, useEffect } from "react";
import { AlertCircle, CheckCircle, RefreshCw } from "lucide-react";

interface RiwayatRunCardProps {
  isRunning: boolean;
  onViewAll?: () => void;
}

const FALLBACK_RUNS = [
  { waktu: "06 Nov, 07.12", dur: "4m 38s", hasil: "158 berita", status: "selesai" },
  { waktu: "05 Nov, 07.05", dur: "4m 12s", hasil: "143 berita", status: "selesai" },
  { waktu: "04 Nov, 19.30", dur: "1m 02s", hasil: "0 (Timeout)", status: "gagal" },
  { waktu: "04 Nov, 07.15", dur: "4m 45s", hasil: "171 berita", status: "selesai" },
  { waktu: "03 Nov, 07.10", dur: "4m 02s", hasil: "129 berita", status: "selesai" },
  { waktu: "02 Nov, 07.12", dur: "3m 31s", hasil: "64 berita", status: "selesai" },
  { waktu: "01 Nov, 07.20", dur: "3m 18s", hasil: "58 berita", status: "selesai" },
  { waktu: "31 Okt, 07.15", dur: "3m 22s", hasil: "52 berita", status: "selesai" },
  { waktu: "30 Okt, 07.10", dur: "4m 50s", hasil: "166 berita", status: "selesai" },
  { waktu: "29 Okt, 07.08", dur: "3m 40s", hasil: "74 berita", status: "selesai" },
  { waktu: "28 Okt, 07.14", dur: "3m 35s", hasil: "68 berita", status: "selesai" },
  { waktu: "27 Okt, 07.22", dur: "4m 18s", hasil: "142 berita", status: "selesai" },
  { waktu: "26 Okt, 07.10", dur: "5m 02s", hasil: "185 berita", status: "selesai" },
  { waktu: "25 Okt, 07.05", dur: "2m 55s", hasil: "45 berita", status: "selesai" },
  { waktu: "24 Okt, 07.18", dur: "2m 40s", hasil: "38 berita", status: "selesai" },
  { waktu: "23 Okt, 07.12", dur: "3m 48s", hasil: "89 berita", status: "selesai" },
];

export default function RiwayatRunCard({ isRunning, onViewAll }: RiwayatRunCardProps) {
  const [runRows, setRunRows] = useState(FALLBACK_RUNS);

  useEffect(() => {
    fetch("/data/runs.json")
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          const mapped = data.slice(0, 30).map((r) => ({
            waktu: r.waktu_display || r.timestamp || "—",
            dur: r.durasi || "—",
            hasil: r.catatan ? `0 (${r.catatan})` : `${r.hasil_berita || 0} berita`,
            status: r.status === "Gagal" ? "gagal" : "selesai",
          }));
          setRunRows(mapped);
        }
      })
      .catch(() => {});
  }, []);

  const displayRows = isRunning
    ? [{ waktu: "06 Nov, 09.45", dur: "2m 41s", hasil: "—", status: "berjalan" }, ...runRows]
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
          {displayRows.map((row, idx) => (
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
          ))}

          {/* Footer info tepat di bawah baris terakhir di area scroll */}
          <div className="card-scroll-footer">
            <span className="text-scroll-count">Menampilkan {displayRows.length} run terakhir</span>
          </div>
        </div>
      </div>
    </div>
  );
}
