import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  fetchApi: vi.fn(),
  ApiError: class extends Error {},
}));
import { fetchApi } from "@/lib/api";
import { IndividualGenetics } from "@/components/individual/IndividualGenetics";

afterEach(cleanup);

describe("IndividualGenetics", () => {
  it("isolates a failure", async () => {
    vi.mocked(fetchApi).mockRejectedValueOnce(new Error("503"));
    render(await IndividualGenetics({ number: "G1-1" }));
    expect(screen.getByText("Genetiken kan inte visas just nu")).toBeTruthy();
  });
});
