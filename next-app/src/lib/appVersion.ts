// The release tag the image was built from (APP_VERSION in .docker/next-app): "2.13.0" for a
// release, "main" or "dev" otherwise. Shown in the footers so anyone can see what runs.
export function appVersion(raw: string | undefined = process.env.NEXT_PUBLIC_APP_VERSION): {
  label: string;
  href: string;
} {
  const v = raw?.trim() || "dev";
  const release = /^\d+\.\d+\.\d+$/.test(v);
  return {
    label: release ? `v${v}` : v,
    href: release
      ? `https://github.com/gotlandskaninen/stamboken/releases/tag/v${v}`
      : "https://github.com/gotlandskaninen/stamboken",
  };
}
