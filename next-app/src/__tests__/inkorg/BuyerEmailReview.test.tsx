import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BuyerEmailReview } from "@/app/(app)/stamboken/(dashboard)/notiser/koparadress/[number]/BuyerEmailReview";
import { reviewBuyerEmail } from "@/app/(app)/stamboken/(dashboard)/notiser/actions";

vi.mock("@/app/(app)/stamboken/(dashboard)/notiser/actions", () => ({
  reviewBuyerEmail: vi.fn(),
}));

const buyer = { id: 7, name: "Testköpare", email: "test@example.org" };
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("requires explicit confirmation to release an unchanged address", async () => {
  vi.mocked(reviewBuyerEmail).mockResolvedValue({ ok: true });
  render(<BuyerEmailReview buyer={buyer} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Bekräfta att det är samma person" }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Adressen är kontrollerad.",
  );
  expect(reviewBuyerEmail).toHaveBeenCalledWith(7, { confirm: true });
});

it("sends corrected fields for checking and keeps them editable on refusal", async () => {
  vi.mocked(reviewBuyerEmail).mockResolvedValue({
    ok: false,
    error: "Kontrollera adressen.",
  });
  render(<BuyerEmailReview buyer={buyer} />);
  fireEvent.change(screen.getByLabelText("E-postadress"), {
    target: { value: "ny@example.org" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Spara rättelse" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Kontrollera adressen.",
  );
  expect(reviewBuyerEmail).toHaveBeenCalledWith(7, {
    name: buyer.name,
    email: "ny@example.org",
  });
  expect(screen.getByLabelText("E-postadress")).toBeEnabled();
});
