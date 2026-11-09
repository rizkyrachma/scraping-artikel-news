import { NextRequest, NextResponse } from "next/server";
import { getGitHubConfig, buildGitHubHeaders, WORKFLOW_FILENAME } from "@/lib/github";

const DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;

function validateDateRange(startDate?: string, endDate?: string): string | null {
  if (!startDate || !DATE_REGEX.test(startDate)) {
    return "Format startDate harus YYYY-MM-DD";
  }
  const effectiveEnd = endDate && DATE_REGEX.test(endDate) ? endDate : startDate;
  const d1 = new Date(`${startDate}T00:00:00Z`);
  const d2 = new Date(`${effectiveEnd}T00:00:00Z`);
  if (Number.isNaN(d1.getTime()) || Number.isNaN(d2.getTime())) {
    return "Tanggal tidak valid";
  }
  if (d1 > d2) {
    return "Tanggal mulai tidak boleh lebih besar dari tanggal akhir";
  }
  const diffDays = Math.round((d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24)) + 1;
  if (diffDays > 31) {
    return "Rentang tanggal maksimal 31 hari dalam satu eksekusi";
  }
  return null;
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const mode = body.mode === "manual" ? "manual" : "auto";
    const skipExisting = body.skipExisting !== false;
    const startDate = typeof body.startDate === "string" ? body.startDate.trim() : "";
    const endDate = typeof body.endDate === "string" ? body.endDate.trim() : startDate;

    if (mode === "manual") {
      const err = validateDateRange(startDate, endDate);
      if (err) {
        return NextResponse.json({ ok: false, error: err }, { status: 400 });
      }
    }

    const { repo, token } = getGitHubConfig();
    if (!token) {
      return NextResponse.json(
        {
          ok: false,
          error: "GITHUB_PAT belum dikonfigurasi di environment server",
        },
        { status: 500 }
      );
    }

    const dispatchUrl = `https://api.github.com/repos/${repo}/actions/workflows/${WORKFLOW_FILENAME}/dispatches`;
    const ghRes = await fetch(dispatchUrl, {
      method: "POST",
      headers: {
        ...buildGitHubHeaders(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          mode,
          start_date: mode === "manual" ? startDate : "",
          end_date: mode === "manual" ? (endDate || startDate) : "",
          skip_existing: skipExisting ? "true" : "false",
        },
      }),
    });

    if (!ghRes.ok) {
      const detail = await ghRes.text().catch(() => "");
      return NextResponse.json(
        {
          ok: false,
          error: `GitHub API menolak dispatch (${ghRes.status})`,
          detail: detail.slice(0, 300),
        },
        { status: ghRes.status }
      );
    }

    return NextResponse.json({
      ok: true,
      message: "Workflow daily_scrape.yml berhasil dipicu di GitHub Actions",
      mode,
      startDate: mode === "manual" ? startDate : "yesterday",
      endDate: mode === "manual" ? (endDate || startDate) : "yesterday",
      skipExisting,
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        error: err instanceof Error ? err.message : "Terjadi kesalahan internal",
      },
      { status: 500 }
    );
  }
}
