import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";

import ContactEditor from "@/components/herd-contact/ContactEditor";
import ContactView from "@/components/herd-contact/ContactView";
import type { ReaderContact } from "@/components/herd-contact/contactTypes";

afterEach(cleanup);

const persons = [
  { id: 1, name: "Anna Exempel", role: "huvudmedlem" },
  { id: 2, name: "Ida Exempel", role: "familjemedlem" },
];

const contact = (over: Partial<ReaderContact["rows"]> = {}): ReaderContact => ({
  mode: "person",
  contact_member: persons[0],
  persons,
  rows: {
    name: {
      source: "person",
      privacy: "private",
      pending: false,
      alternative: null,
    },
    email: {
      source: "person",
      privacy: "authenticated",
      pending: false,
      alternative: null,
    },
    mobile_phone: {
      source: "egen",
      privacy: "authenticated",
      pending: true,
      alternative: "070-111 11 11",
    },
    physical_address: {
      source: "medlemskap",
      privacy: "private",
      pending: false,
      alternative: null,
    },
    ...over,
  },
});

const herd = {
  name: "Anna Exempel",
  email: "anna@example.invalid",
  mobile_phone: "070-000 00 00",
  physical_address: "Byvägen 1|623 00|Roma",
};

const ok = () => vi.fn().mockResolvedValue({ success: true, data: {} });
const group = (name: string) => within(screen.getByRole("group", { name }));
const save = () =>
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));

describe("ContactEditor", () => {
  it("sends only changed rows with shown state", async () => {
    const onSave = ok();
    render(<ContactEditor herd={herd} contact={contact()} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-222 22 22" },
    });
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith({
      contact: {
        shown: { mode: "person", contact_member: 1, name: null },
        rows: {
          mobile_phone: {
            source: "egen",
            value: "070-222 22 22",
            privacy: "authenticated",
            shown: {
              source: "egen",
              value: "070-000 00 00",
              alternative: "070-111 11 11",
              privacy: "authenticated",
            },
          },
        },
      },
    });
  });

  it("switching to medlemskapet shows readonly value", async () => {
    const onSave = ok();
    render(<ContactEditor herd={herd} contact={contact()} onSave={onSave} />);
    fireEvent.click(
      group("Mobil").getByRole("button", { name: "Från medlemskapet" }),
    );
    expect(screen.queryByRole("textbox", { name: "Mobil" })).toBeNull();
    expect(screen.getByText("070-111 11 11")).toBeTruthy();
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const row = onSave.mock.calls[0][0].contact.rows.mobile_phone;
    expect(row).toMatchObject({
      source: "medlemskap",
      value: null,
      shown: {
        source: "egen",
        value: "070-000 00 00",
        alternative: "070-111 11 11",
      },
    });
  });

  it("annan kontakt locks email and mobile to egen", async () => {
    const onSave = ok();
    render(<ContactEditor herd={herd} contact={contact()} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText("Kontaktperson"), {
      target: { value: "annan" },
    });
    for (const name of ["E-post", "Mobil"]) {
      const btn = group(name).getByRole("button", {
        name: "Från medlemskapet",
      });
      expect((btn as HTMLButtonElement).disabled).toBe(true);
      expect(screen.getByRole("textbox", { name })).toBeTruthy();
    }
    fireEvent.change(screen.getByRole("textbox", { name: "Namn" }), {
      target: { value: "Olle Påhittad" },
    });
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const sent = onSave.mock.calls[0][0].contact;
    expect(sent).toMatchObject({ contact_member: null, name: "Olle Påhittad" });
    expect(sent.rows.email.source).toBe("egen");
  });

  it("own address keeps postal code and city", async () => {
    const onSave = ok();
    const own = contact({
      physical_address: {
        source: "egen",
        privacy: "private",
        pending: false,
        alternative: null,
      },
    });
    render(<ContactEditor herd={herd} contact={own} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Gatuadress" }), {
      target: { value: "Nyvägen 2" },
    });
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].contact.rows.physical_address.value).toBe(
      "Nyvägen 2|623 00|Roma",
    );
  });

  it("a bare street address is saved unchanged", async () => {
    const onSave = ok();
    const own = contact({
      physical_address: {
        source: "egen",
        privacy: "private",
        pending: false,
        alternative: null,
      },
    });
    render(
      <ContactEditor
        herd={{ ...herd, physical_address: "Byvägen 1" }}
        contact={own}
        onSave={onSave}
      />,
    );
    fireEvent.click(
      group("Vem ser adressen").getByRole("button", { name: /Inloggade/ }),
    );
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].contact.rows.physical_address.value).toBe(
      "Byvägen 1",
    );
  });

  it("a non-reader sends only own rows without top-level state", async () => {
    const onSave = ok();
    render(
      <ContactEditor
        herd={herd}
        contact={{
          rows: {
            email: { source: "hamtad" },
            mobile_phone: {
              source: "egen",
              value: "070-000 00 00",
              privacy: "private",
            },
          },
        }}
        onSave={onSave}
      />,
    );
    expect(screen.queryByLabelText("Kontaktperson")).toBeNull();
    expect(screen.getByText("Hämtas från medlemskapet")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-333 33 33" },
    });
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toEqual({
      contact: {
        rows: {
          mobile_phone: {
            source: "egen",
            value: "070-333 33 33",
            privacy: "private",
            shown: {
              source: "egen",
              value: "070-000 00 00",
              privacy: "private",
            },
          },
        },
      },
    });
  });

  it("conflict reloads form", async () => {
    const onSave = vi.fn().mockResolvedValue({
      success: false,
      error: "x",
      status: 409,
      type: "contact-changed",
    });
    const onReload = vi.fn();
    const { rerender } = render(
      <ContactEditor
        herd={herd}
        contact={contact()}
        onSave={onSave}
        onReload={onReload}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-222 22 22" },
    });
    save();
    await waitFor(() => expect(onReload).toHaveBeenCalled());
    expect(screen.getByRole("alert").textContent).toMatch(/har ändrats/);
    rerender(
      <ContactEditor
        herd={{ ...herd, mobile_phone: "070-999 99 99" }}
        contact={contact()}
        onSave={onSave}
        onReload={onReload}
      />,
    );
    expect(
      (screen.getByRole("textbox", { name: "Mobil" }) as HTMLInputElement)
        .value,
    ).toBe("070-999 99 99");
  });
});

