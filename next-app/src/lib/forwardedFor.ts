import { isIP } from "node:net";

/**
 * X-Forwarded-For for a server-side call to Flask, taken from the request
 * next-app is serving. Flask-Limiter keys on remote_addr behind
 * ProxyFix(x_for=1), which trusts the LAST X-Forwarded-For entry. nginx puts
 * the browser's address there, so without this header every user arrives as the
 * next-app container and shares one rate-limit bucket per endpoint.
 *
 * Forward that last entry alone, and only if it is an IP address. Werkzeug
 * reads a header such as `"x, 203.0.113.9` as ONE entry, so passing the chain
 * on whole would let a client choose its own limiter key. X-Real-IP is the
 * fallback. Both are only trustworthy because every nginx location that
 * proxies to next-app sets them (nginx test in __tests__/infra) and production
 * publishes no port for next-app.
 */
export function forwardedFor(
  incoming: Pick<Headers, "get">,
): Record<string, string> {
  const last = incoming.get("x-forwarded-for")?.split(",").pop()?.trim();
  const ip = [last, incoming.get("x-real-ip")?.trim()].find(
    (candidate) => candidate && isIP(candidate),
  );
  return ip ? { "X-Forwarded-For": ip } : {};
}
