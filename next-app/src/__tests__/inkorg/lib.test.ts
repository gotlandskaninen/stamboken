import { describe, expect, it } from "vitest";
import {
  buildSalePayload,
  buildSavePayload,
  canEditDocuments,
  canSave,
  CLOSED_STATES,
  initialCertForm,
  initialSaveMode,
  itemActions,
  nextOpenDocument,
  numberCheckOf,
  OPEN_STATES,
  people,
  problemField,
  problemText,
  waited,
  type CertForm,
  type InboxItem,
  type ItemAction,
  type ItemState,
  type QueueUser,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

// Synthetic users: an admin, a manager of genebank 1, of genebank 2, and a
// helper (in the queue, no manager role).
const admin: QueueUser = { id: 1, is_admin: true, is_manager: null };
const boss1: QueueUser = { id: 2, is_admin: false, is_manager: [1] };
const boss2: QueueUser = { id: 5, is_admin: false, is_manager: [2] };
const helper: QueueUser = { id: 3, is_admin: false, is_manager: null };
const someone = { id: 9, name: "Konto 9" };
const holder = (u: QueueUser) => ({ id: u.id, name: `Konto ${u.id}` });

const item = (
  state: ItemState,
  assigned: { id: number; name: string } | null,
  genebank: number | null = 1,
) => ({ state, assigned_to: assigned, genebank_id: genebank });

describe("itemActions, by docs/inkorg.md", () => {
  it.each<[string, ReturnType<typeof item>, QueueUser, ItemAction[]]>([
    ["new item, helper", item("ny", null), helper, ["ta"]],
    ["new item, its manager", item("ny", null), boss1, ["ta", "tilldela"]],
    ["new item, another genebank's manager", item("ny", null), boss2, ["ta"]],
    [
      "new item without genebank, any manager",
      item("ny", null, null),
      boss2,
      ["ta", "tilldela"],
    ],
    [
      "with the manager",
      item("hos_genbanksansvarig", null),
      boss1,
      ["ta", "tilldela"],
    ],
    [
      "taken by me",
      item("tagen", holder(helper)),
      helper,
      [
        "hos_genbanksansvarig",
        "vantar_foralder",
        "ofullstandig",
        "dubblett",
        "skrap",
      ],
    ],
    [
      "taken by me, a manager",
      item("tagen", holder(boss1)),
      boss1,
      [
        "tilldela",
        "hos_genbanksansvarig",
        "vantar_foralder",
        "ofullstandig",
        "dubblett",
        "skrap",
      ],
    ],
    [
      "taken by someone else, helper",
      item("tagen", someone),
      helper,
      ["ta_over"],
    ],
    [
      "taken by someone else, admin",
      item("tagen", someone),
      admin,
      ["ta_over", "tilldela"],
    ],
    [
      "mine, waiting for a parent",
      item("vantar_foralder", holder(helper)),
      helper,
      ["arbeta_vidare", "dubblett", "skrap"],
    ],
    [
      "mine, incomplete",
      item("ofullstandig", holder(helper)),
      helper,
      ["arbeta_vidare", "dubblett", "skrap"],
    ],
    [
      "mine, waiting for the breeder",
      item("vantar_uppfodare", holder(helper)),
      helper,
      ["arbeta_vidare", "dubblett", "skrap"],
    ],
    [
      "someone else's, waiting",
      item("vantar_foralder", someone),
      helper,
      ["ta_over"],
    ],
    ["done, its manager", item("klar", someone), boss1, ["oppna"]],
    ["duplicate, admin", item("dubblett", someone), admin, ["oppna"]],
    ["junk, another genebank's manager", item("skrap", someone), boss2, []],
    [
      "done, helper (even the last handler)",
      item("klar", holder(helper)),
      helper,
      [],
    ],
  ])("%s", (_name, facts, user, expected) => {
    expect(itemActions(facts, user)).toEqual(expected);
  });

  // The "Byta läge" table: target state -> the states …/lage accepts it from.
  const LAGE_FROM: Partial<Record<ItemAction, ItemState[]>> = {
    arbeta_vidare: ["vantar_foralder", "ofullstandig", "vantar_uppfodare"], // via …/ta
    hos_genbanksansvarig: ["tagen"],
    vantar_foralder: ["tagen"],
    ofullstandig: ["tagen"],
    dubblett: ["tagen", "vantar_uppfodare", "vantar_foralder", "ofullstandig"],
    skrap: ["tagen", "vantar_uppfodare", "vantar_foralder", "ofullstandig"],
    oppna: ["klar", "dubblett", "skrap"],
  };

  it("never offers a state change the doc forbids, for any role, state or handler", () => {
    // ny and hos_genbanksansvarig never have a handler, the held states always do
    for (const state of [...OPEN_STATES, ...CLOSED_STATES])
      for (const user of [admin, boss1, boss2, helper])
        for (const assigned of state === "ny" ||
        state === "hos_genbanksansvarig"
          ? [null]
          : [someone, holder(user)])
          for (const action of itemActions(item(state, assigned), user)) {
            const from = LAGE_FROM[action];
            if (from) expect(from, `${action} from ${state}`).toContain(state);
            if (action === "oppna")
              expect(user === admin || user === boss1).toBe(true);
            if (action === "tilldela")
              expect(CLOSED_STATES).not.toContain(state);
            if (from && action !== "oppna") expect(assigned?.id).toBe(user.id);
          }
  });
});

describe("klar for an item without documents", () => {
  const empty = (state: ItemState, assigned: { id: number; name: string }) => ({
    ...item(state, assigned),
    documents: 0,
  });
  it("is offered to the handler of a held item, whatever its kind", () => {
    for (const state of ["tagen", "ofullstandig", "vantar_uppfodare"] as const)
      expect(itemActions(empty(state, holder(helper)), helper)).toContain(
        "klar",
      );
    // the item arrives with an array of documents in the working view
    expect(
      itemActions({ ...item("tagen", holder(helper)), documents: [] }, helper),
    ).toContain("klar");
  });
  it("is not offered with documents, to others, or on a closed item", () => {
    const withDocs = { ...item("tagen", holder(helper)), documents: 2 };
    expect(itemActions(withDocs, helper)).not.toContain("klar");
    expect(itemActions(empty("tagen", someone), helper)).not.toContain("klar");
    expect(itemActions(empty("klar", holder(helper)), helper)).not.toContain(
      "klar",
    );
  });
});

describe("the two gates", () => {
  const facts = (
    state: ItemState,
    assigned = holder(helper),
    ref_type: string | null = null,
  ) => ({
    ...item(state, assigned),
    ref_type,
  });
  it("saving needs the item taken by me, in tagen, without ref_type", () => {
    expect(canSave(facts("tagen"), helper)).toBe(true);
    expect(canSave(facts("vantar_foralder"), helper)).toBe(false);
    expect(canSave(facts("tagen", someone), helper)).toBe(false);
    expect(canSave(facts("tagen", holder(helper), "arsrapport"), helper)).toBe(
      false,
    );
    expect(canSave(facts("tagen", someone), admin)).toBe(false);
  });
  it("document changes need me as the handler in any held state", () => {
    expect(canEditDocuments(facts("ofullstandig"), helper)).toBe(true);
    expect(canEditDocuments(facts("tagen", someone), admin)).toBe(false);
    expect(canEditDocuments(facts("klar"), helper)).toBe(false);
  });
});

describe("nextOpenDocument", () => {
  const docs = [
    { id: 1, status: "klar" as const },
    { id: 2, status: "sparad" as const },
    { id: 3, status: "vantar_foralder" as const },
    { id: 4, status: "ny" as const },
  ];
  it("starts with the first open document", () => {
    expect(nextOpenDocument(docs, null)).toBe(2);
  });
  it("keeps a saved certificate until it is masked", () => {
    expect(nextOpenDocument(docs, 2)).toBe(2);
  });
  it("skips the current one, and documents waiting for a parent", () => {
    expect(nextOpenDocument(docs, 2, true)).toBe(4);
  });
  it("goes round the list", () => {
    expect(nextOpenDocument(docs, 4, true)).toBe(2);
  });
  it("is null when nothing is open", () => {
    expect(nextOpenDocument([{ id: 1, status: "avfardad" }], 1)).toBeNull();
    expect(nextOpenDocument([{ id: 1, status: "ny" }], 1, true)).toBeNull();
    expect(nextOpenDocument([], null)).toBeNull();
  });
});

describe("the …/spara payload", () => {
  const filled: CertForm = {
    ...initialCertForm(null),
    paper_number: " g9001-2512 ",
    paper_certificate: " 900123 ",
    name: "Testa",
    sex: "female",
    birth_date: "2025-05-10",
    color: "viltgrå",
    litter_size: "5",
    litter_size6w: "4",
    mother: "G9001-2131",
    father: "g9002-2214",
  };

  it("starts empty while there is no proposal", () => {
    expect(Object.values(initialCertForm(null)).every((v) => v === "")).toBe(
      true,
    );
  });
  it("takes a proposed value per field, none from avviker or osäker", () => {
    const form = initialCertForm({
      fields: {
        name: { value: "Testa", source: "läst" },
        litter_size: { value: 5, source: "härlett" },
        mother: { value: null, source: "avviker", read: "G9001 2131" },
        father: { value: null, source: "osäker", read: "G9OO2 2214" },
      },
      checks: [],
    });
    expect(form).toMatchObject({
      name: "Testa",
      litter_size: "5",
      mother: "",
      father: "",
    });
  });
  it("starts on the paper certificate when the proposal found the rabbit", () => {
    const found = { value: "G9001-2512", source: "läst" as const };
    expect(initialSaveMode({ fields: { individual: found }, checks: [] })).toBe(
      "pappersintyg",
    );
    expect(initialSaveMode({ fields: {}, checks: [] })).toBe("ny_kanin");
    expect(initialSaveMode(null)).toBe("ny_kanin");
  });
  it("a new rabbit: every field of the certificate, numbers trimmed and upper case", () => {
    expect(buildSavePayload("ny_kanin", filled)).toEqual({
      action: "ny_kanin",
      paper_number: "G9001-2512",
      paper_certificate: "900123",
      mother: "G9001-2131",
      father: "G9002-2214",
      birth_date: "2025-05-10",
      name: "Testa",
      sex: "female",
      color: "viltgrå",
      litter_size: 5,
      litter_size6w: 4,
    });
  });
  it("leaves out empty optional fields and counts that are not numbers", () => {
    const payload = buildSavePayload("ny_kanin", {
      ...filled,
      name: " ",
      sex: "",
      color: "",
      litter_size: "",
      litter_size6w: "fyra",
    });
    expect(payload).not.toHaveProperty("name");
    expect(payload).not.toHaveProperty("sex");
    expect(payload).not.toHaveProperty("color");
    expect(payload).not.toHaveProperty("litter_size");
    expect(payload).not.toHaveProperty("litter_size6w");
  });
  it("sends the chosen Stamboken number after a number conflict", () => {
    const resolution = {
      expected_number: "G9001-2513",
      choice: "use_stamboken_number" as const,
    };
    expect(buildSavePayload("ny_kanin", filled, resolution)).toMatchObject({
      resolution,
    });
  });
  it("the paper certificate on a rabbit that exists: three fields only", () => {
    expect(
      buildSavePayload("pappersintyg", { ...filled, individual: "g9001-2511" }),
    ).toEqual({
      action: "pappersintyg",
      individual: "G9001-2511",
      paper_certificate: "900123",
      paper_number: "G9001-2512",
    });
  });
});

describe("the …/overlat payload", () => {
  it("a buyer herd in the association", () => {
    expect(
      buildSalePayload({
        individual: "g9001-2511",
        herd: " g9002 ",
        outside: false,
        date: "2026-10-03",
      }),
    ).toEqual({ individual: "G9001-2511", herd: "G9002", date: "2026-10-03" });
  });
  it("a herd picked from the list sends its code, not its label", () => {
    const sale = {
      individual: "G9001-2511",
      outside: false,
      date: "2026-10-03",
    };
    expect(buildSalePayload({ ...sale, herd: "G9002 – Testgården" }).herd).toBe(
      "G9002",
    );
  });
  it("outside the association: the genebank's GX1 or MX1", () => {
    const sale = { herd: "G9002", outside: true, date: "2026-10-03" };
    expect(buildSalePayload({ ...sale, individual: "G9001-2511" }).herd).toBe(
      "GX1",
    );
    expect(buildSalePayload({ ...sale, individual: "M9001-2511" }).herd).toBe(
      "MX1",
    );
    expect(buildSalePayload({ ...sale, individual: "" }).herd).toBe("");
  });
});

describe("problemField", () => {
  const p = (status: number, title: string, detail: string) => ({
    status,
    title,
    detail,
  });
  it.each([
    [
      p(
        409,
        "number_conflict",
        "Numret G9001-2512 finns redan på en annan kanin.",
      ),
      "paper_number",
    ],
    [
      p(
        422,
        "too_young",
        "Kaninen måste vara minst 42 dagar gammal för att registreras.",
      ),
      "birth_date",
    ],
    [p(409, "litter_order_conflict", "Kullen är född före …"), "birth_date"],
    [
      p(
        400,
        "Ogiltig försäljning",
        "Försäljningsdatumet får inte ligga i framtiden.",
      ),
      "date",
    ],
    [
      p(
        400,
        "Ogiltig försäljning",
        "Individen kan bara flyttas till en besättning inom samma genbank.",
      ),
      "herd",
    ],
    [
      p(
        409,
        "Conflict",
        "A conflict prevented registration — a certificate number may already be in use",
      ),
      "paper_certificate",
    ],
    [
      p(409, "Conflict", "Mor eller far ändrades samtidigt. Försök igen."),
      null,
    ],
    [
      p(400, "Bad Request", "Välj mor och far bland registrerade kaniner."),
      "mother",
    ],
    [
      p(
        403,
        "Forbidden",
        "Modern finns inte i en besättning där du får registrera kaniner.",
      ),
      "mother",
    ],
    [
      p(
        400,
        "Bad Request",
        "Fadern måste vara registrerad i samma genbank som modern.",
      ),
      "father",
    ],
    [p(400, "Bad Request", "Ange antal födda (minst 1)."), "litter_size"],
    [
      p(400, "Bad Request", "Ange antal levande vid 6 veckor (minst 1)."),
      "litter_size6w",
    ],
    [
      p(
        400,
        "Bad Request",
        "Antal levande vid 6 veckor kan inte vara fler än antal födda.",
      ),
      "litter_size6w",
    ],
    [
      p(400, "Bad Request", "Födelsedatum måste anges som ÅÅÅÅ-MM-DD."),
      "birth_date",
    ],
    [
      p(400, "Bad Request", "name must be a string of at most 50 characters"),
      "name",
    ],
    [
      p(400, "Bad Request", "Intygsnummer krävs för pappersintyg."),
      "paper_certificate",
    ],
    [
      p(400, "Ogiltig begäran", "Individual certificate already exists"),
      "paper_certificate",
    ],
    [
      p(
        400,
        "Ogiltig begäran",
        "Ange intygsnumret (paper_certificate), högst 20 tecken.",
      ),
      "paper_certificate",
    ],
    [
      p(
        400,
        "Bad Request",
        "Skriv individnumret som det står på pappersintyget, till exempel G1274-2512.",
      ),
      "paper_number",
    ],
    [p(404, "Hittades inte", "Kaninen finns inte i Stamboken."), "individual"],
    [
      p(
        400,
        "Ogiltig begäran",
        "Ange köparens besättning (herd) och datum (date, ÅÅÅÅ-MM-DD).",
      ),
      "herd",
    ],
    [p(409, "Konflikt", "Ta posten först."), null],
    [p(400, "Bad Request", "Parningsdatum måste anges som ÅÅÅÅ-MM-DD."), null],
  ])("%o -> %s", (problem, field) => {
    expect(problemField(problem)).toBe(field);
  });

  it("goes by the field the API names before the title and the wording", () => {
    const named = (field: unknown, title = "Ogiltig begäran") => ({
      status: 400,
      title,
      detail: "Något som ingen mönstermatchning känner igen.",
      extensions: { field },
    });
    expect(problemField(named("mother"))).toBe("mother");
    expect(problemField(named("date", "number_conflict"))).toBe("date");
    // Not a field of the forms: the fallback decides.
    expect(problemField(named("__proto__"))).toBeNull();
    expect(problemField(named(42))).toBeNull();
  });

  it("words the bare rule keys and leaves Swedish details as they are", () => {
    const p = (detail: string) => ({
      status: 400,
      title: "Bad Request",
      detail,
    });
    expect(problemText(p("litter_size6w_required"))).toMatch(
      /levande efter 6 veckor/,
    );
    expect(problemField(p("litter_size6w_required"))).toBe("litter_size6w");
    expect(problemText(p("max_reached"))).toMatch(/Kullen är full/);
    expect(problemText(p("Ta posten först."))).toBe("Ta posten först.");
  });
});

describe("numberCheckOf", () => {
  it("reads the check from a 409 number_conflict", () => {
    const check = numberCheckOf({
      status: 409,
      title: "number_conflict",
      detail: "…",
      extensions: {
        stamboken_number: "G9001-2513",
        paper_number: "G9001-2512",
        check_status: "conflict",
        conflicts: [],
        choices: ["use_stamboken_number"],
        actions: [],
      },
    });
    expect(check).toMatchObject({
      status: "conflict",
      stamboken_number: "G9001-2513",
      paper_number: "G9001-2512",
    });
  });
  it("is null for any other problem", () => {
    expect(
      numberCheckOf({
        status: 409,
        title: "Konflikt",
        detail: "Ta posten först.",
      }),
    ).toBeNull();
  });
});

describe("waited", () => {
  const now = Date.parse("2026-11-14T12:00:00Z");
  it.each([
    ["2026-11-14T11:30:00Z", "under en timme"],
    ["2026-11-14T11:00:00Z", "1 timme"],
    ["2026-11-13T12:00:00Z", "24 timmar"],
    ["2026-11-10T12:00:00Z", "4 dagar"],
  ])("%s", (from, text) => expect(waited(from, now)).toBe(text));
});

describe("people", () => {
  it("is me, the handlers in the list and the extra, once each, by name", () => {
    const items = [
      { assigned_to: { id: 7, name: "Bertil" } },
      { assigned_to: null },
      { assigned_to: { id: 7, name: "Bertil" } },
    ] as InboxItem[];
    expect(
      people({ id: 3, name: "Cecilia" }, items, [{ id: 8, name: "Anna" }]).map(
        (p) => p.id,
      ),
    ).toEqual([8, 7, 3]);
  });
});