describe("ContactView answers", () => {
  it("answer buttons send behall and anvand", async () => {
    const onSave = ok();
    render(<ContactView herd={herd} contact={contact()} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Ja, behåll" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].contact.rows.mobile_phone).toMatchObject({
      source: "egen",
      answer: "behall",
      shown: {
        source: "egen",
        value: "070-000 00 00",
        alternative: "070-111 11 11",
      },
    });
    expect(onSave.mock.calls[0][0].contact.shown).toEqual({
      mode: "person",
      contact_member: 1,
      name: null,
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Använd medlemskapets" }),
    );
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1][0].contact.rows.mobile_phone).toMatchObject({
      source: "medlemskap",
      answer: "anvand",
    });
  });

  it("groups rows by source and names the huvudmedlem in the footnote", () => {
    render(<ContactView herd={herd} contact={contact()} />);
    expect(screen.getByText("Från ditt medlemskap")).toBeTruthy();
    expect(screen.getByText("Egna för besättningen")).toBeTruthy();
    expect(screen.getByText(/ändrar Anna själv under/)).toBeTruthy();
  });
});

describe("review fixes", () => {
  const fritext = (): ReaderContact => ({
    ...contact(),
    mode: "fritext",
    contact_member: null,
    rows: {
      ...contact().rows,
      name: {
        source: "egen",
        privacy: "authenticated",
        pending: true,
        alternative: "Anna Exempel",
      },
    },
  });
  const fherd = { ...herd, name: "Anna och Per Exempel" };

  it("name row asks and answers behall and anvand", async () => {
    const onSave = ok();
    render(<ContactView herd={fherd} contact={fritext()} onSave={onSave} />);
    const q = within(screen.getByRole("group", { name: "Namnet skiljer sig" }));
    fireEvent.click(q.getByRole("button", { name: "Ja, behåll" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].contact.rows.name).toMatchObject({
      source: "egen",
      answer: "behall",
      shown: {
        source: "egen",
        value: "Anna och Per Exempel",
        alternative: "Anna Exempel",
      },
    });
    fireEvent.click(q.getByRole("button", { name: "Använd medlemskapets" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1][0].contact.rows.name).toMatchObject({
      source: "medlemskap",
      answer: "anvand",
    });
  });

  it("a shared name can be made private", async () => {
    const onSave = ok();
    const c = contact();
    c.rows.name.privacy = "authenticated";
    render(<ContactEditor herd={herd} contact={c} onSave={onSave} />);
    fireEvent.click(
      group("Vem ser namnet").getByRole("button", {
        name: "Endast genbanksansvarig",
      }),
    );
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].contact.rows.name).toEqual({
      source: "medlemskap",
      value: null,
      privacy: "private",
      shown: {
        source: "person",
        value: "Anna Exempel",
        alternative: null,
        privacy: "authenticated",
      },
    });
  });

  it("public shows its own label in view and editor", () => {
    const c = contact();
    c.rows.email.privacy = "public";
    render(<ContactView herd={herd} contact={c} />);
    expect(screen.getAllByText("Synligt för alla").length).toBeGreaterThan(0);
    cleanup();
    render(<ContactEditor herd={herd} contact={c} onSave={ok()} />);
    const chip = group("Vem ser e-posten").getByRole("button", {
      name: "Synligt för alla",
    });
    expect(chip.getAttribute("aria-pressed")).toBe("true");
  });

  const plain = {
    rows: {
      email: {
        source: "egen" as const,
        value: "a@example.invalid",
        privacy: "private" as const,
      },
    },
  };

  it("an own email can be cleared and the server decides", async () => {
    const onSave = ok();
    render(
      <ContactEditor
        herd={{ email: "a@example.invalid" }}
        contact={plain}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "E-post" }), {
      target: { value: "" },
    });
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].contact.rows.email).toMatchObject({
      source: "egen",
      value: null,
    });
    cleanup();
    const refuse = vi.fn().mockResolvedValue({
      success: false,
      error: "Nej, det går inte.",
      status: 403,
    });
    render(
      <ContactEditor
        herd={{ email: "a@example.invalid" }}
        contact={plain}
        onSave={refuse}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "E-post" }), {
      target: { value: "" },
    });
    save();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Nej, det går inte.",
    );
  });

  it("own row without alternative has no source switch", () => {
    const own = contact({
      physical_address: {
        source: "egen",
        privacy: "private",
        pending: false,
        alternative: null,
      },
    });
    render(<ContactEditor herd={herd} contact={own} onSave={ok()} />);
    expect(screen.queryByRole("group", { name: "Adress" })).toBeNull();
  });

  it("a source switch keeps the row's privacy", async () => {
    const onSave = ok();
    render(<ContactEditor herd={herd} contact={contact()} onSave={onSave} />);
    const seg = group("Mobil");
    fireEvent.click(seg.getByRole("button", { name: "Egen" })); // current source: no-op
    fireEvent.click(seg.getByRole("button", { name: "Från medlemskapet" }));
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].contact.rows.mobile_phone.privacy).toBe(
      "authenticated",
    );
  });

  it("the draft survives a new herd object from another card's save", () => {
    const c = contact();
    const { rerender } = render(
      <ContactEditor herd={herd} contact={c} onSave={ok()} />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-555 55 55" },
    });
    rerender(
      <ContactEditor herd={{ ...herd }} contact={{ ...c }} onSave={ok()} />,
    );
    expect(
      (screen.getByRole("textbox", { name: "Mobil" }) as HTMLInputElement)
        .value,
    ).toBe("070-555 55 55");
  });
});

