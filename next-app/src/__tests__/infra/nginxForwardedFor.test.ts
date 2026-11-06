import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

// next-app hands the last X-Forwarded-For entry to Flask's rate limiter,
// so nginx must overwrite/append it on EVERY location that proxies to next-app.
// A location that sets neither lets the client send its own address, e.g. a
// server action POSTed to /_next/probe, which Next forwards to the page that
// owns the action.
const NGINX_DIR = path.resolve(__dirname, "../../../../nginx");

function confFiles(): string[] {
  return fs
    .readdirSync(NGINX_DIR, { recursive: true, encoding: "utf8" })
    .filter((f) => f.endsWith(".conf"))
    .sort();
}

/** Every `location … { … }` block that proxies to next-app, comments removed. */
function nextAppLocations(conf: string) {
  const lines = conf.split("\n").filter((l) => !l.trim().startsWith("#"));
  const found: { header: string; body: string }[] = [];
  for (let i = 0; i < lines.length; i++) {
    if (!/^\s*location\s.*\{\s*$/.test(lines[i])) continue;
    let depth = 0;
    const body: string[] = [];
    for (let j = i; j < lines.length; j++) {
      body.push(lines[j]);
      depth += (lines[j].match(/\{/g) ?? []).length;
      depth -= (lines[j].match(/\}/g) ?? []).length;
      if (depth <= 0) break;
    }
    const text = body.join("\n");
    if (/proxy_pass\s+http:\/\/(nextjs|next-app)\b/.test(text)) {
      found.push({ header: lines[i].trim(), body: text });
    }
  }
  return found;
}

describe("nginx forwarding headers for next-app", () => {
  const files = confFiles();

  it("finds the nginx configs", () => {
    expect(files).toContain("production/herdbook-production.conf");
  });

  describe.each(files)("%s", (file) => {
    const locations = nextAppLocations(
      fs.readFileSync(path.join(NGINX_DIR, file), "utf8"),
    );

    it.each(locations.map((l) => [l.header, l.body]))(
      "%s sets X-Real-IP and X-Forwarded-For",
      (_header, body) => {
        expect(body).toMatch(/proxy_set_header\s+X-Real-IP\s+\$remote_addr;/);
        // $http_x_forwarded_for would hand the client's own header through.
        expect(body).toMatch(
          /proxy_set_header\s+X-Forwarded-For\s+(\$proxy_add_x_forwarded_for|\$remote_addr);/,
        );
      },
    );
  });
});
