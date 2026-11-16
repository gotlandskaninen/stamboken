import { afterEach, describe, expect, it, vi } from "vitest";
import { prepare } from "@/app/(app)/stamboken/(dashboard)/inskick/ny/prepare";

const png = () => new File(["x"], "foto.png", { type: "image/png" });
const bitmap = (width = 4000, height = 3000) => ({
  width,
  height,
  close: vi.fn(),
});

function stubBitmap(b: ReturnType<typeof bitmap>) {
  const create = vi.fn(async () => b);
  vi.stubGlobal("createImageBitmap", create);
  return create;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("prepare", () => {
  it("decodes upright, redraws as JPEG and closes the bitmap", async () => {
    const b = bitmap();
    const create = stubBitmap(b);
    const draw = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: draw,
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((cb) =>
      cb(new Blob(["j"], { type: "image/jpeg" })),
    );
    const out = await prepare(png());
    expect(create).toHaveBeenCalledWith(expect.any(File), {
      imageOrientation: "from-image",
    });
    expect(draw).toHaveBeenCalledWith(b, 0, 0, 3000, 2250);
    expect(out.name).toBe("foto.jpg");
    expect(b.close).toHaveBeenCalledOnce();
  });

  it("sends the file unchanged when there is no 2D context, and still closes", async () => {
    const b = bitmap();
    stubBitmap(b);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const file = png();
    expect(await prepare(file)).toBe(file);
    expect(b.close).toHaveBeenCalledOnce();
  });

  it("sends a file the browser cannot decode unchanged", async () => {
    vi.stubGlobal("createImageBitmap", async () => {
      throw new Error("decode");
    });
    const file = png();
    expect(await prepare(file)).toBe(file);
  });
});