describe("review round 2", () => {
  const fr = (): ReaderContact => {
    const c = contact();
    return {
      ...c,
      mode: "fritext",
      contact_member: null,
      rows: {
        ...c.rows,
        name: {
          source: "egen",
          privacy: "authenticated",
          pending: false,
          alternative: null,
        },
      },
    };
  };
  const fh = { ...herd, name: "Anna och Per Exempel" };

  it("a renamed fritext contact carries its chosen privacy", async () => {
    const onSave = ok();
    render(<ContactEditor herd={fh} contact={fr()} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Namn" }), {
      target: { value: "Per Exempel" },
    });
    fireEvent.click(
      group("Vem ser namnet").getByRole("button", {
        name: "Endast genbanksansvarig",
      }),
    );
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const sent = onSave.mock.calls[0][0].contact;
    expect(sent.name).toBe("Per Exempel");
    expect(sent.rows.name).toMatchObject({
      source: "egen",
      value: "Per Exempel",
      privacy: "private",
    });
    expect(sent.rows.name.shown).toMatchObject({
      source: "egen",
      value: "Anna och Per Exempel",
      privacy: "authenticated",
    });
  });

  it("narrower data resets the editor at once", () => {
    const c = contact();
    const { rerender } = render(
      <ContactEditor herd={herd} contact={c} onSave={ok()} />,
    );
    expect(screen.getByLabelText("Kontaktperson")).toBeTruthy();
    rerender(
      <ContactEditor
        herd={{ ...herd }}
        contact={{
          rows: {
            email: { source: "hamtad" },
            mobile_phone: {
              source: "egen",
              value: "070-000 00 00",
              privacy: "private",
            },
          },
        }}
        onSave={ok()}
      />,
    );
    expect(screen.queryByLabelText("Kontaktperson")).toBeNull();
    expect(screen.getByText("Hämtas från medlemskapet")).toBeTruthy();
  });

  it("a 409 after another card's save is reloaded by the data after the conflict", async () => {
    const c = contact();
    const conflict = vi.fn().mockResolvedValue({
      success: false,
      error: "x",
      status: 409,
      type: "contact-changed",
    });
    const { rerender } = render(
      <ContactEditor herd={herd} contact={c} onSave={conflict} />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-555 55 55" },
    });
    rerender(
      <ContactEditor herd={{ ...herd }} contact={{ ...c }} onSave={conflict} />,
    );
    save();
    await waitFor(() => expect(conflict).toHaveBeenCalled());
    await screen.findByRole("alert");
    expect(
      (screen.getByRole("textbox", { name: "Mobil" }) as HTMLInputElement)
        .value,
    ).toBe("070-555 55 55");
    rerender(
      <ContactEditor
        herd={{ ...herd, mobile_phone: "070-999 99 99" }}
        contact={{ ...c }}
        onSave={conflict}
      />,
    );
    expect(
      (screen.getByRole("textbox", { name: "Mobil" }) as HTMLInputElement)
        .value,
    ).toBe("070-999 99 99");
  });

  it("a reader can clear an own mobile the register does not have", async () => {
    const onSave = ok();
    const c = contact();
    c.rows.mobile_phone.alternative = null;
    c.rows.mobile_phone.pending = false;
    render(<ContactEditor herd={herd} contact={c} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "" },
    });
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].contact.rows.mobile_phone).toMatchObject({
      source: "egen",
      value: null,
      shown: { source: "egen", value: "070-000 00 00", alternative: null },
    });
  });

  it("a pending fritext name without alternative still asks, keep only", async () => {
    const onSave = ok();
    const c = fr();
    c.rows.name.pending = true;
    render(<ContactView herd={fh} contact={c} onSave={onSave} />);
    const q = within(
      screen.getByRole("group", { name: "Namnet behöver ett svar" }),
    );
    expect(
      q.queryByRole("button", { name: "Använd medlemskapets" }),
    ).toBeNull();
    fireEvent.click(q.getByRole("button", { name: "Ja, behåll" }));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].contact.rows.name).toMatchObject({
      source: "egen",
      answer: "behall",
    });
  });
});

