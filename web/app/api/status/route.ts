import { NextRequest, NextResponse } from "next/server";
import { getGitHubConfig, buildGitHubHeaders, WORKFLOW_FILENAME } from "@/lib/github";

export const dynamic = "force-dynamic";

interface GitHubRunItem {
  id: number;
  status: string;
  conclusion: string | null;
  html_url: string;
  created_at: string;
  updated_at: string;
  event: string;
  run_number: number;
}

export async function GET() {
  try {
    const { repo, token } = getGitHubConfig();
    const runsUrl = `https://api.github.com/repos/${repo}/actions/workflows/${WORKFLOW_FILENAME}/runs?per_page=5`;

    const ghRes = await fetch(runsUrl, {
      headers: buildGitHubHeaders(token),
      cache: "no-store",
    });

    if (!ghRes.ok) {
      return NextResponse.json(
        {
          ok: false,
          isRunning: false,
          error: `Gagal membaca status GitHub Actions (${ghRes.status})`,
        },
        { status: ghRes.status }
      );
    }

    const data = await ghRes.json();
    const runs: GitHubRunItem[] = Array.isArray(data.workflow_runs) ? data.workflow_runs : [];

    const activeRun = runs.find(
      (r) =>
        r.status === "in_progress" ||
        r.status === "queued" ||
        r.status === "waiting" ||
        r.status === "pending" ||
        r.status === "requested"
    );
    const latestRun = runs[0] || null;

    let currentStepName: string | null = null;
    if (activeRun) {
      if (activeRun.status !== "in_progress") {
        currentStepName = "Menunggu runner GitHub Actions";
      } else {
        try {
          const jobsUrl = `https://api.github.com/repos/${repo}/actions/runs/${activeRun.id}/jobs`;
          const jobsRes = await fetch(jobsUrl, {
            headers: buildGitHubHeaders(token),
            cache: "no-store",
          });
          if (jobsRes.ok) {
            const jobsData = await jobsRes.json();
            const firstJob = jobsData.jobs?.[0];
            const inProgressStep = firstJob?.steps?.find((s: { status: string }) => s.status === "in_progress");
            if (inProgressStep?.name) {
              currentStepName = inProgressStep.name;
            }
          }
        } catch {
          // Abaikan jika gagal mengambil detail step
        }
      }
    }

    return NextResponse.json({
      ok: true,
      isRunning: Boolean(activeRun),
      activeRun: activeRun
        ? {
            id: activeRun.id,
            status: activeRun.status,
            htmlUrl: activeRun.html_url,
            createdAt: activeRun.created_at,
            updatedAt: activeRun.updated_at,
            event: activeRun.event,
            currentStepName,
          }
        : null,
      latestRun: latestRun
        ? {
            id: latestRun.id,
            status: latestRun.status,
            conclusion: latestRun.conclusion,
            htmlUrl: latestRun.html_url,
            createdAt: latestRun.created_at,
            updatedAt: latestRun.updated_at,
            event: latestRun.event,
          }
        : null,
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        isRunning: false,
        error: err instanceof Error ? err.message : "Gagal memeriksa status workflow",
      },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    if (body.action !== "cancel" || !body.runId) {
      return NextResponse.json({ ok: false, error: "Action atau runId tidak valid" }, { status: 400 });
    }
    const { repo, token } = getGitHubConfig();
    if (!token) {
      return NextResponse.json({ ok: false, error: "GITHUB_PAT belum dikonfigurasi" }, { status: 500 });
    }
    const cancelUrl = `https://api.github.com/repos/${repo}/actions/runs/${Number(body.runId)}/cancel`;
    const ghRes = await fetch(cancelUrl, {
      method: "POST",
      headers: buildGitHubHeaders(token),
    });
    return NextResponse.json({ ok: ghRes.ok, status: ghRes.status });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err instanceof Error ? err.message : "Gagal membatalkan workflow" },
      { status: 500 }
    );
  }
}
