import test from "node:test";
import assert from "node:assert/strict";

// Helper tiruan logika dispatch /api/trigger untuk pengujian unit dengan mock fetch
async function executeTriggerLogic({ token, repo, fetchFn, body }) {
  if (!token) {
    return {
      status: 500,
      data: {
        ok: false,
        error: "GITHUB_PAT belum dikonfigurasi di environment server Vercel. Silakan konfigurasikan GITHUB_PAT di Vercel Project Settings > Environment Variables.",
      },
    };
  }

  const dispatchUrl = `https://api.github.com/repos/${repo}/actions/workflows/daily_scrape.yml/dispatches`;
  try {
    const ghRes = await fetchFn(dispatchUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!ghRes.ok) {
      const detail = await ghRes.text().catch(() => "");
      return {
        status: ghRes.status,
        data: {
          ok: false,
          error: `GitHub API menolak dispatch (${ghRes.status})`,
          detail: detail.slice(0, 300),
        },
      };
    }

    return {
      status: 200,
      data: {
        ok: true,
        message: "Workflow daily_scrape.yml berhasil dipicu di GitHub Actions",
      },
    };
  } catch (err) {
    return {
      status: 500,
      data: {
        ok: false,
        error: err instanceof Error ? err.message : "Terjadi kesalahan internal",
      },
    };
  }
}

// Helper tiruan logika status /api/status untuk pengujian unit dengan mock fetch
async function executeStatusLogic({ token, repo, fetchFn }) {
  try {
    const runsUrl = `https://api.github.com/repos/${repo}/actions/workflows/daily_scrape.yml/runs?per_page=5`;
    const ghRes = await fetchFn(runsUrl);
    if (!ghRes.ok) {
      return {
        status: ghRes.status,
        data: {
          ok: false,
          isRunning: false,
          error: `Gagal membaca status GitHub Actions (${ghRes.status})`,
        },
      };
    }

    const data = await ghRes.json();
    const runs = data.workflow_runs || [];
    const activeRun = runs.find((r) => ["in_progress", "queued", "waiting"].includes(r.status));
    const latestRun = runs[0] || null;

    let wasSkipped = false;
    let skipReason = null;
    let failedStep = null;

    if (!activeRun && latestRun) {
      const jobsUrl = `https://api.github.com/repos/${repo}/actions/runs/${latestRun.id}/jobs`;
      const jobsRes = await fetchFn(jobsUrl);
      if (jobsRes.ok) {
        const jobsData = await jobsRes.json();
        const steps = jobsData.jobs?.[0]?.steps || [];
        const pipeStep = steps.find((s) => s.name?.includes("Jalankan Pipeline Scraping"));
        if (pipeStep && pipeStep.conclusion === "skipped" && latestRun.conclusion === "success") {
          wasSkipped = true;
          skipReason = "Data tanggal target sudah ada di arsip data_export (dilewati oleh sistem).";
        }
        const failStep = steps.find((s) => s.conclusion === "failure");
        if (failStep) {
          failedStep = failStep.name;
        }
      }
    }

    return {
      status: 200,
      data: {
        ok: true,
        isRunning: Boolean(activeRun),
        activeRun: activeRun ? { id: activeRun.id, status: activeRun.status } : null,
        latestRun: latestRun
          ? {
              id: latestRun.id,
              status: latestRun.status,
              conclusion: latestRun.conclusion,
              wasSkipped,
              skipReason,
              failedStep,
            }
          : null,
      },
    };
  } catch (err) {
    return {
      status: 500,
      data: {
        ok: false,
        isRunning: false,
        error: err instanceof Error ? err.message : "Error",
      },
    };
  }
}

// --- TES TRIGGER ---

test("trigger - token missing returns 500 with actionable error", async () => {
  const res = await executeTriggerLogic({
    token: null,
    repo: "owner/repo",
    fetchFn: async () => {},
    body: {},
  });
  assert.equal(res.status, 500);
  assert.equal(res.data.ok, false);
  assert.ok(res.data.error.includes("GITHUB_PAT belum dikonfigurasi"));
});

test("trigger - GitHub 401 Unauthorized returns 401 with details", async () => {
  const fakeFetch = async () => ({
    ok: false,
    status: 401,
    text: async () => "Bad credentials",
  });
  const res = await executeTriggerLogic({
    token: "invalid-pat",
    repo: "owner/repo",
    fetchFn: fakeFetch,
    body: {},
  });
  assert.equal(res.status, 401);
  assert.equal(res.data.ok, false);
  assert.ok(res.data.error.includes("401"));
  assert.equal(res.data.detail, "Bad credentials");
});