describe("review round 3", () => {
  it("a fetched row switched to Egen and left empty is blocked; an own row without alternative may be cleared", async () => {
    const onSave = ok();
    const c = contact();
    c.rows.email.privacy = "private";
    render(<ContactEditor herd={herd} contact={c} onSave={onSave} />);
    fireEvent.click(group("E-post").getByRole("button", { name: "Egen" }));
    fireEvent.change(screen.getByRole("textbox", { name: "E-post" }), {
      target: { value: "" },
    });
    save();
    expect((await screen.findByRole("alert")).textContent).toMatch(/e-post/);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("an own row that turns fetched on reload leaves no old value in the form", () => {
    const own = {
      rows: {
        email: {
          source: "egen" as const,
          value: "old@example.invalid",
          privacy: "private" as const,
        },
      },
    };
    const { rerender } = render(
      <ContactEditor
        herd={{ email: "old@example.invalid" }}
        contact={own}
        onSave={ok()}
      />,
    );
    rerender(
      <ContactEditor
        herd={{}}
        contact={{ rows: { email: { source: "hamtad" } } }}
        onSave={ok()}
      />,
    );
    expect(document.body.innerHTML).not.toContain("old@example.invalid");
  });

  it("a person change sends the chosen name privacy", async () => {
    const onSave = ok();
    render(<ContactEditor herd={herd} contact={contact()} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText("Kontaktperson"), {
      target: { value: "2" },
    });
    fireEvent.click(
      group("Vem ser namnet").getByRole("button", {
        name: "Inloggade besättningar",
      }),
    );
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const sent = onSave.mock.calls[0][0].contact;
    expect(sent.contact_member).toBe(2);
    expect(sent.rows.name).toMatchObject({
      source: "medlemskap",
      value: null,
      privacy: "authenticated",
    });
  });
});

describe("review round 4", () => {
  it("an empty fetched address switched to Egen is blocked, also with blank parts", async () => {
    for (const postal of ["", " "]) {
      const onSave = ok();
      render(
        <ContactEditor
          herd={{ ...herd, physical_address: "" }}
          contact={contact()}
          onSave={onSave}
        />,
      );
      fireEvent.click(group("Adress").getByRole("button", { name: "Egen" }));
      if (postal)
        fireEvent.change(screen.getByRole("textbox", { name: "Postnummer" }), {
          target: { value: postal },
        });
      fireEvent.click(
        group("Vem ser adressen").getByRole("button", {
          name: "Inloggade besättningar",
        }),
      );
      save();
      expect((await screen.findByRole("alert")).textContent).toMatch(/adress/);
      expect(onSave).not.toHaveBeenCalled();
      cleanup();
    }
  });

  const fritextAs = (): ReaderContact => {
    const c = contact();
    return {
      ...c,
      mode: "fritext",
      contact_member: null,
      rows: {
        ...c.rows,
        name: {
          source: "egen",
          privacy: "authenticated",
          pending: false,
          alternative: null,
        },
      },
    };
  };

  it.each<
    [string, string, "private" | "authenticated", string | null, boolean]
  >([
    [
      "wider, same name",
      "Ida Exempel",
      "private",
      "Inloggade besättningar",
      true,
    ],
    [
      "narrower, another name",
      "Olle Påhittad",
      "authenticated",
      "Endast genbanksansvarig",
      true,
    ],
    ["no privacy change", "Olle Påhittad", "authenticated", null, false],
  ])("fritext to a person: %s", async (_case, name, privacy, chip, blocked) => {
    const onSave = ok();
    const c = fritextAs();
    c.rows.name.privacy = privacy;
    render(
      <ContactEditor herd={{ ...herd, name }} contact={c} onSave={onSave} />,
    );
    fireEvent.change(screen.getByLabelText("Kontaktperson"), {
      target: { value: "2" },
    });
    if (chip)
      fireEvent.click(
        group("Vem ser namnet").getByRole("button", { name: chip }),
      );
    save();
    if (blocked) {
      expect((await screen.findByRole("alert")).textContent).toBe(
        "Spara bytet av kontaktperson först. Ändra sedan vem som ser namnet.",
      );
      expect(onSave).not.toHaveBeenCalled();
    } else {
      await waitFor(() => expect(onSave).toHaveBeenCalled());
      expect(onSave.mock.calls[0][0].contact.contact_member).toBe(2);
    }
  });

  it("a row that turns fetched on reload drops only that row; other drafts keep their shown state", async () => {
    const onSave = ok();
    const own = {
      rows: {
        email: {
          source: "egen" as const,
          value: "old@example.invalid",
          privacy: "private" as const,
        },
        mobile_phone: {
          source: "egen" as const,
          value: "070-000 00 00",
          privacy: "private" as const,
        },
      },
    };
    const { rerender } = render(
      <ContactEditor
        herd={{ email: "old@example.invalid", mobile_phone: "070-000 00 00" }}
        contact={own}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-444 44 44" },
    });
    rerender(
      <ContactEditor
        herd={{ mobile_phone: "070-999 99 99" }}
        contact={{
          rows: {
            email: { source: "hamtad" },
            mobile_phone: { ...own.rows.mobile_phone, value: "070-999 99 99" },
          },
        }}
        onSave={onSave}
      />,
    );
    expect(document.body.innerHTML).not.toContain("old@example.invalid");
    expect(screen.getByText("Hämtas från medlemskapet")).toBeTruthy();
    expect(
      (screen.getByRole("textbox", { name: "Mobil" }) as HTMLInputElement)
        .value,
    ).toBe("070-444 44 44");
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toEqual({
      contact: {
        rows: {
          mobile_phone: {
            source: "egen",
            value: "070-444 44 44",
            privacy: "private",
            shown: {
              source: "egen",
              value: "070-000 00 00",
              privacy: "private",
            },
          },
        },
      },
    });
  });

  it("Spara without changes saves nothing and reports no success", async () => {
    const onSave = ok();
    const onDone = vi.fn();
    render(
      <ContactEditor
        herd={herd}
        contact={contact()}
        onSave={onSave}
        onDone={onDone}
      />,
    );
    save();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Inga ändringar att spara.",
    );
    expect(onSave).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });
});

