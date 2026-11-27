import "@/i18n";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { PhotoViewer } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/PhotoViewer";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const WIDTH = 400;
const HEIGHT = 300;

/**
 * A viewport of 400 × 300 px over a photo of the same size at 100 %: jsdom lays nothing out, so the photo's
 * size follows its zoom and the scroll is cut back at the edges, as a browser does.
 */
function setup() {
  render(<PhotoViewer src="/foto.jpg" rotation={0} onRotate={() => {}} />);
  const region = screen.getByRole("region", { name: /^Fotot\./ });
  const stage = region.firstElementChild as HTMLElement;
  const factor = () => parseFloat(stage.style.width) / 100;
  const scroll = { left: 0, top: 0 };
  const edge = (value: number, size: number) =>
    Math.max(0, Math.min(value, size * factor() - size));
  Object.defineProperty(region, "scrollLeft", {
    get: () => edge(scroll.left, WIDTH),
    set: (value: number) => (scroll.left = edge(value, WIDTH)),
  });
  Object.defineProperty(region, "scrollTop", {
    get: () => edge(scroll.top, HEIGHT),
    set: (value: number) => (scroll.top = edge(value, HEIGHT)),
  });
  stage.getBoundingClientRect = () =>
    new DOMRect(
      -region.scrollLeft,
      -region.scrollTop,
      WIDTH * factor(),
      HEIGHT * factor(),
    );
  return region;
}

function wheel(
  target: HTMLElement,
  deltaY: number,
  init: Omit<WheelEventInit, "deltaY"> & { x?: number; y?: number } = {},
) {
  const { x = 0, y = 0, ...rest } = init;
  const event = new WheelEvent("wheel", {
    deltaY,
    clientX: x,
    clientY: y,
    bubbles: true,
    cancelable: true,
    ...rest,
  });
  act(() => {
    target.dispatchEvent(event);
  });
  return event;
}

describe("PhotoViewer: the mouse wheel zooms", () => {
  it("lets the page scroll on at 100 % and zooms in a step per notch", () => {
    const region = setup();
    expect(wheel(region, 100).defaultPrevented).toBe(false);
    expect(screen.getByText("100 %")).toBeInTheDocument();

    expect(wheel(region, -100).defaultPrevented).toBe(true);
    expect(screen.getByText("150 %")).toBeInTheDocument();
    wheel(region, 100);
    expect(screen.getByText("100 %")).toBeInTheDocument();
  });

  it("lets the page scroll on at 600 % too", () => {
    const region = setup();
    for (let i = 0; i < 5; i++) wheel(region, -100);
    expect(screen.getByText("600 %")).toBeInTheDocument();
    expect(wheel(region, -100).defaultPrevented).toBe(false);
  });

  it("holds the photo still while a mouse button is held (a drag)", () => {
    const region = setup();
    const held = wheel(region, -100, { buttons: 1 });
    expect(held.defaultPrevented).toBe(true);
    expect(screen.getByText("100 %")).toBeInTheDocument();
    expect(wheel(region, 100, { buttons: 1 }).defaultPrevented).toBe(true);
  });

  it("holds it still while any press in the photo lasts, as Safari says no button is down", () => {
    const region = setup();
    const pointer = (type: string, pointerId: number, target: EventTarget) =>
      act(() => {
        target.dispatchEvent(
          Object.assign(new Event(type, { bubbles: true }), { pointerId }),
        );
      });
    pointer("pointerdown", 1, region); // a finger on a masking rectangle
    pointer("pointerdown", 2, region);
    pointer("pointerup", 2, window); // another pointer lets go elsewhere
    expect(wheel(region, -100).defaultPrevented).toBe(true);
    expect(screen.getByText("100 %")).toBeInTheDocument();
    pointer("pointerup", 1, window);
    wheel(region, -100);
    expect(screen.getByText("150 %")).toBeInTheDocument();
  });

  it("reads the unit first, so Firefox keeps a notch in lines", () => {
    const region = setup();
    // Firefox reports pixels (16 a line) when a delta is read before deltaMode, lines otherwise.
    const event = new WheelEvent("wheel", { bubbles: true, cancelable: true });
    let unitRead = false;
    let pixels = false;
    const delta = (lines: number) => () => {
      if (!unitRead) pixels = true;
      return pixels ? lines * 16 : lines;
    };
    Object.defineProperties(event, {
      deltaMode: {
        get: () => {
          unitRead = true;
          return pixels ? 0 : WheelEvent.DOM_DELTA_LINE;
        },
      },
      deltaX: { get: delta(0) },
      deltaY: { get: delta(-1) },
    });
    act(() => {
      region.dispatchEvent(event);
    });
    expect(screen.getByText("150 %")).toBeInTheDocument();
  });

  it("takes a line or a page as a notch", () => {
    const region = setup();
    wheel(region, -1, { deltaMode: WheelEvent.DOM_DELTA_PAGE });
    expect(screen.getByText("150 %")).toBeInTheDocument();
    wheel(region, -3, { deltaMode: WheelEvent.DOM_DELTA_LINE });
    expect(screen.getByText("200 %")).toBeInTheDocument();
  });

  it("adds up a trackpad's flicks and keeps what is left over", () => {
    const region = setup();
    wheel(region, -40);
    expect(screen.getByText("100 %")).toBeInTheDocument();
    wheel(region, -40);
    wheel(region, -40);
    expect(screen.getByText("200 %")).toBeInTheDocument();
  });

  it("leaves a pinch (ctrlKey) to the browser", () => {
    const region = setup();
    expect(wheel(region, -100, { ctrlKey: true }).defaultPrevented).toBe(false);
    expect(screen.getByText("100 %")).toBeInTheDocument();
  });

  it("keeps the point under the pointer where it was", () => {
    const region = setup();
    wheel(region, -100, { x: 100, y: 50 });
    // 1.5 times as large: the point 100 px in is now 150 px in, so scroll 50 px to keep it under the pointer.
    expect(region.scrollLeft).toBe(50);
    expect(region.scrollTop).toBe(25);
  });

  it("keeps it there zooming out near the edge, where the scroll was cut back", () => {
    const region = setup();
    wheel(region, -100, { x: 200, y: 150 });
    wheel(region, -100, { x: 200, y: 150 });
    expect(screen.getByText("200 %")).toBeInTheDocument();
    region.scrollLeft = 300; // 500 px into an 800 px photo is under the pointer
    wheel(region, 100, { x: 200, y: 150 });
    // 600 px wide now (at most 200 px of scroll): 375 px into it under the pointer.
    expect(region.scrollLeft).toBe(175);
  });
});

