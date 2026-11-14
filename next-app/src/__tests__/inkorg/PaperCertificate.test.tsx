import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PaperCertificate } from "@/components/individual/PaperCertificate";

afterEach(cleanup);

describe("PaperCertificate", () => {
  it("shows the thumbnail linking to the full image", () => {
    render(<PaperCertificate number="G9001-2512" />);
    expect(screen.getByText("Pappersintyg")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/api/v2/individual/G9001-2512/paper-certificate",
    );
  });

  it("hides the block when the image fails to load (403/404)", () => {
    render(<PaperCertificate number="G9001-2512" />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.queryByText("Pappersintyg")).toBeNull();
  });
});
