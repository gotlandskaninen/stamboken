import { describe, expect, it } from "vitest";
import {
  noticeHref,
  planImage,
  statusText,
  warningText,
  type InskickStatus,
} from "@/lib/inkorg";
import {
  badgeKey,
  badgeLabel,
  navItemsFor,
} from "@/components/shell/nav-items";

describe("statusText", () => {
  it.each<[InskickStatus, string]>([
    ["mottaget", "Mottaget"],
    ["under_arbete", "Under arbete"],
    ["fragat", "Vi har frågat dig något"],
    ["klart", "Klart"],
    ["avslutat", "Avslutat"],
  ])("%s -> %s", (status, text) => {
    expect(statusText(status)).toBe(text);
  });

  it("passes an unknown status through", () => {
    expect(statusText("nytt_lage")).toBe("nytt_lage");
  });
});

describe("planImage", () => {
  it("sends a PDF unchanged", () => {
    expect(planImage("application/pdf", null)).toEqual({ action: "keep" });
  });

  it("sends an image the browser cannot decode unchanged", () => {
    expect(planImage("image/heic", null)).toEqual({ action: "keep" });
  });

  it("keeps a JPEG already within 3000 px", () => {
    expect(planImage("image/jpeg", { width: 3000, height: 2000 })).toEqual({
      action: "keep",
    });
  });

  it("scales a large landscape photo to 3000 px on the long side", () => {
    expect(planImage("image/jpeg", { width: 4032, height: 3024 })).toEqual({
      action: "resize",
      width: 3000,
      height: 2250,
    });
  });

  it("scales a large portrait photo to 3000 px on the long side", () => {
    expect(planImage("image/jpeg", { width: 3024, height: 4032 })).toEqual({
      action: "resize",
      width: 2250,
      height: 3000,
    });
  });

  it("re-encodes a small PNG as JPEG at its own size", () => {
    expect(planImage("image/png", { width: 1000, height: 800 })).toEqual({
      action: "resize",
      width: 1000,
      height: 800,
    });
  });
});

describe("warningText", () => {
  it("uses the house wording for blur", () => {
    expect(warningText("suddig")).toBe("Bilden ser suddig ut. Ta om den?");
  });

  it("has a fallback for an unknown code", () => {
    expect(warningText("nytt")).toMatch(/Ta om den/);
  });
});

describe("noticeHref", () => {
  it("sends klar notices to Mina inskick", () => {
    expect(noticeHref({ kind: "klar", item_id: 7 })).toBe(
      "/stamboken/inskick#arende-7",
    );
  });

  it("sends queue notices to the item in the inbox", () => {
    expect(noticeHref({ kind: "ny_post", item_id: 7 })).toBe(
      "/stamboken/inkorg/7",
    );
  });
});

describe("nav visibility and badge", () => {
  const keys = (w: boolean) => navItemsFor(w).map((i) => i.key);

  it("shows Mina inskick to everyone and no Inkorg to non-workers", () => {
    expect(keys(false)).toContain("inskick");
    expect(keys(false)).not.toContain("inkorg");
  });

  it("shows Inkorg to queue workers", () => {
    expect(keys(true)).toContain("inskick");
    expect(navItemsFor(true).find((i) => i.key === "inkorg")?.href).toBe(
      "/stamboken/inkorg",
    );
  });

  it("puts the badge on Inkorg for workers and on Mina inskick otherwise", () => {
    expect(badgeKey(true)).toBe("inkorg");
    expect(badgeKey(false)).toBe("inskick");
  });

  it("formats the unread count", () => {
    expect(badgeLabel(0)).toBeNull();
    expect(badgeLabel(3)).toBe("3");
    expect(badgeLabel(120)).toBe("99+");
  });
});
