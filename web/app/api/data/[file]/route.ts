import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import { fetchRemoteDataFile } from "@/lib/github";

export const dynamic = "force-dynamic";

const ALLOWED_FILES = new Set(["summary.json", "runs.json", "articles_all.json"]);

export async function GET(
  _req: Request,
  { params }: { params: { file: string } }
) {
  const file = params?.file || "";
  if (!ALLOWED_FILES.has(file)) {
    return NextResponse.json({ error: "File tidak diizinkan" }, { status: 404 });
  }

  const remote = await fetchRemoteDataFile(`web/public/data/${file}`);
  if (remote) {
    const body = await remote.text();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Data-Source": "github-data",
      },
    });
  }

  try {
    const localPath = path.join(process.cwd(), "public", "data", file);
    const localBody = await fs.readFile(localPath, "utf-8");
    return new NextResponse(localBody, {
      status: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Data-Source": "local-disk",
      },
    });
  } catch {
    return NextResponse.json({ error: "Data tidak ditemukan" }, { status: 404 });
  }
}
