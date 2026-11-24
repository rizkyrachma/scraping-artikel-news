export type NoticeType = "info" | "warning" | "error" | "success";

export interface StatusNotice {
  type: NoticeType;
  message: string;
  url?: string;
}

export interface ActiveRunData {
  id: number;
  status: string;
  htmlUrl?: string;
  currentStepName?: string | null;
}

export interface LatestRunData {
  id: number;
  status: string;
  conclusion: string | null;
  htmlUrl?: string;
  wasSkipped?: boolean;
  skipReason?: string | null;
  failedStep?: string | null;
}

/**
 * Memetakan status polling GitHub Actions ke objek notifikasi yang jujur dan informatif.
 * Menjamin UI tidak pernah menampilkan "Selesai" jika run dilewati atau gagal.
 */
export function mapRunStatusToNotice(params: {
  isRunning: boolean;
  activeRun: ActiveRunData | null;
  latestRun: LatestRunData | null;
  wasRunning: boolean;
}): StatusNotice | null {
  const { isRunning, activeRun, latestRun, wasRunning } = params;

  if (isRunning) {
    const step = activeRun?.currentStepName || "Menunggu runner GitHub Actions";
    return {
      type: "info",
      message: `Sedang berjalan: ${step}`,
      url: activeRun?.htmlUrl,
    };
  }

  // Jika baru saja selesai berjalan
  if (wasRunning && latestRun) {
    if (latestRun.conclusion === "success") {
      if (latestRun.wasSkipped) {
        return {
          type: "warning",
          message:
            latestRun.skipReason ||
            "Pengambilan data dilewati karena data tanggal target sudah ada di arsip.",
          url: latestRun.htmlUrl,
        };
      }
      return {
        type: "success",
        message: "Scraping berhasil selesai dan data telah disinkronkan.",
        url: latestRun.htmlUrl,
      };
    }

    if (latestRun.conclusion === "failure") {
      const stepInfo = latestRun.failedStep ? ` pada langkah "${latestRun.failedStep}"` : "";
      return {
        type: "error",
        message: `Workflow scraping gagal dijalankan di GitHub Actions${stepInfo}. Silakan periksa log.`,
        url: latestRun.htmlUrl,
      };
    }

    if (latestRun.conclusion === "cancelled") {
      return {
        type: "warning",
        message: "Workflow scraping dibatalkan oleh pengguna atau sistem.",
        url: latestRun.htmlUrl,
      };
    }

    if (latestRun.conclusion === "timed_out") {
      return {
        type: "error",
        message: "Workflow scraping melebihi batas waktu eksekusi (timed out).",
        url: latestRun.htmlUrl,
      };
    }
  }

  return null;
}
