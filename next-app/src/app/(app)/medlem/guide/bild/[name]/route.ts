import { readFile } from "node:fs/promises";
import path from "node:path";
import { getUser } from "@/lib/auth";
import { GUIDE_DIR, canReadGuide } from "../../guide";

// The guide's screenshots, for the same readers as the guide. The middleware
// skips paths with a dot, so this handler does its own check.
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  // A plain file name only: nothing that can climb out of the folder.
  if (!/^[a-z0-9-]+\.png$/.test(name) || !canReadGuide(await getUser())) {
    return new Response(null, { status: 404 });
  }
  try {
    const png = await readFile(path.join(GUIDE_DIR, name));
    return new Response(png, {
      headers: {
        "Content-Type": "image/png",
        "Cache-Control": "private, max-age=3600",
      },
    });
  } catch {
    return new Response(null, { status: 404 });
  }
}
