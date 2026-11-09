import { execSync } from "child_process";

export const DEFAULT_GITHUB_REPO = "rizkyrachma/scraping-artikel-news";
export const WORKFLOW_FILENAME = "daily_scrape.yml";

export function getGitHubConfig(): { repo: string; token: string | null } {
  const repo = (process.env.GITHUB_REPO || DEFAULT_GITHUB_REPO).trim();
  const envToken = (
    process.env.GITHUB_PAT ||
    process.env.GH_TOKEN ||
    process.env.GITHUB_TOKEN ||
    ""
  ).trim();

  if (envToken) {
    return { repo, token: envToken };
  }

  // Fallback lokal (development) menggunakan Git Credential Manager jika env belum diset
  if (process.env.NODE_ENV !== "production") {
    try {
      const out = execSync("git credential fill", {
        input: "protocol=https\nhost=github.com\n\n",
        encoding: "utf-8",
        timeout: 3000,
        stdio: ["pipe", "pipe", "ignore"],
      });
      const match = out.match(/^password=(.+)$/m);
      if (match && match[1]) {
        return { repo, token: match[1].trim() };
      }
    } catch {
      // Abaikan jika git credential tidak tersedia
    }
  }

  return { repo, token: null };
}

export function buildGitHubHeaders(token: string | null): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "agro-media-monitoring-dashboard",
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}
