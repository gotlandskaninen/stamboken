import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { ModeProvider } from "@/lib/mode-context";
import { ModeHtmlAttribute } from "@/components/public/ModeHtmlAttribute.client";

describe("ModeHtmlAttribute", () => {
  afterEach(() => cleanup());

  it("sets data-mode=demo on <html> in testmiljön and removes it on unmount", () => {
    const { unmount } = render(
      <ModeProvider mode="demo">
        <ModeHtmlAttribute />
      </ModeProvider>,
    );
    expect(document.documentElement.dataset.mode).toBe("demo");
    unmount();
    expect(document.documentElement.dataset.mode).toBeUndefined();
  });

  it("sets data-mode=prod in riktiga stamboken", () => {
    render(
      <ModeProvider mode="prod">
        <ModeHtmlAttribute />
      </ModeProvider>,
    );
    expect(document.documentElement.dataset.mode).toBe("prod");
  });
});
