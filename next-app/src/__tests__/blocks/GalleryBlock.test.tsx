import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GalleryBlockComponent } from "@/components/blocks/GalleryBlock";

const images = [
  { image: { url: "/a.jpg", alt: "Svartbrokig" }, caption: "Svart" },
  { image: null, caption: "Saknad bild" },
  { image: { url: "/b.jpg", alt: "Gulbrokig" }, caption: "Gul" },
];

afterEach(cleanup);

describe("GalleryBlockComponent", () => {
  it("shows the first image and counts only images that exist", () => {
    render(<GalleryBlockComponent images={images} />);
    expect(screen.getByAltText("Svartbrokig")).toBeTruthy();
    expect(screen.getByText("1 / 2")).toBeTruthy();
  });

  it("switches the large image when a thumbnail is chosen", () => {
    render(<GalleryBlockComponent images={images} />);
    const second = screen.getByRole("button", { name: "Visa bild 2: Gul" });
    fireEvent.click(second);
    expect(screen.getByAltText("Gulbrokig")).toBeTruthy();
    expect(screen.getByText("2 / 2")).toBeTruthy();
    expect(second.getAttribute("aria-current")).toBe("true");
  });

  it("steps with the arrows and wraps around", () => {
    render(<GalleryBlockComponent images={images} />);
    fireEvent.click(screen.getByRole("button", { name: "Nästa bild" }));
    expect(screen.getByText("2 / 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Nästa bild" }));
    expect(screen.getByText("1 / 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Föregående bild" }));
    expect(screen.getByText("2 / 2")).toBeTruthy();
  });

  const swipe = (el: Element, dx: number, dy: number) => {
    fireEvent.touchStart(el, { touches: [{ clientX: 200, clientY: 200 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [{ clientX: 200 + dx, clientY: 200 + dy }],
    });
  };

  it("steps on a sideways swipe", () => {
    render(<GalleryBlockComponent images={images} />);
    swipe(screen.getByAltText("Svartbrokig"), -60, 10);
    expect(screen.getByText("2 / 2")).toBeTruthy();
  });

  it("keeps the image when the page is scrolled with a drifting thumb", () => {
    render(<GalleryBlockComponent images={images} />);
    swipe(screen.getByAltText("Svartbrokig"), -50, 180);
    expect(screen.getByText("1 / 2")).toBeTruthy();
  });

  it("loads the small size for the thumbnails", () => {
    const sized = [
      {
        image: {
          url: "/a.jpg",
          alt: "Stor",
          sizes: {
            card: { url: "/a-card.jpg" },
            thumbnail: { url: "/a-thumb.jpg" },
          },
        },
      },
      { image: { url: "/b.jpg", alt: "Utan storlekar" } },
    ];
    const { container } = render(<GalleryBlockComponent images={sized} />);
    const srcs = Array.from(container.querySelectorAll("img")).map((img) =>
      img.getAttribute("src"),
    );
    expect(srcs).toEqual(["/a-card.jpg", "/a-thumb.jpg", "/b.jpg"]);
  });

  it("shows a single image without thumbnails or a counter", () => {
    render(<GalleryBlockComponent images={images.slice(0, 1)} />);
    expect(screen.getByAltText("Svartbrokig")).toBeTruthy();
    expect(screen.queryByText("1 / 1")).toBeNull();
    expect(screen.queryByRole("group", { name: "Välj bild" })).toBeNull();
  });

  it("renders nothing without images", () => {
    const { container } = render(<GalleryBlockComponent images={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
