/**
 * Crop a region from an image and return as JPEG blob.
 * Uses createImageBitmap for EXIF-aware decoding.
 */
export async function cropImage(
  imageUrl: string,
  cropArea: { x: number; y: number; width: number; height: number },
): Promise<Blob> {
  const response = await fetch(imageUrl);
  const imageBlob = await response.blob();
  const bitmap = await createImageBitmap(imageBlob);

  const canvas = document.createElement("canvas");
  canvas.width = cropArea.width;
  canvas.height = cropArea.height;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    bitmap.close();
    throw new Error("Failed to get canvas 2D context");
  }
  ctx.drawImage(
    bitmap,
    cropArea.x,
    cropArea.y,
    cropArea.width,
    cropArea.height,
    0,
    0,
    cropArea.width,
    cropArea.height,
  );

  bitmap.close();

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("Canvas toBlob failed"));
      },
      "image/jpeg",
      0.95,
    );
  });
}
