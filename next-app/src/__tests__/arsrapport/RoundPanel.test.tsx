import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
const sendTestMail = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/arsrapport/actions", () => ({
  activateGenebank: vi.fn(),
  saveRound: vi.fn(),
  sendTestMail: (...a: unknown[]) => sendTestMail(...a),
}));

import { RoundPanel } from "@/app/(app)/stamboken/(dashboard)/arsrapport/status/[year]/RoundPanel";
import type { Round } from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(() => {
  cleanup();
  sendTestMail.mockReset();
});

const round: Round = {
  year: 2026,
  start_date: "2026-12-31",
  deadline: "2027-01-31",
  end_date: "2027-03-01",
  is_active: true,
  genebanks: [
    {
      genebank_id: 1,
      activated_at: "2026-12-01T10:00:00+01:00",
      activated_by: { id: 1, name: "Test Admin" },
      send_at: "2026-12-31",
      sent_at: null,
    },
  ],
};
const show = (canEdit: boolean) =>
  render(
    <RoundPanel
      year={2026}
      genebankId={1}
      genebankName="Gotland"
      round={round}
      canEdit={canEdit}
      recipients={{ med_epost: 190, utan_epost: 5 }}
      env="demo"
    />,
  );

describe("RoundPanel invitation", () => {
  it("says how many herds the invitation reaches and how many get the form by post", () => {
    show(true);
    expect(
      screen.getByText(
        /Inbjudan går till 190 besättningar\.\s+5 saknar e-post och får blanketten med post\./,
      ),
    ).toBeTruthy();
  });
  it("sends the test mail to the manager and says so", async () => {
    sendTestMail.mockResolvedValue({ ok: true, data: { queued: true } });
    show(true);
    fireEvent.click(screen.getByText("Skicka provmejl till mig"));
    await waitFor(() =>
      expect(sendTestMail).toHaveBeenCalledWith(2026, 1, "demo"),
    );
    expect(await screen.findByText(/Provmejlet är på väg/)).toBeTruthy();
  });
  it("gives a helper the count but no test mail button", () => {
    show(false);
    expect(screen.getByText(/Inbjudan går till 190/)).toBeTruthy();
    expect(screen.queryByText("Skicka provmejl till mig")).toBeNull();
  });
  it("shows no count once the invitations are sent", () => {
    render(
      <RoundPanel
        year={2026}
        genebankId={1}
        genebankName="Gotland"
        round={{
          ...round,
          genebanks: [
            { ...round.genebanks[0], sent_at: "2026-12-31T07:00:00+01:00" },
          ],
        }}
        canEdit
        recipients={null}
        env="demo"
      />,
    );
    expect(screen.queryByText(/Inbjudan går till/)).toBeNull();
    expect(screen.getByText(/Inbjudningarna skickades/)).toBeTruthy();
  });
  it("says 1 besättning for one herd", () => {
    render(
      <RoundPanel
        year={2026}
        genebankId={1}
        genebankName="Gotland"
        round={round}
        canEdit
        recipients={{ med_epost: 1, utan_epost: 1 }}
        env="demo"
      />,
    );
    expect(
      screen.getByText(
        /Inbjudan går till 1 besättning\.\s+1 saknar e-post och får blanketten med post\./,
      ),
    ).toBeTruthy();
  });
  it("shows a helper the count before the round is activated, without the button", () => {
    render(
      <RoundPanel
        year={2026}
        genebankId={1}
        genebankName="Gotland"
        round={{ ...round, genebanks: [] }}
        canEdit={false}
        recipients={{ med_epost: 190, utan_epost: 5 }}
        env="demo"
      />,
    );
    expect(screen.getByText(/Inbjudan går till 190/)).toBeTruthy();
    expect(screen.queryByText("Skicka provmejl till mig")).toBeNull();
  });
});
