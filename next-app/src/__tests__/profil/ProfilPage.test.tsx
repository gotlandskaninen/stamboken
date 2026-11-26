import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const { fetchApi, stub } = vi.hoisted(() => ({
  fetchApi: vi.fn(),
  stub: (name: string) => () => ({ [name]: () => null }),
}));
vi.mock("@/lib/api", () => ({ fetchApi, ApiError: class extends Error {} }));
vi.mock("@/lib/auth", () => ({
  requireUser: async () => ({ email: "m@example.invalid" }),
}));
vi.mock("@/components/shell/Masthead", () => ({ Masthead: () => null }));
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/profil/KontoCard",
  stub("KontoCard"),
);
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/profil/MedlemskapCard",
  stub("MedlemskapCard"),
);
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/profil/KontaktClient",
  stub("KontaktClient"),
);
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/profil/PersonerClient",
  stub("PersonerClient"),
);
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/profil/NotisClient",
  stub("NotisClient"),
);
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/profil/IntygareClient",
  stub("IntygareClient"),
);
vi.mock("@/app/(app)/stamboken/(dashboard)/profil/PubliceringClient", () => ({
  PubliceringClient: () => <p>Koharen-frågan</p>,
}));

import ProfilPage from "@/app/(app)/stamboken/(dashboard)/profil/page";

afterEach(cleanup);

const show = async (hasActiveHerd: boolean, ja = false) => {
  const membership = { id: 1 };
  const me = {
    role: "huvudmedlem",
    membership,
    has_active_herd: hasActiveHerd,
    publication_consent: {
      name: ja,
      phone: false,
      email: false,
      address: false,
    },
  };
  fetchApi.mockImplementation(async (path: string) =>
    path === "/v2/members/me"
      ? me
      : path === "/v2/my-membership"
        ? { membership: { ...membership, persons: [], herds: [] } }
        : null,
  );
  render(await ProfilPage());
};

describe("ProfilPage's Koharen card", () => {
  it("asks about the herd when the membership has an active one", async () => {
    await show(true);
    expect(screen.getByText("Koharen-frågan")).toBeTruthy();
  });

  it("is not shown without an active herd in a genebank", async () => {
    await show(false);
    expect(screen.queryByText("Koharen-frågan")).toBeNull();
  });

  it("is shown without an active herd while a Ja stands, so it can be withdrawn", async () => {
    await show(false, true);
    expect(screen.getByText("Koharen-frågan")).toBeTruthy();
  });
});
