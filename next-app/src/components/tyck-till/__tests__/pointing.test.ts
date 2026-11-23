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

import { captureAround, describe, shrink } from "../pointing";

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
      ["<input value='Ada'>", "fältet ”Ada”"],
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
