import { describe, it, expect, vi, beforeEach } from "vitest";
import type { UserContext } from "@/lib/user-context";

const { getUserMock, notFoundMock } = vi.hoisted(() => ({
  getUserMock: vi.fn(),
  notFoundMock: vi.fn(() => {
    // Next's notFound() throws — emulate so control flow matches prod.
    throw new Error("notFound");
  }),
}));

vi.mock("@/lib/auth", () => ({ getUser: getUserMock }));
vi.mock("next/navigation", () => ({ notFound: notFoundMock }));

import { requireHerdAdmin } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/requireAdmin";

const makeUser = (over: Partial<UserContext>): UserContext =>
  ({
    id: 1,
    username: "u",
    email: "u@example.com",
    is_admin: false,
    is_manager: null,
    is_owner: null,
    is_matrikel_admin: false,
    ...over,
  }) as unknown as UserContext;

describe("requireHerdAdmin", () => {
  beforeEach(() => {
    getUserMock.mockReset();
    notFoundMock.mockClear();
  });

  it("returns the user for an admin", async () => {
    const admin = makeUser({ is_admin: true });
    getUserMock.mockResolvedValue(admin);
    await expect(requireHerdAdmin()).resolves.toBe(admin);
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  it("returns the user for a genebank manager", async () => {
    const manager = makeUser({ is_manager: [1] });
    getUserMock.mockResolvedValue(manager);
    await expect(requireHerdAdmin()).resolves.toBe(manager);
  });

  it("404s a matrikel-only admin — the landing gate admits them, these pages must not", async () => {
    getUserMock.mockResolvedValue(makeUser({ is_matrikel_admin: true }));
    await expect(requireHerdAdmin()).rejects.toThrow("notFound");
    expect(notFoundMock).toHaveBeenCalledTimes(1);
  });

  it("404s an owner and a missing session", async () => {
    getUserMock.mockResolvedValue(makeUser({ is_owner: ["G1"] }));
    await expect(requireHerdAdmin()).rejects.toThrow("notFound");
    getUserMock.mockResolvedValue(null);
    await expect(requireHerdAdmin()).rejects.toThrow("notFound");
  });
});
