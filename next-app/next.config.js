import { withPayload } from "@payloadcms/next/withPayload";
import path from "path";
import { fileURLToPath } from "url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  transpilePackages: ["react-easy-crop"],
  experimental: {
    // Intyg uploads go through a Server Action: up to 10 photos of ≤10 MB.
    // Next.js only has this limit globally (no per-action setting), so every
    // Server Action accepts 11 MB; Flask enforces the real limits per endpoint.
    serverActions: { bodySizeLimit: "11mb" },
    optimizePackageImports: ["@mui/material", "@mui/icons-material"],
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
