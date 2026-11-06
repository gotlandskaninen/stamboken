import { randomBytes } from "crypto";

/**
 * The temporary password MUST come from Node's
 * crypto.randomBytes — never Math.random(). 16 random bytes → base64url
 * → 22 URL-safe chars (A-Za-z0-9_-), no padding. Lives outside
 * actions.ts because "use server" modules may only export async
 * functions, and this must stay unit-testable.
 */
export function generateTempPassword(): string {
  return randomBytes(16).toString("base64url");
}
