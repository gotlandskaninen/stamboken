import type { JSXConvertersFunction } from "@payloadcms/richtext-lexical/react";

/**
 * Only root-relative paths (not protocol-relative `//host`) and explicit
 * http(s) URLs are safe to put in an href. Payload generates these media urls
 * so a `javascript:`/`data:` url cannot realistically reach here, but this
 * converter renders CMS content into an anchor, so we allowlist anyway —
 * unsafe urls fall back to plain text instead of a clickable link.
 */
function isSafeHref(url: string): boolean {
  return (
    (url.startsWith("/") && !url.startsWith("//")) || /^https?:\/\//i.test(url)
  );
}

/**
 * Shared JSX converters for public RichText rendering.
 *
 * Overrides only the `upload` node (inline images inserted via the Lexical
 * UploadFeature). The default converter renders a fixed-size <img>/<picture>
 * with no responsive constraint, so a large original overflows the column on
 * mobile; its <picture> sources also point at our center-cropped `thumbnail`/
 * `card` sizes (Media.ts uses position: "centre"), which would show a cropped
 * image on small screens. We instead render the uncropped original as a
 * responsive, lazy-loaded <img>, with the Media caption as a <figcaption>
 * when one is set. Non-image uploads keep the default behaviour
 * (a download link). All other nodes use the package defaults.
 */
export const richTextConverters: JSXConvertersFunction = ({
  defaultConverters,
}) => ({
  ...defaultConverters,
  upload: ({ node }) => {
    const media = node.value;
    if (typeof media !== "object" || media === null) return null;

    const { url, mimeType, filename, width, height, caption } = media as {
      url?: string | null;
      mimeType?: string | null;
      filename?: string | null;
      width?: number | null;
      height?: number | null;
      caption?: string | null;
    };
    if (!url) return null;

    // Per-insertion alt override wins, then the Media doc's alt-text.
    const alt =
      (node.fields as { alt?: string } | undefined)?.alt ??
      (media as { alt?: string }).alt ??
      "";

    if (!mimeType?.startsWith("image")) {
      const label = filename ?? url;
      return isSafeHref(url) ? (
        <a href={url} rel="noopener noreferrer">
          {label}
        </a>
      ) : (
        <>{label}</>
      );
    }

    const img = (
      // next/image is avoided on purpose: it needs intrinsic width/height and
      // would break on the SVGs Media.ts allows, and would require remotePatterns
      // config for the dynamic Payload media url. A plain <img> renders every
      // allowed mime (incl. SVG) with no extra config.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt={alt}
        width={width ?? undefined}
        height={height ?? undefined}
        loading="lazy"
        decoding="async"
        style={{
          display: "block",
          maxWidth: "100%",
          height: "auto",
          margin: caption ? "0 auto" : "1.5rem auto",
          borderRadius: 8,
        }}
      />
    );
    if (!caption) return img;

    return (
      <figure style={{ margin: "1.5rem 0" }}>
        {img}
        <figcaption
          className="sb-meta"
          style={{ marginTop: 8, textAlign: "center" }}
        >
          {caption}
        </figcaption>
      </figure>
    );
  },
});
