import { describe, it, expect, afterEach } from "vitest";
import { parseMode, readModeCookieClient, MODE_COOKIE } from "@/lib/mode";

describe("parseMode", () => {
  it("returns 'prod' for the exact string 'prod'", () => {
    expect(parseMode("prod")).toBe("prod");
  });

  it("returns 'demo' for the exact string 'demo'", () => {
    expect(parseMode("demo")).toBe("demo");
  });

  it("fail-safe defaults to 'demo' for undefined", () => {
    expect(parseMode(undefined)).toBe("demo");
  });

  it("is case-sensitive: 'PROD' is not on the allow-list, defaults to 'demo'", () => {
    expect(parseMode("PROD")).toBe("demo");
  });

  it("defaults to 'demo' for any unknown value", () => {
    expect(parseMode("anything-else")).toBe("demo");
  });

  it("defaults to 'demo' for the empty string", () => {
    expect(parseMode("")).toBe("demo");
  });
});

describe("readModeCookieClient", () => {
  afterEach(() => {
    // Clear the sb_mode cookie between tests (jsdom persists document.cookie).
    document.cookie = `${MODE_COOKIE}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });

  it("returns parseMode() of the sb_mode value = 'prod'", () => {
    document.cookie = `${MODE_COOKIE}=prod`;
    expect(readModeCookieClient()).toBe("prod");
  });

  it("returns 'demo' when sb_mode=demo", () => {
    document.cookie = `${MODE_COOKIE}=demo`;
    expect(readModeCookieClient()).toBe("demo");
  });

  it("returns 'demo' (fail-safe) when sb_mode cookie is absent", () => {
    expect(readModeCookieClient()).toBe("demo");
  });

  it("returns 'demo' for a tampered/unknown sb_mode value", () => {
    document.cookie = `${MODE_COOKIE}=hacked`;
    expect(readModeCookieClient()).toBe("demo");
  });

  it("extracts sb_mode from among other cookies", () => {
    document.cookie = "other=1";
    document.cookie = `${MODE_COOKIE}=prod`;
    document.cookie = "another=2";
    expect(readModeCookieClient()).toBe("prod");
  });
});
