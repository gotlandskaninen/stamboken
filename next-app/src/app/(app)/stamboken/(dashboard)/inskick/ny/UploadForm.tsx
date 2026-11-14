"use client";

import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useSnackbar } from "@/components/SnackbarProvider";
import { planImage, warningText } from "@/lib/inkorg";
import { uploadIntyg } from "./actions";
import styles from "../inskick.module.css";

const MAX_TOTAL = 10 * 1024 * 1024; // nginx request limit, docs/inkorg.md

// Downscale per planImage; anything the browser cannot decode goes unchanged.
async function prepare(file: File): Promise<File> {
  let bitmap: ImageBitmap | null = null;
  if (file.type.startsWith("image/")) {
    try {
      bitmap = await createImageBitmap(file);
    } catch {
      bitmap = null;
    }
  }
  const plan = planImage(
    file.type,
    bitmap ? { width: bitmap.width, height: bitmap.height } : null,
  );
  if (!bitmap || plan.action === "keep") return file;
  const canvas = document.createElement("canvas");
  canvas.width = plan.width;
  canvas.height = plan.height;
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, plan.width, plan.height);
  const blob = await new Promise<Blob | null>((r) =>
    canvas.toBlob(r, "image/jpeg", 0.85),
  );
  if (!blob) return file;
  return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", {
    type: "image/jpeg",
  });
}

export function UploadForm({ herds }: { herds: string[] }) {
  const router = useRouter();
  const { showSnackbar } = useSnackbar();
  const inputRef = useRef<HTMLInputElement>(null);
  const [herd, setHerd] = useState(herds.length === 1 ? herds[0] : "");
  const [files, setFiles] = useState<File[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Warnings per index in `files`, set after the dry run.
  const [warnings, setWarnings] = useState<Record<number, string[]> | null>(
    null,
  );
  const [pending, start] = useTransition();

  const addFiles = (picked: FileList | null) => {
    if (!picked) return;
    setFiles((f) => [...f, ...Array.from(picked)]);
    setWarnings(null);
    setError(null);
  };
  const removeFile = (i: number) => {
    setFiles((f) => f.filter((_, j) => j !== i));
    setWarnings(null);
  };
  // "Ta om": drop the blurry photo and open the camera for a new one.
  const retake = (i: number) => {
    removeFile(i);
    inputRef.current?.click();
  };

  const build = async (): Promise<FormData | null> => {
    const prepared = await Promise.all(files.map(prepare));
    if (prepared.reduce((n, f) => n + f.size, 0) > MAX_TOTAL) {
      setError("Bilderna är för stora tillsammans. Skicka färre åt gången.");
      return null;
    }
    const fd = new FormData();
    fd.set("herd", herd);
    prepared.forEach((f) => fd.append("files", f));
    if (message.trim()) fd.set("message", message.trim());
    return fd;
  };

  const send = (skipCheck: boolean) =>
    start(async () => {
      setError(null);
      const fd = await build();
      if (!fd) return;
      if (!skipCheck) {
        const dry = await uploadIntyg(fd, true);
        if (!dry.ok) return setError(dry.error);
        const byFile: Record<number, string[]> = {};
        for (const d of dry.documents) {
          if (d.warnings.length)
            byFile[d.file] = [...(byFile[d.file] ?? []), ...d.warnings];
        }
        if (Object.keys(byFile).length) return setWarnings(byFile);
      }
      const res = await uploadIntyg(fd, false);
      if (!res.ok) return setError(res.error);
      showSnackbar("Tack, intygen är skickade", "success");
      router.push(
        res.itemId
          ? `/stamboken/inskick#arende-${res.itemId}`
          : "/stamboken/inskick",
      );
    });

  const canSend = !pending && herd !== "" && files.length > 0;

  return (
    <section className="sb-card">
      <div className={styles.cardBody}>
        {error && (
          <div role="alert" className={styles.error}>
            {error}
          </div>
        )}
        <div className={styles.field}>
          <label className="sb-label" htmlFor="inskick-herd">
            Besättning
          </label>
          <select
            id="inskick-herd"
            className="sb-input"
            value={herd}
            onChange={(e) => setHerd(e.target.value)}
          >
            {herds.length !== 1 && <option value="">Välj besättning</option>}
            {herds.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/*,application/pdf"
          multiple
          hidden
          data-testid="inskick-files"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <ul className={styles.list} aria-label="Valda filer">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              <div className={styles.row}>
                <span>{f.name}</span>
                <span className={styles.actions}>
                  {warnings?.[i] && (
                    <button
                      type="button"
                      className="sb-btn sb-btn-secondary sb-btn-sm"
                      onClick={() => retake(i)}
                    >
                      Ta om
                    </button>
                  )}
                  <button
                    type="button"
                    className="sb-btn sb-btn-ghost sb-btn-sm"
                    aria-label={`Ta bort ${f.name}`}
                    onClick={() => removeFile(i)}
                  >
                    Ta bort
                  </button>
                </span>
              </div>
              {warnings?.[i]?.map((w) => (
                <p key={w} className={styles.warn}>
                  {warningText(w)}
                </p>
              ))}
            </li>
          ))}
        </ul>
        <div className={styles.field}>
          <button
            type="button"
            className={`sb-btn sb-btn-secondary ${styles.bigBtn}`}
            onClick={() => inputRef.current?.click()}
          >
            Ta foto eller välj filer
          </button>
          <span className="sb-meta">
            Foton eller PDF. Högst 10 bilder per inskick.
          </span>
        </div>
        <div className={styles.field}>
          <label className="sb-label" htmlFor="inskick-message">
            Meddelande (valfritt)
          </label>
          <textarea
            id="inskick-message"
            className="sb-input"
            rows={3}
            maxLength={2000}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </div>
        <div className={styles.actions}>
          {warnings ? (
            <button
              type="button"
              className={`sb-btn ${styles.bigBtn}`}
              disabled={!canSend}
              onClick={() => send(true)}
            >
              Skicka ändå
            </button>
          ) : (
            <button
              type="button"
              className={`sb-btn ${styles.bigBtn}`}
              disabled={!canSend}
              onClick={() => send(false)}
            >
              {pending ? "Skickar..." : "Skicka"}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
