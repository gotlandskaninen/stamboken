import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const push = vi.fn();
const uploadIntyg = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: vi.fn() }),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inskick/ny/actions", () => ({
  uploadIntyg: (...a: unknown[]) => uploadIntyg(...a),
}));

import { UploadForm } from "@/app/(app)/stamboken/(dashboard)/inskick/ny/UploadForm";

const pdf = () => new File(["x"], "intyg.pdf", { type: "application/pdf" });

function pick() {
  fireEvent.change(screen.getByTestId("inskick-files"), {
    target: { files: [pdf()] },
  });
}

beforeEach(() => {
  push.mockReset();
  uploadIntyg.mockReset();
});
afterEach(cleanup);

describe("UploadForm", () => {
  it("preselects the only herd and disables Skicka until a file is chosen", () => {
    render(<UploadForm herds={["G9001"]} />);
    expect(screen.getByLabelText("Besättning")).toHaveValue("G9001");
    expect(screen.getByRole("button", { name: "Skicka" })).toBeDisabled();
  });

  it("lets a queue worker search any herd and sends its code", async () => {
    uploadIntyg
      .mockResolvedValueOnce({ ok: true, documents: [], itemId: null })
      .mockResolvedValueOnce({ ok: true, documents: [], itemId: 14 });
    render(
      <UploadForm
        herds={[]}
        herdOptions={[
          { herd: "G9001", herd_name: "Testbesättningen", is_active: true },
        ]}
      />,
    );
    const input = screen.getByRole("combobox", { name: "Besättning" });
    fireEvent.change(input, { target: { value: "G9" } });
    fireEvent.click(await screen.findByText("G9001 – Testbesättningen"));
    pick();
    fireEvent.click(await screen.findByRole("button", { name: "Skicka" }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect((uploadIntyg.mock.calls[0][0] as FormData).get("herd")).toBe(
      "G9001",
    );
  });

  it("sends straight on when the dry run has no warnings", async () => {
    uploadIntyg
      .mockResolvedValueOnce({
        ok: true,
        documents: [{ file: 0, page: 1, warnings: [] }],
        itemId: null,
      })
      .mockResolvedValueOnce({ ok: true, documents: [], itemId: 12 });
    render(<UploadForm herds={["G9001"]} />);
    pick();
    fireEvent.click(await screen.findByRole("button", { name: "Skicka" }));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/stamboken/inskick#arende-12"),
    );
    expect(uploadIntyg.mock.calls.map((c) => c[1])).toEqual([true, false]);
  });

  it("shows the API warning, then Skicka ändå sends without a second dry run", async () => {
    uploadIntyg
      .mockResolvedValueOnce({
        ok: true,
        documents: [{ file: 0, page: null, warnings: ["suddig"] }],
        itemId: null,
      })
      .mockResolvedValueOnce({ ok: true, documents: [], itemId: 13 });
    render(<UploadForm herds={["G9001"]} />);
    pick();
    fireEvent.click(await screen.findByRole("button", { name: "Skicka" }));
    expect(
      await screen.findByText("Bilden ser suddig ut. Ta om den?"),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Ta om" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Skicka ändå" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Skicka ändå" }));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/stamboken/inskick#arende-13"),
    );
    expect(uploadIntyg.mock.calls.map((c) => c[1])).toEqual([true, false]);
  });

  it("shows the API problem detail on failure", async () => {
    uploadIntyg.mockResolvedValueOnce({
      ok: false,
      error: "Otillåten filtyp. Bara JPEG, PNG, WebP, HEIC och PDF.",
    });
    render(<UploadForm herds={["G9001", "G9002"]} />);
    fireEvent.change(screen.getByLabelText("Besättning"), {
      target: { value: "G9002" },
    });
    pick();
    fireEvent.click(await screen.findByRole("button", { name: "Skicka" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Otillåten filtyp",
    );
  });
});
