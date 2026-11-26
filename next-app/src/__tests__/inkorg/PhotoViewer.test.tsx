import "@/i18n";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { PhotoViewer } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/PhotoViewer";

afterEach(cleanup);

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
