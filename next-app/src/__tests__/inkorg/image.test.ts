import { describe, expect, it } from "vitest";
import {
  enhancePencil,
  initialRects,
  LOWER_THIRD,
  MAX_RECTS,
  moveRect,
  resizeRect,
  rotateRect,
  toApiRects,
  turn,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/image";

const r = { x: 0.1, y: 0.2, w: 0.3, h: 0.4 };
const close = (a: object, b: object) =>
  Object.entries(b).forEach(([k, v]) =>
    expect((a as Record<string, number>)[k]).toBeCloseTo(v as number, 9),
  );

describe("moveRect", () => {
  it("moves", () =>
    close(moveRect(r, 0.1, -0.1), { x: 0.2, y: 0.1, w: 0.3, h: 0.4 }));
  it("stops at every edge without changing the size", () => {
    close(moveRect(r, -1, -1), { x: 0, y: 0, w: 0.3, h: 0.4 });
    close(moveRect(r, 1, 1), { x: 0.7, y: 0.6, w: 0.3, h: 0.4 });
  });
});

describe("resizeRect", () => {
  it("grows and shrinks from the lower right corner", () =>
    close(resizeRect(r, 0.1, -0.1), { x: 0.1, y: 0.2, w: 0.4, h: 0.3 }));
  it("never past the image, never below the minimum", () => {
    close(resizeRect(r, 5, 5), { w: 0.9, h: 0.8 });
    close(resizeRect(r, -5, -5), { w: 0.02, h: 0.02 });
  });
});

describe("rotateRect", () => {
  it("a quarter turn clockwise takes the bottom band to the left edge", () =>
    close(rotateRect(LOWER_THIRD, 1), { x: 0, y: 0, w: 0.3333, h: 1 }));
  it("a half turn takes the bottom band to the top", () =>
    close(rotateRect(LOWER_THIRD, 2), { x: 0, y: 0, w: 1, h: 0.3333 }));
  it("follows the content of an off-centre rectangle", () => {
    // Point (0.1, 0.2) in a W×H image is at (1 - 0.2, 0.1) after 90° clockwise.
    close(rotateRect(r, 1), { x: 1 - 0.2 - 0.4, y: 0.1, w: 0.4, h: 0.3 });
    close(rotateRect(r, -1), rotateRect(r, 3));
  });
  it("four quarter turns are none", () => close(rotateRect(r, 4), r));
  it("turn keeps the rotation in 0-270", () => {
    expect(turn(0, -1)).toBe(270);
    expect(turn(270, 1)).toBe(0);
    expect(turn(90, 2)).toBe(270);
  });
});

describe("toApiRects", () => {
  it("rounds to four decimals and stays inside the image", () => {
    const [out] = toApiRects([
      { x: 0.66666666, y: 0.123456, w: 0.33339, h: 0.5 },
    ]);
    expect(out).toEqual({ x: 0.6667, y: 0.1235, w: 0.3333, h: 0.5 });
    expect(out.x + out.w).toBeLessThanOrEqual(1.0001);
  });
  it("sends at most 20, and an empty list as is", () => {
    expect(toApiRects(Array(25).fill(r))).toHaveLength(MAX_RECTS);
    expect(toApiRects([])).toEqual([]);
  });
});

describe("initialRects", () => {
  it("prefers the saved rectangles, then the suggestion, then the lower third", () => {
    expect(
      initialRects({ mask_rects: [r], mask_suggestion: [LOWER_THIRD] }),
    ).toEqual([r]);
    expect(initialRects({ mask_rects: [], mask_suggestion: null })).toEqual([]);
    expect(initialRects({ mask_rects: null, mask_suggestion: [r] })).toEqual([
      r,
    ]);
    expect(initialRects({ mask_rects: null, mask_suggestion: null })).toEqual([
      LOWER_THIRD,
    ]);
  });
});

describe("enhancePencil", () => {
  it("greys out by the green channel and stretches it to full range", () => {
    // Paper (bright in green), green print (bright in green too) and pencil (dark grey).
    const rgba = [
      [240, 235, 225, 255],
      [60, 200, 80, 255],
      [90, 90, 90, 255],
    ];
    const px = new Uint8ClampedArray(rgba.flat());
    enhancePencil(px);
    const grey = [0, 4, 8].map((i) => px[i]);
    expect(
      [0, 4, 8].every((i) => px[i] === px[i + 1] && px[i] === px[i + 2]),
    ).toBe(true);
    expect(grey[2]).toBe(0); // pencil black
    expect(grey[0]).toBe(255); // paper white
    expect(grey[1]).toBeGreaterThan(180); // the green print fades towards the paper
    expect([3, 7, 11].map((i) => px[i])).toEqual([255, 255, 255]); // alpha kept
  });
  it("survives a flat image", () => {
    const px = new Uint8ClampedArray([100, 100, 100, 255, 100, 100, 100, 255]);
    enhancePencil(px);
    expect(px[0]).toBe(0);
  });
});
