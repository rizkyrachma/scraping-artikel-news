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

const _shaDataCache = new Map<string, ArrayBuffer>();

export async function fetchRemoteDataFile(repoRelativePath: string): Promise<Response | null> {
  const { repo, token } = getGitHubConfig();
  let ref = "data";

  // Pakai SHA commit terbaru jika token tersedia agar melewati cache CDN raw.githubusercontent.com
  if (token) {
    try {
      const commitRes = await fetch(`https://api.github.com/repos/${repo}/commits/data`, {
        headers: buildGitHubHeaders(token),
        cache: "no-store",
        signal: AbortSignal.timeout(4000),
      });
      if (commitRes.ok) {
        const commitJson = await commitRes.json();
        if (commitJson?.sha) ref = commitJson.sha;
      }
    } catch {
      // Abaikan dan pakai ref "data" langsung
    }
  }

  // SHA commit bersifat immutable: kembalikan salinan cache bila commit data tidak berubah
  const cacheKey = `${repo}:${ref}:${repoRelativePath}`;
  if (ref !== "data" && _shaDataCache.has(cacheKey)) {
    return new Response(_shaDataCache.get(cacheKey)!);
  }

  const rawUrl = `https://raw.githubusercontent.com/${repo}/${ref}/${repoRelativePath}${
    ref === "data" ? `?t=${Date.now()}` : ""
  }`;
  try {
    const res = await fetch(rawUrl, {
      headers: token ? { Authorization: `Bearer ${token}`, "Cache-Control": "no-cache" } : { "Cache-Control": "no-cache" },
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) return null;
    if (ref !== "data") {
      const buf = await res.arrayBuffer();
      if (buf.byteLength <= 5 * 1024 * 1024) {
        if (_shaDataCache.size >= 8) {
          const oldest = _shaDataCache.keys().next().value;
          if (oldest) _shaDataCache.delete(oldest);
        }
        _shaDataCache.set(cacheKey, buf);
      }
      return new Response(buf);
    }
    return res;
  } catch {
    return null;
  }
}
