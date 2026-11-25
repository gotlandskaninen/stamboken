import { describe, expect, it } from "vitest";
import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { config } from "../middleware";

// The personal report link (/rapport) is for people with no account: the sign-in redirect must never match it.
describe("middleware matcher", () => {
  const matches = (url: string) =>
    unstable_doesMiddlewareMatch({ config, nextConfig: {}, url });
  it("leaves /rapport and /rapport/ogiltig alone", () => {
    expect(matches("/rapport")).toBe(false);
    expect(matches("/rapport?kod=3")).toBe(false);
    expect(matches("/rapport/ogiltig")).toBe(false);
  });
  it("still guards the dashboard", () => {
    expect(matches("/stamboken/arsrapport")).toBe(true);
  });
});
