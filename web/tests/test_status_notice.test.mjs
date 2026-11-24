import test from "node:test";
import assert from "node:assert/strict";
import { mapRunStatusToNotice } from "../lib/statusNotice.ts";

test("mapRunStatusToNotice - running state returns info notice", () => {
  const notice = mapRunStatusToNotice({
    isRunning: true,
    activeRun: {
      id: 12345,
      status: "in_progress",
      htmlUrl: "https://github.com/org/repo/actions/runs/12345",
      currentStepName: "Jalankan Pipeline Scraping",
    },
    latestRun: null,
    wasRunning: false,
  });

  assert.ok(notice);
  assert.equal(notice.type, "info");
  assert.equal(notice.message, "Sedang berjalan: Jalankan Pipeline Scraping");
  assert.equal(notice.url, "https://github.com/org/repo/actions/runs/12345");
});

test("mapRunStatusToNotice - completion with wasSkipped returns warning notice", () => {
  const notice = mapRunStatusToNotice({
    isRunning: false,
    activeRun: null,
    latestRun: {
      id: 12345,
      status: "completed",
      conclusion: "success",
      htmlUrl: "https://github.com/org/repo/actions/runs/12345",
      wasSkipped: true,
      skipReason: "Data tanggal target sudah ada di arsip data_export (dilewati oleh sistem).",
    },
    wasRunning: true,
  });

  assert.ok(notice);
  assert.equal(notice.type, "warning");
  assert.ok(notice.message.includes("dilewati"));
  assert.equal(notice.url, "https://github.com/org/repo/actions/runs/12345");
});

test("mapRunStatusToNotice - completion with genuine success returns success notice", () => {
  const notice = mapRunStatusToNotice({
    isRunning: false,
    activeRun: null,
    latestRun: {
      id: 12345,
      status: "completed",
      conclusion: "success",
      htmlUrl: "https://github.com/org/repo/actions/runs/12345",
      wasSkipped: false,
    },
    wasRunning: true,
  });

  assert.ok(notice);
  assert.equal(notice.type, "success");
  assert.ok(notice.message.includes("berhasil selesai"));
});

test("mapRunStatusToNotice - completion with failure returns error notice with step name", () => {
  const notice = mapRunStatusToNotice({
    isRunning: false,
    activeRun: null,
    latestRun: {
      id: 12345,
      status: "completed",
      conclusion: "failure",
      htmlUrl: "https://github.com/org/repo/actions/runs/12345",
      failedStep: "Ambil data_export dan pipeline_state",
    },
    wasRunning: true,
  });

  assert.ok(notice);
  assert.equal(notice.type, "error");
  assert.ok(notice.message.includes("Ambil data_export dan pipeline_state"));
});

test("mapRunStatusToNotice - completion with cancellation returns warning notice", () => {
  const notice = mapRunStatusToNotice({
    isRunning: false,
    activeRun: null,
    latestRun: {
      id: 12345,
      status: "completed",
      conclusion: "cancelled",
      htmlUrl: "https://github.com/org/repo/actions/runs/12345",
    },
    wasRunning: true,
  });

  assert.ok(notice);
  assert.equal(notice.type, "warning");
  assert.ok(notice.message.includes("dibatalkan"));
});

test("mapRunStatusToNotice - idle load (wasRunning: false) returns null", () => {
  const notice = mapRunStatusToNotice({
    isRunning: false,
    activeRun: null,
    latestRun: {
      id: 12345,
      status: "completed",
      conclusion: "success",
    },
    wasRunning: false,
  });

  assert.equal(notice, null);
});
