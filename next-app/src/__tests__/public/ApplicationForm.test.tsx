// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const { submitApplicationMock } = vi.hoisted(() => ({
  submitApplicationMock: vi.fn(),
}));

vi.mock("@/app/(app)/(public)/ansok/actions", () => ({
  submitApplication: submitApplicationMock,
}));

import { ApplicationForm } from "@/app/(app)/(public)/ansok/ApplicationForm";

beforeEach(() => {
  submitApplicationMock.mockReset();
  submitApplicationMock.mockResolvedValue({ ok: true, id: 1 });
});

afterEach(cleanup);

// Required TextFields render their label as "Förnamn *" — anchor on the start.
// (A function matcher rather than `new RegExp(label)`: Semgrep's
// detect-non-literal-regexp gate flags that.)
const field = (label: string) =>
  screen.getByLabelText((content) => content.startsWith(label));

function fill(label: string, value: string) {
  fireEvent.change(field(label), { target: { value } });
}

const billingBox = () =>
  screen.getByRole("checkbox", { name: /Fakturan ska till en annan adress/ });
const submit = () => screen.getByRole("button", { name: "Skicka ansökan" });

function fillApplicant() {
  fill("Förnamn", "Nora");
  fill("Efternamn", "Nysson");
  fill("E-post", "nora@example.com");
  fireEvent.click(
    screen.getByRole("checkbox", { name: /mina personuppgifter/ }),
  );
}

describe("ApplicationForm — fakturaadress", () => {
  it("hides the billing fields and sends none of them by default", async () => {
    render(<ApplicationForm />);
    expect(billingBox()).not.toBeChecked();
    expect(screen.queryByLabelText("Fakturamottagare")).not.toBeInTheDocument();

    fillApplicant();
    fireEvent.click(submit());

    await waitFor(() => expect(submitApplicationMock).toHaveBeenCalledTimes(1));
    const body = submitApplicationMock.mock.calls[0][0];
    expect(Object.keys(body).filter((k) => k.startsWith("billing_"))).toEqual(
      [],
    );
  });

  it("sends the billing address when the box is ticked", async () => {
    render(<ApplicationForm />);
    fillApplicant();
    fireEvent.click(billingBox());
    fill("Fakturamottagare", "Djurparken i Exempelby");
    fill("Fakturaadress", "Box 99");
    fill("Fakturapostnummer", "987");
    expect(submit()).toBeDisabled();
    fill("Fakturapostnummer", "98765");
    fireEvent.blur(field("Fakturapostnummer"));
    fill("Fakturapostort", "Annanstad");
    fill("Fakturareferens", "Er ref 12");
    expect(submit()).toBeEnabled();

    fireEvent.click(submit());

    await waitFor(() => expect(submitApplicationMock).toHaveBeenCalledTimes(1));
    expect(submitApplicationMock).toHaveBeenCalledWith(
      expect.objectContaining({
        first_name: "Nora",
        billing_name: "Djurparken i Exempelby",
        billing_address: "Box 99",
        billing_postal_code: "987 65",
        billing_city: "Annanstad",
        billing_email: "",
        billing_reference: "Er ref 12",
      }),
    );
  });

  it("drops the typed billing address when the box is unticked again", async () => {
    render(<ApplicationForm />);
    fillApplicant();
    fireEvent.click(billingBox());
    fill("Fakturamottagare", "Gården");
    fireEvent.click(billingBox());
    expect(screen.queryByLabelText("Fakturamottagare")).not.toBeInTheDocument();

    fireEvent.click(submit());

    await waitFor(() => expect(submitApplicationMock).toHaveBeenCalledTimes(1));
    expect(submitApplicationMock.mock.calls[0][0]).not.toHaveProperty(
      "billing_name",
    );
  });
});
