import { withPayload } from "@payloadcms/next/withPayload";
import path from "path";
import { fileURLToPath } from "url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  transpilePackages: ["react-easy-crop"],
  experimental: {
    // Intyg uploads go through a Server Action. Next.js only has this limit
    // globally (no per-action setting). nginx cuts every request at 10 MiB
    // before it gets here, so 10mb is all that can arrive; Flask enforces the
    // real limits per endpoint, and the upload form keeps the files to 9 MB.
    serverActions: { bodySizeLimit: "10mb" },
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
