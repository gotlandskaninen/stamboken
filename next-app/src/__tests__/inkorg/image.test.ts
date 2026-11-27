import { describe, expect, it } from "vitest";
import {
  degrees,
  enhancePencil,
  crops,
  initialFrame,
  initialRects,
  MAX_RECTS,
  MIN_FRAME,
  toApiFrame,
  moveRect,
  resizeRect,
  rotateRect,
  toApiRects,
  turn,
  turnedSize,
  UPPER_TWO_THIRDS,
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
    close(resizeRect(r, -5, -5, MIN_FRAME), { w: 0.101, h: 0.101 });
  });
});

describe("rotateRect", () => {
  it("a quarter turn clockwise takes the top band to the right edge", () =>
    close(rotateRect(UPPER_TWO_THIRDS, 1), {
      x: 0.3333,
      y: 0,
      w: 0.6667,
      h: 1,
    }));
  it("a half turn takes the top band to the bottom", () =>
    close(rotateRect(UPPER_TWO_THIRDS, 2), {
      x: 0,
      y: 0.3333,
      w: 1,
      h: 0.6667,
    }));
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
  it("starts from the saved black boxes, or none", () => {
    expect(initialRects({ mask_rects: [r] })).toEqual([r]);
    expect(initialRects({ mask_rects: [] })).toEqual([]);
    expect(initialRects({ mask_rects: null })).toEqual([]);
  });
});

describe("initialFrame", () => {
  it("prefers the saved frame, then the API's, then the upper two thirds of a photo never masked", () => {
    const none = { copy_frame: null, frame_suggestion: null, mask_rects: null };
    expect(initialFrame({ ...none, copy_frame: r })).toEqual(r);
    expect(
      initialFrame({
        ...none,
        frame_suggestion: { ...UPPER_TWO_THIRDS, h: 0.5 },
      }),
    ).toEqual({ ...UPPER_TWO_THIRDS, h: 0.5 });
    expect(initialFrame(none)).toEqual(UPPER_TWO_THIRDS);
    // A copy made with boxes only, or with nothing to hide, is redone as it was made: without a frame.
    expect(initialFrame({ ...none, mask_rects: [r] })).toBe(null);
    expect(initialFrame({ ...none, mask_rects: [] })).toBe(null);
    // even when the API offers its frame for a handwritten certificate
    expect(
      initialFrame({
        ...none,
        mask_rects: [],
        frame_suggestion: UPPER_TWO_THIRDS,
      }),
    ).toBe(null);
  });
});

describe("toApiFrame", () => {
  it("rounds to four decimals inwards, never past what the frame shows", () => {
    expect(toApiFrame({ x: 0, y: 0, w: 1, h: 0.66545 })).toEqual({
      x: 0,
      y: 0,
      w: 1,
      h: 0.6654,
    });
    expect(toApiFrame({ x: 0.12341, y: 0.5, w: 0.5, h: 0.5 })).toEqual({
      x: 0.1235,
      y: 0.5,
      w: 0.4999,
      h: 0.5,
    });
    expect(toApiFrame(UPPER_TWO_THIRDS)).toEqual(UPPER_TWO_THIRDS); // already four decimals: unchanged
  });
});

describe("crops", () => {
  it("is a frame that leaves part of the photo out", () => {
    expect(crops(UPPER_TWO_THIRDS)).toBe(true);
    expect(crops({ x: 0, y: 0, w: 1, h: 1 })).toBe(false);
    expect(crops({ x: 0, y: 0, w: 1, h: 0.995 })).toBe(false);
    // judged as the API gets it, rounded inwards: 0.98996 goes as 0.9899, 0.99004 as 0.99
    expect(crops({ x: 0, y: 0, w: 1, h: 0.98996 })).toBe(true);
    expect(crops({ x: 0, y: 0, w: 1, h: 0.99004 })).toBe(false);
    expect(crops(null)).toBe(false);
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

describe("turnedSize", () => {
  it("swaps width and height for a quarter turn and keeps them for a half", () => {
    expect(turnedSize(400, 300, 0)).toEqual({ width: 400, height: 300 });
    expect(turnedSize(400, 300, 90)).toEqual({ width: 300, height: 400 });
    expect(turnedSize(400, 300, 180)).toEqual({ width: 400, height: 300 });
    expect(turnedSize(400, 300, 270)).toEqual({ width: 300, height: 400 });
  });

  it("is the bounding box of the photo turned by any other angle", () => {
    // 400 cos 30° + 300 sin 30° = 496.4, and 400 sin 30° + 300 cos 30° = 459.8.
    expect(turnedSize(400, 300, 30)).toEqual({ width: 496, height: 460 });
    expect(turnedSize(400, 300, -30)).toEqual({ width: 496, height: 460 });
    expect(turnedSize(400, 300, 90 + 30)).toEqual({ width: 460, height: 496 });
  });
});

describe("degrees", () => {
  it("writes the angle with a decimal comma and a minus sign", () => {
    expect(degrees(4)).toBe("4,0°");
    expect(degrees(-2.5)).toBe("−2,5°");
  });
});
