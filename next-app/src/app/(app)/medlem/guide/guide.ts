import path from "node:path";
import type { UserContext } from "@/lib/user-context";

// The matrikel guide is for the people who keep the member register, so it
// lives outside public/ and is served only to them (next.config.js traces the
// folder into the standalone build).
export const GUIDE_DIR = path.join(process.cwd(), "content", "matrikel-guide");
export const GUIDE_IMAGE_URL = "/medlem/guide/bild/";

export function canReadGuide(user: UserContext | null): boolean {
  return Boolean(user?.is_admin) || Boolean(user?.is_matrikel_admin);
}
