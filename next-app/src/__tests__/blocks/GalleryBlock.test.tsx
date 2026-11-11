import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GalleryBlockComponent } from "@/components/blocks/GalleryBlock";

const images = [
  { image: { url: "/a.jpg", alt: "Svart scheck" }, caption: "Svart" },
  { image: null, caption: "Saknad bild" },
  { image: { url: "/b.jpg", alt: "Gul scheck" }, caption: "Gul" },
];

afterEach(cleanup);

describe("GalleryBlockComponent", () => {
  it("shows the first image and counts only images that exist", () => {
    render(<GalleryBlockComponent images={images} />);
    expect(screen.getByAltText("Svart scheck")).toBeTruthy();
    expect(screen.getByText("1 / 2")).toBeTruthy();
  });

  it("switches the large image when a thumbnail is chosen", () => {
    render(<GalleryBlockComponent images={images} />);
    const second = screen.getByRole("button", { name: "Visa bild 2: Gul" });
    fireEvent.click(second);
    expect(screen.getByAltText("Gul scheck")).toBeTruthy();
    expect(screen.getByText("2 / 2")).toBeTruthy();
    expect(second.getAttribute("aria-current")).toBe("true");
  });

  it("renders nothing without images", () => {
    const { container } = render(<GalleryBlockComponent images={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
