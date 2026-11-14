import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { RefreshBadge } from "@/components/shell/RefreshBadge";

beforeEach(() => refresh.mockReset());
afterEach(cleanup);

describe("RefreshBadge", () => {
  it("refreshes once when there were unread notices", () => {
    render(<RefreshBadge unread={2} />);
    expect(refresh).toHaveBeenCalledTimes(1);
  });
  it("does nothing when there were none", () => {
    render(<RefreshBadge unread={0} />);
    expect(refresh).not.toHaveBeenCalled();
  });
});
