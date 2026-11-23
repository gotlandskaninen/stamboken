import { describe, expect, it } from "vitest";
import { appVersion } from "@/lib/appVersion";

describe("appVersion", () => {
  it("links a release to its tag", () => {
    expect(appVersion("2.13.0")).toEqual({
      label: "v2.13.0",
      href: "https://github.com/gotlandskaninen/stamboken/releases/tag/v2.13.0",
    });
  });
  it("shows main and dev builds without a tag link", () => {
    expect(appVersion("main").href).toBe("https://github.com/gotlandskaninen/stamboken");
    expect(appVersion(undefined).label).toBe("dev");
    expect(appVersion("  ").label).toBe("dev");
  });
});
