import type { MetadataRoute } from "next";

// Served as /manifest.webmanifest (only from the app root, not a route group)
// and linked from the (app) layout's metadata.
// The legacy SPA keeps its own manifest under /static/ (#220).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Stamboken",
    short_name: "Stamboken",
    start_url: "/stamboken/min-besattning",
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
