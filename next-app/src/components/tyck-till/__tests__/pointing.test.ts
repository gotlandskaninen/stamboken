import {
  afterEach,
  beforeEach,
  describe as suite,
  expect,
  it,
  vi,
} from "vitest";

const toCanvas = vi.fn();
vi.mock("html-to-image", () => ({
  toCanvas: (...a: unknown[]) => toCanvas(...a),
}));

import { captureAround, describe, pickable, shrink } from "../pointing";

function html(markup: string): HTMLElement {
  document.body.innerHTML = markup;
  return document.body.firstElementChild as HTMLElement;
}

suite("describe", () => {
  it("names what was pointed at", () => {
    const cases: [string, string][] = [
      ["<button>Spara kull</button>", "knappen ”Spara kull”"],
      ["<a href='#'>Källkod</a>", "länken ”Källkod”"],
      ["<h2>Kaniner</h2>", "rubriken ”Kaniner”"],
      ["<ul><li>Ada G9999-2601</li></ul>", "raden ”Ada G9999-2601”"],
      [
        "<table><tbody><tr><td>Berit</td></tr></tbody></table>",
        "raden ”Berit”",
      ],
      ["<input value='Ada'>", "fältet"],
      ["<p>Några ord</p>", "texten ”Några ord”"],
    ];
    for (const [markup, want] of cases) {
      document.body.innerHTML = markup;
      const el = document.body.querySelector(
        "button, a, h2, li, tr, input, p",
      )!;
      expect(describe(el)).toBe(want);
    }
  });

  it("names a row in a facts list", () => {
    const el = html(
      "<dl class='facts'><div><dt>Född</dt> <dd>2026-11-02</dd></div></dl>",
    ).querySelector("div")!;
    expect(describe(el)).toBe("raden ”Född 2026-11-02”");
  });

  it("puts a space between blocks and a stat cell's label first", () => {
    const cell = html(
      "<div class='cell'><div>inga</div><div class='sb-stat-label'>Besättningar</div></div>",
    );
    expect(describe(cell)).toBe("texten ”Besättningar: inga”");
    document.body.innerHTML =
      "<table><tbody><tr><td>Ada</td><td>G9999-2601</td><td>Hona</td></tr></tbody></table>";
    expect(describe(document.querySelector("tr")!)).toBe(
      "raden ”Ada G9999-2601 Hona”",
    );
    const card = html(
      "<div class='card'><h2>Kullen</h2><p>Född<br>2026-11-02</p></div>",
    );
    expect(describe(card)).toBe("rutan ”Kullen Född 2026-11-02”");
  });

  it("takes a whole stat cell for a tap on its value or label, not the strip", () => {
    document.body.innerHTML =
      "<div class='strip'>" +
      "<div class='cell'><div class='v'>7</div><div class='sb-stat-label'>Aktiva kaniner</div></div>" +
      "<div class='cell'><div>3</div><div class='sb-stat-label'>Avelsdjur</div></div></div>";
    const q = (sel: string) => document.querySelector(sel)!;
    expect(describe(pickable(q(".v")))).toBe("texten ”Aktiva kaniner: 7”");
    expect(describe(pickable(q(".sb-stat-label")))).toBe(
      "texten ”Aktiva kaniner: 7”",
    );
    expect(describe(q(".strip"))).toBe("texten ”7 Aktiva kaniner 3 Avelsdjur”");
  });

  it("parts text before a nested block in a cell", () => {
    document.body.innerHTML =
      "<table><tbody><tr><td>Inloggning<div>login_handler</div></td><td>10 anrop per timme</td></tr></tbody></table>";
    expect(describe(document.querySelector("tr")!)).toBe(
      "raden ”Inloggning login_handler 10 anrop per timme”",
    );
  });

  it("leaves hidden parts of a field label out", () => {
    document.body.innerHTML =
      "<label for='f'>Kod <span data-tyck-till='dolj'>DOLD</span></label><input id='f' value='x'>" +
      "<label for='g' data-tyck-till='dolj'>DOLD</label><input id='g' placeholder='Sök' value='y'>";
    expect(describe(document.getElementById("f")!)).toBe("fältet ”Kod”");
    expect(describe(document.getElementById("g")!)).toBe("fältet ”Sök”");
  });

  it("cuts long text at 50 characters", () => {
    const el = html(`<p>${"a".repeat(60)}</p>`);
    expect(describe(el)).toBe(`texten ”${"a".repeat(50)}…”`);
  });

  it("gives no text for something hidden, nor for what is inside it", () => {
    const el = html(
      "<footer><span data-tyck-till='dolj'>token 1234</span></footer>",
    );
    const span = el.querySelector("span")!;
    expect(describe(span)).toBe("en dold uppgift");
    document.body.innerHTML =
      "<div data-tyck-till='dolj'><b>token 1234</b></div>";
    expect(describe(document.querySelector("b")!)).toBe("en dold uppgift");
  });

  it("names a field by its label, never by what is typed in it", () => {
    document.body.innerHTML =
      "<label for='e'>E-post</label><input id='e' value='anna@example.org'>" +
      "<input aria-label='Kod' value='Brokig-1234'>" +
      "<input placeholder='Sök kanin' value='G9999-2601'>" +
      "<div class='card'><h2>Anteckning</h2><textarea>hemlig text</textarea></div>";
    const q = (sel: string) => document.body.querySelector(sel)!;
    expect(describe(q("#e"))).toBe("fältet ”E-post”");
    expect(describe(q("[aria-label]"))).toBe("fältet ”Kod”");
    expect(describe(q("[placeholder]"))).toBe("fältet ”Sök kanin”");
    expect(describe(q(".card"))).toBe("rutan ”Anteckning”");
    expect(describe(q("textarea"))).toBe("fältet");
  });

  it("leaves the choices of a list out, also when the label wraps it", () => {
    document.body.innerHTML =
      "<label>Handläggare <select><option>Alla</option><option>Test Person</option></select></label>";
    const q = (sel: string) => document.body.querySelector(sel)!;
    expect(describe(q("select"))).toBe("fältet ”Handläggare”");
    expect(describe(q("label"))).toBe("texten ”Handläggare”");
  });

  it("reads .value from nothing", () => {
    document.body.innerHTML =
      "<ul><li value='3'>Ada</li></ul><progress value='0.5'></progress><button value='x'>Spara</button>";
    const q = (sel: string) => document.body.querySelector(sel)!;
    expect(describe(q("li"))).toBe("raden ”Ada”");
    expect(describe(q("progress"))).toBe("texten");
    expect(describe(q("button"))).toBe("knappen ”Spara”");
  });

  it("leaves a hidden part out of the text of its parent", () => {
    const el = html(
      "<footer>Be säljaren <span data-tyck-till='dolj'>token 1234</span></footer>",
    );
    expect(describe(el)).not.toContain("1234");
  });
});

