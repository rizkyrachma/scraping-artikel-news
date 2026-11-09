import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import { fetchRemoteDataFile } from "@/lib/github";

export const dynamic = "force-dynamic";

const VALID_EXCEL_RE = /^Media_Monitoring_Agro_[A-Za-z0-9_-]+\.xlsx$/;

export async function GET(
  _req: Request,
  { params }: { params: { file: string } }
) {
  const file = params?.file || "";
  if (!VALID_EXCEL_RE.test(file)) {
    return NextResponse.json({ error: "Nama file Excel tidak valid" }, { status: 400 });
  }

  const remote = await fetchRemoteDataFile(`web/public/files/${file}`);
  if (remote) {
    const buf = await remote.arrayBuffer();
    return new NextResponse(buf, {
      status: 200,
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename="${file}"`,
        "Cache-Control": "no-store",
      },
    });
  }

  try {
    const localPath = path.join(process.cwd(), "public", "files", file);
    const buf = await fs.readFile(localPath);
    return new NextResponse(buf, {
      status: 200,
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename="${file}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return NextResponse.json({ error: "File Excel tidak ditemukan" }, { status: 404 });
  }
}