test("trigger - GitHub 403 Forbidden returns 403", async () => {
  const fakeFetch = async () => ({
    ok: false,
    status: 403,
    text: async () => "Resource not accessible by personal access token",
  });
  const res = await executeTriggerLogic({
    token: "pat",
    repo: "owner/repo",
    fetchFn: fakeFetch,
    body: {},
  });
  assert.equal(res.status, 403);
  assert.equal(res.data.ok, false);
  assert.ok(res.data.error.includes("403"));
});

test("trigger - GitHub 422 Unprocessable returns 422", async () => {
  const fakeFetch = async () => ({
    ok: false,
    status: 422,
    text: async () => "Workflow does not have 'workflow_dispatch' trigger",
  });
  const res = await executeTriggerLogic({
    token: "pat",
    repo: "owner/repo",
    fetchFn: fakeFetch,
    body: {},
  });
  assert.equal(res.status, 422);
  assert.equal(res.data.ok, false);
  assert.ok(res.data.detail.includes("workflow_dispatch"));
});

test("trigger - GitHub 204 No Content (Sukses) returns 200 ok", async () => {
  const fakeFetch = async () => ({
    ok: true,
    status: 204,
  });
  const res = await executeTriggerLogic({
    token: "valid-pat",
    repo: "owner/repo",
    fetchFn: fakeFetch,
    body: { mode: "auto" },
  });
  assert.equal(res.status, 200);
  assert.equal(res.data.ok, true);
  assert.ok(res.data.message.includes("berhasil dipicu"));
});

test("trigger - Network timeout throws error returning 500", async () => {
  const fakeFetch = async () => {
    throw new Error("Connect timeout (ETIMEDOUT)");
  };
  const res = await executeTriggerLogic({
    token: "valid-pat",
    repo: "owner/repo",
    fetchFn: fakeFetch,
    body: {},
  });
  assert.equal(res.status, 500);
  assert.equal(res.data.ok, false);
  assert.ok(res.data.error.includes("Connect timeout"));
});

// --- TES STATUS ---

test("status - active run returns isRunning: true", async () => {
  const fakeFetch = async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      workflow_runs: [
        { id: 999, status: "in_progress", conclusion: null },
      ],
    }),
  });
  const res = await executeStatusLogic({
    token: "pat",
    repo: "owner/repo",
    fetchFn: fakeFetch,
  });
  assert.equal(res.status, 200);
  assert.equal(res.data.isRunning, true);
  assert.equal(res.data.activeRun.id, 999);
});

test("status - completed run with pipeline skipped returns wasSkipped: true", async () => {
  const fakeFetch = async (url) => {
    if (url.includes("/runs?")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          workflow_runs: [
            { id: 888, status: "completed", conclusion: "success" },
          ],
        }),
      };
    }
    if (url.includes("/runs/888/jobs")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          jobs: [
            {
              steps: [
                { name: "Checkout repository", conclusion: "success" },
                { name: "Tentukan rentang tanggal target (WIB)", conclusion: "success" },
                { name: "Jalankan Pipeline Scraping (main.py)", conclusion: "skipped" },
                { name: "Sinkronisasi Data Dashboard", conclusion: "skipped" },
              ],
            },
          ],
        }),
      };
    }
  };

  const res = await executeStatusLogic({
    token: "pat",
    repo: "owner/repo",
    fetchFn: fakeFetch,
  });
  assert.equal(res.status, 200);
  assert.equal(res.data.isRunning, false);
  assert.equal(res.data.latestRun.wasSkipped, true);
  assert.ok(res.data.latestRun.skipReason.includes("dilewati"));
});

test("status - completed run with failure returns failedStep", async () => {
  const fakeFetch = async (url) => {
    if (url.includes("/runs?")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          workflow_runs: [
            { id: 777, status: "completed", conclusion: "failure" },
          ],
        }),
      };
    }
    if (url.includes("/runs/777/jobs")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          jobs: [
            {
              steps: [
                { name: "Setup Python 3.11", conclusion: "success" },
                { name: "Install Python dependencies", conclusion: "failure" },
              ],
            },
          ],
        }),
      };
    }
  };

  const res = await executeStatusLogic({
    token: "pat",
    repo: "owner/repo",
    fetchFn: fakeFetch,
  });
  assert.equal(res.status, 200);
  assert.equal(res.data.isRunning, false);
  assert.equal(res.data.latestRun.conclusion, "failure");
  assert.equal(res.data.latestRun.failedStep, "Install Python dependencies");
});
