import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PaperCertificate } from "@/components/individual/PaperCertificate";
import { ModeProvider } from "@/lib/mode-context";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

const inMode = (mode: "demo" | "prod") =>
  render(
    <ModeProvider mode={mode}>
      <PaperCertificate number="G9001-2512" />
    </ModeProvider>,
  );

describe("PaperCertificate", () => {
  it("shows the thumbnail linking to the full image", () => {
    inMode("prod");
    expect(screen.getByText("Pappersintyg")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/api/v2/individual/G9001-2512/paper-certificate",
    );
  });

  it("reads the copy from the demo API in demo mode", () => {
    vi.stubEnv("NEXT_PUBLIC_API_TEST_URL", "/api-test");
    inMode("demo");
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/api-test/v2/individual/G9001-2512/paper-certificate",
    );
  });
});
