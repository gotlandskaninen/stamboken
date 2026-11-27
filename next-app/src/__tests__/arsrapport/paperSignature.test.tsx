import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { view } from "./fixtures";
import "@/i18n";
import { ReportForm } from "@/app/(app)/stamboken/(dashboard)/arsrapport/ReportForm";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
afterEach(cleanup);

it("sends a receipt-day signature only when explicitly entered", async () => {
  const dryRun = vi.fn().mockResolvedValue({
    ok: true,
    data: { ok: false, refusals: [], warnings: [] },
  });
  const item = {
    id: 5,
    received_at: "2027-01-03T10:00:00Z",
    state: "tagen",
    account_end: null,
  };
  render(
    <ReportForm
      env="demo"
      view={view({ source: "paper", access: "helper", item })}
      actions={{
        saveDraft: vi.fn(),
        dryRun,
        submitReport: vi.fn(),
        withdrawReport: vi.fn(),
        reportPurchase: vi.fn(),
        sendPurchasePhotos: vi.fn(),
        getGenebankHerds: vi.fn(),
      }}
      post={item.id}
      paper={{
        documentIds: [11],
        intygPending: false,
        archive: vi.fn(),
        leave: vi.fn(),
      }}
    />,
  );
  const signature =
    screen.getByLabelText<HTMLInputElement>("Blankettens datum");
  expect(signature.value).toBe("");
  fireEvent.change(screen.getByLabelText("Mottagen"), {
    target: { value: "2027-01-04" },
  });
  expect(signature.value).toBe("");
  fireEvent.change(signature, { target: { value: "2027-01-04" } });
  await act(async () => {
    fireEvent.click(
      screen.getByRole("button", { name: "Skicka och nästa blankett" }),
    );
  });
  expect(dryRun.mock.calls[0][2]).toMatchObject({
    received_on: "2027-01-04",
    signed_on: "2027-01-04",
    signed_on_confirmed: true,
  });
});
