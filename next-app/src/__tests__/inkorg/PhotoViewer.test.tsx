import "@/i18n";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { PhotoViewer } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/PhotoViewer";

afterEach(cleanup);

function setup() {
  render(<PhotoViewer src="/foto.jpg" rotation={0} onRotate={() => {}} />);
  const region = screen.getByRole("region", { name: /^Fotot\./ });
  for (const key of ["scrollLeft", "scrollTop"]) {
    Object.defineProperty(region, key, { value: 0, writable: true });
  }
  return region;
}

function wheel(target: HTMLElement, deltaY: number, at = { x: 0, y: 0 }) {
  const event = new WheelEvent("wheel", {
    deltaY,
    clientX: at.x,
    clientY: at.y,
    bubbles: true,
    cancelable: true,
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

  it("adds up a trackpad's small flicks before a step", () => {
    const region = setup();
    wheel(region, -20);
    expect(screen.getByText("100 %")).toBeInTheDocument();
    wheel(region, -40);
    expect(screen.getByText("150 %")).toBeInTheDocument();
  });

  it("keeps the point under the pointer where it was", () => {
    const region = setup();
    wheel(region, -100, { x: 100, y: 50 });
    // 1.5 times as large: the point 100 px in is now 150 px in, so scroll 50 px to keep it under the pointer.
    expect(region.scrollLeft).toBe(50);
    expect(region.scrollTop).toBe(25);
  });
});
