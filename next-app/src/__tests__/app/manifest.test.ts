import { describe, it, expect } from "vitest";
import manifest from "@/app/manifest";

// The old manifest's start_url "." resolved to /static/, which looped (#220).
describe("web app manifest", () => {
  it("opens the dashboard", () => {
    const m = manifest();
    expect(m.start_url).toBe("/stamboken");
    expect(m.scope).toBe("/");
    expect(m.display).toBe("standalone");
  });
});
