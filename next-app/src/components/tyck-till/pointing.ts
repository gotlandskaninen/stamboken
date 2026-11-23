import { toCanvas } from "html-to-image";

// Marks what never goes into the picture or the description (the code of a certificate).
export const HIDE = '[data-tyck-till="dolj"]';
const MAX_SIDE = 2000;
const BACKGROUND = "#F4F1EA";

// What a tap may land on: the nearest of these around the element under the finger.
const PICKABLE =
  "button, a, input, textarea, select, label, li, tr, .facts > div, h1, h2, p, img, .card";

export function pickable(hit: Element): Element {
  return hit.closest(PICKABLE) ?? hit;
}

function kindOf(el: Element): string {
  if (el.matches("button")) return "knappen";
  if (el.matches("a")) return "länken";
  if (el.matches("h1, h2")) return "rubriken";
  if (el.matches("input, textarea, select")) return "fältet";
  if (el.matches("li, tr, .facts > div")) return "raden";
  if (el.matches("img")) return "bilden";
  if (el.matches(".card")) return "rutan";
  return "texten";
}

export function describe(el: Element): string {
  if (el.closest(HIDE)) return "en dold uppgift";
  const clone = el.cloneNode(true) as Element;
  clone.querySelectorAll(HIDE).forEach((n) => n.remove());
  let t = (
    el.getAttribute("aria-label") ||
    (el.matches("input, textarea, select") && (el as HTMLInputElement).value) ||
    clone.textContent ||
    el.getAttribute("alt") ||
    ""
  )
    .replace(/\s+/g, " ")
    .trim();
  if (t.length > 50) t = t.slice(0, 50) + "…";
  return kindOf(el) + (t ? ` ”${t}”` : "");
}

function fit(w: number, h: number): [number, number] {
  const k = Math.min(1, MAX_SIDE / Math.max(w, h));
  return [Math.round(w * k), Math.round(h * k)];
}

function jpeg(
  w: number,
  h: number,
  draw: (ctx: CanvasRenderingContext2D) => void,
): Promise<Blob | null> {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return Promise.resolve(null);
  draw(ctx);
  return new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.85));
}

/**
 * A region about 4:5 around `el`, so the preview stays readable on a phone, as
 * JPEG within MAX_SIDE. Null when the browser cannot draw the page.
 */
export async function captureAround(
  el: Element,
  root: HTMLElement,
): Promise<Blob | null> {
  try {
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const full = await toCanvas(root, {
      pixelRatio: ratio,
      backgroundColor: BACKGROUND,
      filter: (n) => !(n instanceof Element && n.closest(HIDE)),
    });
    const pr = root.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    const pageH = pr.height;
    const h = Math.min(
      window.innerHeight,
      Math.round(pr.width * 1.25),
      pageH || Infinity,
    );
    const top = Math.max(
      0,
      Math.min(er.top - pr.top + er.height / 2 - h / 2, pageH - h),
    );
    // html-to-image shrinks a canvas over 16384 px, so the scale is read off the canvas.
    const scale = pageH ? full.height / pageH : ratio;
    const sy = Math.round(top * scale);
    const sh = Math.min(Math.round(h * scale), full.height - sy);
    const [w, oh] = fit(full.width, sh);
    return await jpeg(w, oh, (ctx) =>
      ctx.drawImage(full, 0, sy, full.width, sh, 0, 0, w, oh),
    );
  } catch (err) {
    console.warn("Bildtagningen misslyckades", err);
    return null;
  }
}

/**
 * JPEG, 2000 px at most on the longest side. What the browser cannot draw
 * (HEIC in Chrome) goes unchanged; the API takes it.
 */
export async function shrink(file: Blob): Promise<Blob> {
  let bitmap: ImageBitmap;
  try {
    // "from-image" applies the EXIF orientation; the JPEG has none.
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return file;
  }
  try {
    const [w, h] = fit(bitmap.width, bitmap.height);
    return (
      (await jpeg(w, h, (ctx) => ctx.drawImage(bitmap, 0, 0, w, h))) ?? file
    );
  } finally {
    bitmap.close();
  }
}
