import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock next/cache
vi.mock("next/cache", () => ({
  revalidatePath: vi.fn(),
}));

// Mock @/lib/api
vi.mock("@/lib/api", () => ({
  fetchApi: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    title: string;
    detail: string;
    constructor(p: { status: number; title: string; detail: string }) {
      super(p.detail);
      this.status = p.status;
      this.title = p.title;
      this.detail = p.detail;
    }
  },
}));

// Mock next/headers (required by fetchApi internals when imported)
vi.mock("next/headers", () => ({
  cookies: vi.fn(() => ({
    getAll: () => [{ name: "session", value: "test-session" }],
    get: () => ({ name: "session", value: "test-session" }),
  })),
  headers: vi.fn(() => ({
    get: () => null,
  })),
}));

import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";
import {
  updateProfilePicture,
  updateSettings,
} from "@/app/(app)/stamboken/(dashboard)/profil/actions";

describe("profil/actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("updateProfilePicture", () => {
    it("calls fetchApi with FormData and revalidates", async () => {
      vi.mocked(fetchApi).mockResolvedValue({ status: "updated" });
      const formData = new FormData();
      formData.append("profile_picture", new Blob(["img"]), "test.jpg");

      const result = await updateProfilePicture(formData);

      expect(result).toEqual({ success: true });
      expect(fetchApi).toHaveBeenCalledWith("/profile", {
        method: "PATCH",
        body: formData,
      });
      expect(revalidatePath).toHaveBeenCalledWith("/stamboken/profil");
    });

    it("returns error on ApiError", async () => {
      const err = new (ApiError as any)({
        status: 413,
        title: "Too large",
        detail: "File too large",
      });
      vi.mocked(fetchApi).mockRejectedValue(err);
      const formData = new FormData();

      const result = await updateProfilePicture(formData);

      expect(result).toEqual({ success: false, error: "File too large" });
      expect(revalidatePath).not.toHaveBeenCalled();
    });

    it("returns error on legacy 200 error response", async () => {
      vi.mocked(fetchApi).mockResolvedValue({
        status: "error",
        message: "Failed to upload image",
      });
      const formData = new FormData();

      const result = await updateProfilePicture(formData);

      expect(result).toEqual({
        success: false,
        error: "Failed to upload image",
      });
      expect(revalidatePath).not.toHaveBeenCalled();
    });
  });

  describe("updateSettings", () => {
    it("calls fetchApi with JSON and revalidates", async () => {
      vi.mocked(fetchApi).mockResolvedValue({ status: "updated" });

      const result = await updateSettings({ use_google_picture: true });

      expect(result).toEqual({ success: true });
      expect(fetchApi).toHaveBeenCalledWith("/profile", {
        method: "PATCH",
        body: JSON.stringify({ use_google_picture: true }),
      });
      expect(revalidatePath).toHaveBeenCalledWith("/stamboken/profil");
    });

    it("returns error on ApiError", async () => {
      const err = new (ApiError as any)({
        status: 500,
        title: "Server Error",
        detail: "Failed to update profile",
      });
      vi.mocked(fetchApi).mockRejectedValue(err);

      const result = await updateSettings({ use_google_picture: false });

      expect(result).toEqual({
        success: false,
        error: "Failed to update profile",
      });
    });

    it("returns error on legacy 200 error response", async () => {
      vi.mocked(fetchApi).mockResolvedValue({
        status: "error",
        message: "Failed to update profile",
      });

      const result = await updateSettings({ use_google_picture: true });

      expect(result).toEqual({
        success: false,
        error: "Failed to update profile",
      });
      expect(revalidatePath).not.toHaveBeenCalled();
    });
  });
});
