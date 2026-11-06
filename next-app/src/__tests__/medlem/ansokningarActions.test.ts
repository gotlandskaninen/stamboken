import { describe, it, expect, beforeEach, vi } from "vitest";

const { fetchApiMock, revalidatePathMock } = vi.hoisted(() => ({
  fetchApiMock: vi.fn(),
  revalidatePathMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ fetchApi: fetchApiMock }));
vi.mock("next/cache", () => ({ revalidatePath: revalidatePathMock }));

import {
  approveApplication,
  rejectApplication,
} from "@/app/(app)/medlem/ansokningar/actions";

beforeEach(() => {
  fetchApiMock.mockReset();
  revalidatePathMock.mockReset();
});

describe("approveApplication", () => {
  it("POSTs without a body and returns duplicateContactEmail=false by default", async () => {
    fetchApiMock.mockResolvedValue({ id: 7, status: "approved" });
    const result = await approveApplication(7);
    expect(result).toEqual({ ok: true, duplicateContactEmail: false });
    expect(fetchApiMock).toHaveBeenCalledWith(
      "/v2/member-applications/7/approve",
      {
        method: "POST",
      },
    );
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/ansokningar");
  });

  it("surfaces duplicate_contact_email=true from the approve response", async () => {
    fetchApiMock.mockResolvedValue({
      id: 7,
      status: "approved",
      duplicate_contact_email: true,
    });
    const result = await approveApplication(7);
    expect(result).toEqual({ ok: true, duplicateContactEmail: true });
  });

  it("returns the RFC 9457 detail on failure", async () => {
    fetchApiMock.mockRejectedValue({
      detail: "Ansökan är redan behandlad (status: approved)",
    });
    const result = await approveApplication(7);
    expect(result).toEqual({
      ok: false,
      error: "Ansökan är redan behandlad (status: approved)",
    });
  });
});

describe("rejectApplication", () => {
  it("POSTs the rejection reason and revalidates the queue", async () => {
    fetchApiMock.mockResolvedValue({});
    const result = await rejectApplication(7, "ofullständig");
    expect(result).toEqual({ ok: true });
    expect(fetchApiMock).toHaveBeenCalledWith(
      "/v2/member-applications/7/reject",
      {
        method: "POST",
        body: JSON.stringify({ rejection_reason: "ofullständig" }),
        headers: { "Content-Type": "application/json" },
      },
    );
    expect(revalidatePathMock).toHaveBeenCalledWith("/medlem/ansokningar");
  });
});