describe("PhotoViewer: the frame around the copy", () => {
  it("is named apart from the black boxes, which are counted without it", async () => {
    // The rectangles lie on the photo once it has loaded; jsdom draws nothing.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    vi.stubGlobal(
      "Image",
      class {
        onload = () => {};
        set src(_: string) {
          queueMicrotask(() => this.onload());
        }
      },
    );
    const noop = () => {};
    render(
      <PhotoViewer
        src="/foto.jpg"
        rotation={0}
        onRotate={noop}
        mask={{
          rects: [
            { x: 0, y: 0, w: 1, h: 0.6667 },
            { x: 0.35, y: 0.45, w: 0.3, h: 0.1 },
          ],
          frameAt: 0,
          selected: null,
          onSelect: noop,
          onChange: noop,
          onRemove: noop,
        }}
      />,
    );
    const frame = await screen.findByRole("button", {
      name: /^Ramen runt kopian\./,
    });
    const box = screen.getByRole("button", { name: /^Svart ruta 1 av 1\./ });
    expect(frame.className).toMatch(/copyFrame/);
    expect(box.className).not.toMatch(/copyFrame/);
  });
});

/** A loaded photo of `width` × `height` px, drawn on a canvas that records nothing. */
function loadedPhoto(width: number, height: number) {
  const ctx = {
    fillRect: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    drawImage: vi.fn(),
    setTransform: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  );
  vi.stubGlobal(
    "Image",
    class {
      naturalWidth = width;
      naturalHeight = height;
      onload = () => {};
      set src(_: string) {
        queueMicrotask(() => this.onload());
      }
    },
  );
  return ctx;
}

describe("PhotoViewer: straightening", () => {
  it("draws the photo turned by its rotation and angle on a canvas the size of the turned photo", async () => {
    const ctx = loadedPhoto(400, 300);
    render(
      <PhotoViewer
        src="/foto.jpg"
        rotation={90}
        straighten={30}
        onRotate={() => {}}
        onStraighten={() => {}}
      />,
    );
    const canvas = await screen.findByRole("img", { name: "Originalet" });
    await vi.waitFor(() => expect(ctx.drawImage).toHaveBeenCalled());
    // 120° in all: Pillow turns 400 × 300 into 460 × 498, white where the photo does not reach.
    expect([
      (canvas as HTMLCanvasElement).width,
      (canvas as HTMLCanvasElement).height,
    ]).toEqual([460, 498]);
    expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, 460, 498);
    expect(ctx.rotate).toHaveBeenCalledWith((120 * Math.PI) / 180);
  });

  it("changes, resets and finds the angle, and none of it while the masking locks it", () => {
    const onStraighten = vi.fn();
    const onFindPaper = vi.fn();
    const { rerender } = render(
      <PhotoViewer
        src="/foto.jpg"
        rotation={0}
        straighten={2.5}
        onRotate={() => {}}
        onStraighten={onStraighten}
        onFindPaper={onFindPaper}
      />,
    );
    const slider = screen.getByRole("slider", { name: /Räta upp/ });
    expect(screen.getByText("2,5°")).toBeInTheDocument();
    fireEvent.change(slider, { target: { value: "-4" } });
    expect(onStraighten).toHaveBeenLastCalledWith(-4);
    fireEvent.change(slider, { target: { value: "2.3" } }); // a tenth of a degree, as the API keeps it
    expect(onStraighten).toHaveBeenLastCalledWith(2.3);
    expect(slider).toHaveAttribute("step", "0.1"); // jsdom neither snaps to the step nor reports a mismatch
    fireEvent.click(screen.getByRole("button", { name: "Nollställ" }));
    expect(onStraighten).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "Hitta pappret" }));
    expect(onFindPaper).toHaveBeenCalledTimes(1);
    rerender(
      <PhotoViewer
        src="/foto.jpg"
        rotation={0}
        straighten={2.5}
        onRotate={() => {}}
        onStraighten={onStraighten}
        straightenLocked
        onFindPaper={onFindPaper}
      />,
    );
    expect(slider).toBeDisabled();
    expect(screen.getByRole("button", { name: "Nollställ" })).toBeDisabled();
    // The masking finds the paper at the locked angle.
    expect(screen.getByRole("button", { name: "Hitta pappret" })).toBeEnabled();
  });
});
