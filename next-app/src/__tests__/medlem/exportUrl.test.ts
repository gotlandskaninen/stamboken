import { describe, it, expect } from "vitest";
import {
  koharenExportUrl,
  memberExportUrl,
} from "@/app/(app)/medlem/statistik/exportUrl";

describe("memberExportUrl", () => {
  it("uses /api in prod mode", () => {
    expect(memberExportUrl("prod", "/api-test")).toBe("/api/v2/members/export");
  });

  it("routes demo mode to the configured test URL", () => {
    expect(memberExportUrl("demo", "/api-test")).toBe(
      "/api-test/v2/members/export",
    );
  });

  it("falls back to /api in demo mode when no test URL is configured (base dev)", () => {
    expect(memberExportUrl("demo", undefined)).toBe("/api/v2/members/export");
  });
});

describe("koharenExportUrl", () => {
  it("uses /api in prod mode", () => {
    expect(koharenExportUrl("prod", undefined)).toBe(
      "/api/v2/members/koharen-export",
    );
  });

  it("routes demo mode to the configured test URL", () => {
    expect(koharenExportUrl("demo", "https://demo.example")).toBe(
      "https://demo.example/v2/members/koharen-export",
    );
  });
});