suite("captureAround", () => {
  beforeEach(() => {
    toCanvas.mockReset();
    toCanvas.mockResolvedValue({ width: 750, height: 2000 });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
    } as never);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((cb) =>
      cb(new Blob(["x"], { type: "image/jpeg" })),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("draws the page without what is marked hidden", async () => {
    const root = html(
      "<main><p id='a'>Synligt</p><span data-tyck-till='dolj'><i id='b'>token</i></span></main>",
    );
    const blob = await captureAround(root.querySelector("#a")!, document.body);
    expect(blob?.type).toBe("image/jpeg");
    const { filter } = toCanvas.mock.calls[0][1] as {
      filter: (n: Node) => boolean;
    };
    expect(filter(document.querySelector("#a")!)).toBe(true);
    expect(filter(document.querySelector("#b")!)).toBe(false);
    expect(filter(document.querySelector("span")!)).toBe(false);
    expect(filter(document.createTextNode("text"))).toBe(true);
  });

  it("scales by the canvas it got when html-to-image shrank it", async () => {
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
    } as never);
    vi.stubGlobal("devicePixelRatio", 2);
    // 375 x 8000 css px would be 1500 px wide at ratio 2; the canvas came back 750 x 2000 (scale 0.25).
    const root = html("<main><p id='a'>Mitt</p></main>");
    vi.spyOn(root, "getBoundingClientRect").mockReturnValue({
      top: 0,
      left: 0,
      width: 375,
      height: 8000,
    } as DOMRect);
    vi.spyOn(
      root.querySelector("#a")!,
      "getBoundingClientRect",
    ).mockReturnValue({
      top: 4000,
      left: 0,
      width: 100,
      height: 20,
    } as DOMRect);
    await captureAround(root.querySelector("#a")!, root);
    vi.unstubAllGlobals();
    // h = min(768, 469, 8000) = 469; top = 4010 - 234.5 = 3775.5 -> sy = 944, sh = 117 at scale 0.25
    expect(drawImage).toHaveBeenCalledWith(
      expect.anything(),
      0,
      944,
      750,
      117,
      0,
      0,
      750,
      117,
    );
  });

  it("gives null when the browser cannot draw the page", async () => {
    toCanvas.mockRejectedValue(new Error("tainted"));
    const root = html("<p>Hej</p>");
    expect(await captureAround(root, document.body)).toBeNull();
  });
});

suite("shrink", () => {
  const sizes: [number, number][] = [];
  beforeEach(() => {
    sizes.length = 0;
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
    } as never);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
      function (this: HTMLCanvasElement, cb) {
        sizes.push([this.width, this.height]);
        cb(new Blob(["x"], { type: "image/jpeg" }));
      },
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("scales to 2000 px on the longest side and gives JPEG", async () => {
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn().mockResolvedValue({ width: 4000, height: 3000, close: vi.fn() }),
    );
    const out = await shrink(new Blob(["png"], { type: "image/png" }));
    expect(out.type).toBe("image/jpeg");
    expect(sizes).toEqual([[2000, 1500]]);
  });

  it("does not enlarge a small image", async () => {
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn().mockResolvedValue({ width: 800, height: 600, close: vi.fn() }),
    );
    await shrink(new Blob(["png"], { type: "image/png" }));
    expect(sizes).toEqual([[800, 600]]);
  });

  it("returns the original when the browser cannot draw it (HEIC in Chrome)", async () => {
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn().mockRejectedValue(new Error("undecodable")),
    );
    const heic = new Blob(["heic"], { type: "image/heic" });
    expect(await shrink(heic)).toBe(heic);
  });
});
