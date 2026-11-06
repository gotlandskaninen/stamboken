import { describe, it, expect } from "vitest";
import { getErrorDetails, getUserFriendlyMessage } from "@/utils/errorHandling";

describe("getErrorDetails", () => {
  it("handles network errors (FETCH_ERROR)", () => {
    const error = {
      status: "FETCH_ERROR",
      error: "TypeError: Failed to fetch",
    };
    const details = getErrorDetails(error);
    expect(details.errorType).toBe("Network Error");
    expect(details.message).toContain("servern");
  });

  it("handles timeout errors", () => {
    const error = { status: "TIMEOUT_ERROR" };
    const details = getErrorDetails(error);
    expect(details.errorType).toBe("Timeout");
    expect(details.message).toContain("lång tid");
  });

  it("handles HTTP 401", () => {
    const error = { status: 401, data: {} };
    const details = getErrorDetails(error);
    expect(details.message).toContain("logga in");
  });

  it("handles HTTP 403", () => {
    const error = { status: 403, data: {} };
    const details = getErrorDetails(error);
    expect(details.message).toContain("nekad");
  });

  it("handles HTTP 404", () => {
    const error = { status: 404, data: {} };
    const details = getErrorDetails(error);
    expect(details.message).toContain("hittades inte");
  });

  it("handles HTTP 500", () => {
    const error = { status: 500, data: { message: "Internal error" } };
    const details = getErrorDetails(error);
    expect(details.message).toContain("Serverfel");
  });

  it("handles null/undefined errors", () => {
    const details = getErrorDetails(null);
    expect(details.errorType).toBe("Null/Undefined Error");
  });

  it("includes timestamp and defaults", () => {
    const details = getErrorDetails({});
    expect(details.timestamp).toBeDefined();
    expect(details.userId).toBe("unknown");
  });
});

describe("getUserFriendlyMessage", () => {
  it("returns Swedish message for network error", () => {
    const msg = getUserFriendlyMessage({ status: "FETCH_ERROR" });
    expect(msg).toContain("servern");
  });

  it("returns Swedish message for timeout", () => {
    const msg = getUserFriendlyMessage({ status: "TIMEOUT_ERROR" });
    expect(msg).toContain("lång tid");
  });

  it("returns fallback for unknown errors", () => {
    const msg = getUserFriendlyMessage({});
    expect(typeof msg).toBe("string");
    expect(msg.length).toBeGreaterThan(0);
  });
});
