import { withPayload } from "@payloadcms/next/withPayload";
import path from "path";
import { fileURLToPath } from "url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // The matrikel guide is read from disk outside public/ (it is not public).
  outputFileTracingIncludes: {
    "/medlem/guide": ["./content/matrikel-guide/**/*"],
    "/medlem/guide/bild/[name]": ["./content/matrikel-guide/**/*"],
  },
  transpilePackages: ["react-easy-crop"],
  experimental: {
    // Intyg uploads go through a Server Action. Next.js only has this limit
    // globally (no per-action setting). nginx cuts every request at 50 MiB
    // before it gets here, so 50mb is all that can arrive; Flask enforces the
    // real limits per endpoint, and the upload form keeps the files to 48 MB.
    serverActions: { bodySizeLimit: "50mb" },
    // The middleware (src/middleware.ts) runs on /stamboken/*, where those
    // actions post, and Next.js buffers only 10 MB of a body for it by default.
    proxyClientMaxBodySize: "50mb",
    optimizePackageImports: ["@mui/material", "@mui/icons-material"],
  },
  // The buyer's erase link carries its token in the fragment, which no server
  // sees; the page is never cached nor named in a referrer either.
  async headers() {
    return [
      {
        source: "/kopare/:path*",
        headers: [
          { key: "Cache-Control", value: "no-store" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
  async rewrites() {
    const apiUrl = process.env.API_INTERNAL_URL || "http://localhost:9090";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
  turbopack: {
    rules: {
      "*.svg": {
        loaders: [
          {
            loader: "@svgr/webpack",
            options: {
              svgoConfig: {
                plugins: [
                  {
                    name: "preset-default",
                    params: {
                      overrides: {
                        removeViewBox: false,
                      },
                    },
                  },
                ],
              },
            },
          },
        ],
        as: "*.js",
      },
    },
  },
};

export default withPayload(nextConfig);
