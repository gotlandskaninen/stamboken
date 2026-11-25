import type { MetadataRoute } from "next";

// Served as /manifest.webmanifest, and Next links it on every page; both only
// from the app root, not from a route group. public/static/manifest.json is the
// old copy and no longer linked; the legacy hosts serve their own build (#220).
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
