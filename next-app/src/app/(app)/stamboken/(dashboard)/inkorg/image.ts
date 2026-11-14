// Image tools of the working view: the masking rectangles and the pencil
// enhancement. Rectangles are fractions of the image after rotation, as
// …/maskning takes them (docs/inkorg.md, "Maskning och kopian på kaninen").
import type { InboxDocument, Rect } from "./lib";

export const MAX_RECTS = 20;
const MIN_SIZE = 0.02;
/** The seller and buyer block of the green certificate: its lower third. */
export const LOWER_THIRD: Rect = { x: 0, y: 0.6667, w: 1, h: 0.3333 };

const clamp = (v: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, v));

/** Moved by (dx, dy), kept inside the image. */
export const moveRect = (r: Rect, dx: number, dy: number): Rect => ({
  ...r,
  x: clamp(r.x + dx, 0, 1 - r.w),
  y: clamp(r.y + dy, 0, 1 - r.h),
});

/** The lower right corner moved by (dw, dh); never smaller than MIN_SIZE nor outside the image. */
export const resizeRect = (r: Rect, dw: number, dh: number): Rect => ({
  ...r,
  w: clamp(r.w + dw, MIN_SIZE, 1 - r.x),
  h: clamp(r.h + dh, MIN_SIZE, 1 - r.y),
});

/** The same area after the image is turned `quarterTurns` × 90° clockwise (negative: counter-clockwise). */
export function rotateRect(r: Rect, quarterTurns: number): Rect {
  let out = r;
  for (let i = 0; i < ((quarterTurns % 4) + 4) % 4; i++)
    out = { x: 1 - out.y - out.h, y: out.x, w: out.h, h: out.w };
  return out;
}

export const turn = (rotation: number, quarterTurns: number) =>
  (((rotation + quarterTurns * 90) % 360) + 360) % 360;

const round4 = (v: number) => Math.round(v * 10000) / 10000;

/** The API's form: at most 20, four decimals, and never past the edge after rounding. */
export const toApiRects = (rects: Rect[]): Rect[] =>
  rects.slice(0, MAX_RECTS).map((r) => {
    const x = round4(clamp(r.x, 0, 1));
    const y = round4(clamp(r.y, 0, 1));
    return {
      x,
      y,
      w: Math.min(round4(r.w), round4(1 - x)),
      h: Math.min(round4(r.h), round4(1 - y)),
    };
  });

/** What the masking step starts from: the saved rectangles, the API's suggestion, or the lower third. */
export const initialRects = (
  doc: Pick<InboxDocument, "mask_rects" | "mask_suggestion">,
): Rect[] => doc.mask_rects ?? doc.mask_suggestion ?? [LOWER_THIRD];

/**
 * "Förstärk blyerts", in place on RGBA pixels: the green channel (the form is
 * printed in green, so the print fades and the pencil stays) as grey,
 * stretched so that the 1st and 99th percentiles become black and white.
 */
export function enhancePencil(px: Uint8ClampedArray): void {
  const hist = new Uint32Array(256);
  const n = px.length / 4;
  for (let i = 1; i < px.length; i += 4) hist[px[i]]++;
  const level = (share: number) => {
    let seen = 0;
    for (let v = 0; v < 256; v++) if ((seen += hist[v]) > n * share) return v;
    return 255;
  };
  const lo = level(0.01);
  const span = Math.max(1, level(0.99) - lo);
  for (let i = 0; i < px.length; i += 4) {
    const v = ((px[i + 1] - lo) * 255) / span; // the clamped array clamps and rounds
    px[i] = px[i + 1] = px[i + 2] = v;
  }
}
