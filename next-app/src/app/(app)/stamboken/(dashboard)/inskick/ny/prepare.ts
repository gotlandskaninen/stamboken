import { planImage } from "@/lib/inkorg";

// Downscale per planImage; anything the browser cannot decode goes unchanged.
// "from-image" applies the EXIF orientation while decoding, so the redrawn
// JPEG (which carries no EXIF) stays upright.
export async function prepare(file: File): Promise<File> {
  if (!file.type.startsWith("image/")) return file;
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return file;
  }
  try {
    const plan = planImage(file.type, {
      width: bitmap.width,
      height: bitmap.height,
    });
    if (plan.action === "keep") return file;
    const canvas = document.createElement("canvas");
    canvas.width = plan.width;
    canvas.height = plan.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, plan.width, plan.height);
    const blob = await new Promise<Blob | null>((r) =>
      canvas.toBlob(r, "image/jpeg", 0.85),
    );
    if (!blob) return file;
    return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", {
      type: "image/jpeg",
    });
  } finally {
    bitmap.close(); // phone photos are large: free the pixels at once
  }
}
