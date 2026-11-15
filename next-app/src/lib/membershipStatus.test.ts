import { describe, expect, it } from "vitest";
import {
  CREATABLE_STATUSES,
  MEMBERSHIP_STATUS,
  MEMBERSHIP_STATUSES,
  isMembershipStatus,
  statusBadge,
  statusLabel,
} from "./membershipStatus";

describe("membershipStatus", () => {
  it("has a table entry for every status", () => {
    expect(Object.keys(MEMBERSHIP_STATUS).sort()).toEqual(
      [...MEMBERSHIP_STATUSES].sort(),
    );
  });

  it("offers every status but inactive when creating", () => {
    expect(CREATABLE_STATUSES).toEqual(["active", "pending", "friexemplar"]);
  });

  it("guards unknown values and renders them as-is", () => {
    expect(isMembershipStatus("pending")).toBe(true);
    expect(isMembershipStatus("archived")).toBe(false);
    expect(isMembershipStatus(undefined)).toBe(false);
    expect(statusLabel("archived")).toBe("archived");
    expect(statusBadge("archived", "w")).toEqual({
      label: "archived",
      className: "sb-badge",
    });
  });

  it("resolves badge classes, the warning one from the caller's module", () => {
    expect(statusBadge("active", "w").className).toBe("sb-badge sb-badge-skog");
    expect(statusBadge("pending", "w")).toEqual({
      label: "Väntar",
      className: "sb-badge w",
    });
    expect(statusBadge("inactive", "w").className).toBe("sb-badge");
    expect(statusBadge("friexemplar", "w").className).toBe(
      "sb-badge sb-badge-himmel",
    );
  });
});
