import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { fetchApi } from "@/lib/api";

vi.mock("@/lib/api", () => ({ fetchApi: vi.fn() }));
const markUploadsSeen = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/inskick/ny/actions", () => ({
  markUploadsSeen: () => markUploadsSeen(),
}));
vi.mock("@/components/shell/Masthead", () => ({ Masthead: () => null }));

import MinaInskickPage from "@/app/(app)/stamboken/(dashboard)/inskick/page";

const api = vi.mocked(fetchApi);
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("Mina inskick", () => {
  it("only reads while it renders, and marks the notices seen once it is shown", async () => {
    api.mockResolvedValueOnce({ items: [] });
    const page = await MinaInskickPage();
    expect(api.mock.calls).toEqual([
      ["/v2/inkorg/mina-inskick", { isolateDemo: true }],
    ]);
    expect(markUploadsSeen).not.toHaveBeenCalled();
    render(page);
    expect(markUploadsSeen).toHaveBeenCalledTimes(1);
  });
});
