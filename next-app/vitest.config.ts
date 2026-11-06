import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "jsdom",
    // .next/dev/node_modules symlinks into the pnpm store — without the
    // exclude, vitest collects Payload's own *.spec.ts through them.
    exclude: ["e2e/**", "e2e-legacy/**", "node_modules/**", ".next/**"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
