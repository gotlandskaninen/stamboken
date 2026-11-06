import { describe, it, expect } from "vitest";
import {
  shouldRetry,
  isExpired,
  MAX_ATTEMPTS,
  MAX_AGE_MS,
} from "@/utils/uploadRetryQueue";

describe("uploadRetryQueue policy", () => {
  it("stops retrying after MAX_ATTEMPTS", () => {
    expect(shouldRetry({ attempts: MAX_ATTEMPTS })).toBe(false);
    expect(shouldRetry({ attempts: MAX_ATTEMPTS - 1 })).toBe(true);
  });
  it("treats items with no attempts recorded as retryable", () => {
    expect(shouldRetry({})).toBe(true);
  });
  it("treats items older than MAX_AGE_MS as expired", () => {
    expect(isExpired({ timestamp: 0 }, MAX_AGE_MS + 1)).toBe(true);
    expect(isExpired({ timestamp: 100 }, 100 + MAX_AGE_MS - 1)).toBe(false);
  });
});
