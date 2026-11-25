import type { MetadataRoute } from "next";

// Served as /manifest.webmanifest; Next links it on every page itself. The
// legacy SPA keeps its own manifest under /static/ (#220).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Stamboken",
    short_name: "Stamboken",
    start_url: "/stamboken",
    scope: "/",
    display: "standalone",
    // --sb-skog and --sb-paper in src/styles/tokens.css
    theme_color: "#2F4A32",
    background_color: "#F4F1EA",
    icons: [
      {
        src: "/static/img/icons/android-chrome-192x192.png",
        sizes: "192x192",
        type: "image/png",
      },
      {
        src: "/static/img/icons/android-chrome-512x512.png",
        sizes: "512x512",
        type: "image/png",
      },
    ],
  };
}
