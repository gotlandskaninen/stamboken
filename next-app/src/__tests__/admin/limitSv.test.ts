import { describe, it, expect } from "vitest";
import {
  functionLabel,
  limitSv,
} from "@/app/(app)/stamboken/(dashboard)/admin/_lib/limitSv";

describe("limitSv", () => {
  it("formats the app-default shape (count + explicit multiple)", () => {
    // app/extensions.py:10 defaults via str(RateLimitItem).
    expect(limitSv("1000 per 1 hour")).toBe("1000 anrop per timme");
    expect(limitSv("100 per 1 minute")).toBe("100 anrop per minut");
  });

  it("formats the decorated-route shape (unit only, no multiple)", () => {
    expect(limitSv("10 per hour")).toBe("10 anrop per timme");
    expect(limitSv("5 per minute")).toBe("5 anrop per minut");
    expect(limitSv("50 per minute")).toBe("50 anrop per minut");
  });

  it("keeps a multi-unit window plural", () => {
    expect(limitSv("20 per 10 seconds")).toBe("20 anrop per 10 sekunder");
    expect(limitSv("2 per 3 days")).toBe("2 anrop per 3 dygn");
  });

  it("falls back to the raw string when the shape is unknown", () => {
    expect(limitSv("1000 per hour;100 per minute")).toBe(
      "1000 per hour;100 per minute",
    );
    expect(limitSv("")).toBe("");
  });
});

describe("functionLabel", () => {
  it("translates known endpoint ids, bare and module-qualified", () => {
    expect(functionLabel("default")).toBe("Standardgräns (alla anrop)");
    expect(functionLabel("blueprints.admin.admin_reset_password")).toBe(
      "Återställ lösenord (admin)",
    );
    expect(functionLabel("member_applications.create_application")).toBe(
      "Medlemsansökan",
    );
  });

  it("falls back to the raw endpoint id", () => {
    expect(functionLabel("some.unknown.endpoint")).toBe(
      "some.unknown.endpoint",
    );
  });
});
