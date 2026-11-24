import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { EmbedBlockComponent } from "@/components/blocks/EmbedBlock";

describe("EmbedBlockComponent", () => {
  it("loads nothing from the video service until the visitor asks", () => {
    const { container } = render(
      <EmbedBlockComponent url="https://www.youtube.com/watch?v=abc123" />,
    );
    expect(container.querySelector("iframe")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Visa filmen" }));

    expect(container.querySelector("iframe")?.getAttribute("src")).toBe(
      "https://www.youtube-nocookie.com/embed/abc123?autoplay=1",
    );
  });

  it("renders nothing for an address it does not recognise", () => {
    const { container } = render(
      <EmbedBlockComponent url="https://example.com/film" />,
    );
    expect(container.firstChild).toBeNull();
  });
});
