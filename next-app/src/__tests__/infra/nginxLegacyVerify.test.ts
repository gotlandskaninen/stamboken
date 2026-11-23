import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

// A v1 digital certificate's QR code points at HERDBOOK_HOST +
// /individual/<number>/verify. When that host is the public one, nginx must
// send the scan on to the legacy app, which is the only one that answers it.
const CONF = path.resolve(
  __dirname,
  "../../../../nginx/production/gotlandskaninen.conf",
);

describe("v1 certificate QR on the public host", () => {
  const conf = fs.readFileSync(CONF, "utf8");
  const match = conf.match(
    /^\s*location ~ (\S+) \{\s*\n\s*return 301 (\S+);\s*\n\s*\}/m,
  );

  it("has a regex location that redirects to the legacy host", () => {
    expect(match?.[2]).toBe("https://stamboken.gotlandskaninen.se$request_uri");
  });

  it.each([
    ["/individual/G1234-2102/verify", true],
    ["/individual/M12-2201/verify", true],
    ["/individual/G1234-2102/verify/extra", false],
    ["/individual//verify", false],
    ["/stamboken/verifiera/9b2f0c1e-0000-4000-8000-000000000000", false],
  ])("%s → %s", (url, redirected) => {
    expect(new RegExp(match![1]).test(url)).toBe(redirected);
  });
});