describe("review round 5", () => {
  const own = (over: Partial<ReaderContact["rows"]["physical_address"]> = {}) =>
    contact({
      physical_address: {
        source: "egen",
        privacy: "private",
        pending: false,
        alternative: null,
        ...over,
      },
    });

  it("a cleared own address with blank parts is sent as null", async () => {
    const onSave = ok();
    render(<ContactEditor herd={herd} contact={own()} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Gatuadress" }), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Postnummer" }), {
      target: { value: " " },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Ort" }), {
      target: { value: "" },
    });
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(
      onSave.mock.calls[0][0].contact.rows.physical_address.value,
    ).toBeNull();
    cleanup();
    const onSave2 = ok();
    render(
      <ContactEditor
        herd={{ ...herd, physical_address: "||" }}
        contact={own()}
        onSave={onSave2}
      />,
    );
    fireEvent.click(
      group("Vem ser adressen").getByRole("button", {
        name: "Inloggade besättningar",
      }),
    );
    save();
    await waitFor(() => expect(onSave2).toHaveBeenCalled());
    expect(
      onSave2.mock.calls[0][0].contact.rows.physical_address.value,
    ).toBeNull();
  });

  const pendingFritext = (): ReaderContact => {
    const c = contact();
    return {
      ...c,
      mode: "fritext",
      contact_member: null,
      rows: {
        ...c.rows,
        name: {
          source: "egen",
          privacy: "private",
          pending: true,
          alternative: "Anna Exempel",
        },
      },
    };
  };
  const spaced = { ...herd, name: "Anna och Per Exempel " };

  it("an untouched fritext name with a trailing space is not sent", async () => {
    const onSave = ok();
    render(
      <ContactEditor
        herd={spaced}
        contact={pendingFritext()}
        onSave={onSave}
      />,
    );
    save();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Inga ändringar att spara.",
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("changing only the mobile or the name privacy sends no name change", async () => {
    const onSave = ok();
    render(
      <ContactEditor
        herd={spaced}
        contact={pendingFritext()}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Mobil" }), {
      target: { value: "070-222 22 22" },
    });
    save();
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const sent = onSave.mock.calls[0][0].contact;
    expect(sent).not.toHaveProperty("name");
    expect(sent).not.toHaveProperty("contact_member");
    expect(sent.rows).not.toHaveProperty("name");
    expect(Object.keys(sent.rows)).toEqual(["mobile_phone"]);
    cleanup();
    const onSave2 = ok();
    render(
      <ContactEditor
        herd={spaced}
        contact={pendingFritext()}
        onSave={onSave2}
      />,
    );
    fireEvent.click(
      group("Vem ser namnet").getByRole("button", {
        name: "Inloggade besättningar",
      }),
    );
    save();
    await waitFor(() => expect(onSave2).toHaveBeenCalled());
    const sent2 = onSave2.mock.calls[0][0].contact;
    expect(sent2).not.toHaveProperty("name");
    expect(sent2.rows.name).toMatchObject({
      source: "egen",
      privacy: "authenticated",
    });
    expect(sent2.rows.name).not.toHaveProperty("value");
  });
});
