import { describe, it, expect, vi } from "vitest";
import { resolveFlaskUser } from "@/auth/resolveFlaskUser";

function makeDeps(over: Partial<Parameters<typeof resolveFlaskUser>[0]> = {}) {
  return {
    sessionValue: "abc",
    fetchUser: vi.fn(async () => ({
      ok: true,
      google_email: "admin@gotlandskaninen.se",
      validated: true,
    })),
    findUserByEmail: vi.fn(async (email: string) =>
      email === "admin@gotlandskaninen.se"
        ? { id: 1, email, role: "admin" }
        : null,
    ),
    ...over,
  };
}

describe("resolveFlaskUser", () => {
  it("returns null when there is no session cookie", async () => {
    const deps = makeDeps({ sessionValue: undefined });
    expect(await resolveFlaskUser(deps)).toBeNull();
    expect(deps.fetchUser).not.toHaveBeenCalled();
  });
  it("returns null when Flask says unauthenticated", async () => {
    const deps = makeDeps({ fetchUser: vi.fn(async () => ({ ok: false })) });
    expect(await resolveFlaskUser(deps)).toBeNull();
  });
  it("returns null when the Google email is not on the allowlist", async () => {
    const deps = makeDeps({
      fetchUser: vi.fn(async () => ({
        ok: true,
        google_email: "stranger@example.com",
        validated: true,
      })),
    });
    expect(await resolveFlaskUser(deps)).toBeNull();
  });
  it("returns the Payload user when the verified Google email matches, whatever User.email says", async () => {
    const deps = makeDeps({
      fetchUser: vi.fn(async () => ({
        ok: true,
        email: "admin.privat@example.se",
        google_email: "admin@gotlandskaninen.se",
        validated: true,
      })),
    });
    const user = await resolveFlaskUser(deps);
    expect(user).toMatchObject({ id: 1, role: "admin", collection: "users" });
  });
  it("matches case-insensitively on the Google email", async () => {
    const deps = makeDeps({
      fetchUser: vi.fn(async () => ({
        ok: true,
        google_email: "Admin@Gotlandskaninen.SE",
        validated: true,
      })),
    });
    const user = await resolveFlaskUser(deps);
    expect(deps.findUserByEmail).toHaveBeenCalledWith(
      "admin@gotlandskaninen.se",
    );
    expect(user).toMatchObject({ id: 1 });
  });
  it("ignores an allowlisted address set as User.email by an account Google knows as someone else", async () => {
    // The allowlisted address has no Flask account; a validated user sets it
    // as their own User.email through PATCH /api/manage/user/.
    const deps = makeDeps({
      fetchUser: vi.fn(async () => ({
        ok: true,
        email: "admin@gotlandskaninen.se",
        google_email: "eve@gotlandskaninen.se",
        validated: true,
      })),
    });
    expect(await resolveFlaskUser(deps)).toBeNull();
    expect(deps.findUserByEmail).toHaveBeenCalledWith("eve@gotlandskaninen.se");
  });
  it("requires validated === true", async () => {
    const deps = makeDeps({
      fetchUser: vi.fn(async () => ({
        ok: true,
        email: "admin@gotlandskaninen.se",
        google_email: "admin@gotlandskaninen.se",
        validated: false,
      })),
    });
    expect(await resolveFlaskUser(deps)).toBeNull();
  });
});
