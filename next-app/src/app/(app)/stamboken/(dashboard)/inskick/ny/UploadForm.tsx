"use client";

import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Autocomplete, TextField } from "@mui/material";
import type { GenebankHerd } from "@/utils/saleRules";
import { useSnackbar } from "@/components/SnackbarProvider";
import { warningText } from "@/lib/inkorg";
import { uploadIntyg } from "./actions";
import { prepare } from "./prepare";
import styles from "../inskick.module.css";

// nginx cuts the request at 10 MiB, multipart overhead included (docs/inkorg.md),
// so the files get a little less.
const MAX_TOTAL = 9 * 1024 * 1024;

/**
 * `herds` are the user's own. Someone who works in the queue may upload for
 * any herd, so they get `herdOptions` to search instead (as SalePanel's buyer).
 */
export function UploadForm({
  herds,
  herdOptions,
}: {
  herds: string[];
  herdOptions?: GenebankHerd[];
}) {
  const router = useRouter();
  const { showSnackbar } = useSnackbar();
  const inputRef = useRef<HTMLInputElement>(null);
  const [herd, setHerd] = useState(herds.length === 1 ? herds[0] : "");
  const [files, setFiles] = useState<File[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Warnings per index in `files`, from the API's 409.
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
    // One at a time: decoded phone photos are large.
    const prepared: File[] = [];
    for (const f of files) prepared.push(await prepare(f));
    if (prepared.reduce((n, f) => n + f.size, 0) > MAX_TOTAL) {
      setError(
        "Bilderna är för stora tillsammans (högst 9 MB). Skicka färre åt gången.",
      );
      return null;
    }
    const fd = new FormData();
    // The picker's label is "G1274 – Name": the code is its first word.
    fd.set("herd", herd.trim().split(/\s/)[0].toUpperCase());
    prepared.forEach((f) => fd.append("files", f));
    if (message.trim()) fd.set("message", message.trim());
    return fd;
  };

  const send = (acceptWarnings: boolean) =>
    start(async () => {
      setError(null);
      const fd = await build();
      if (!fd) return;
      if (acceptWarnings) fd.set("accept_warnings", "1");
      let res: Awaited<ReturnType<typeof uploadIntyg>>;
      try {
        res = await uploadIntyg(fd);
      } catch {
        // The connection dropped: the call itself rejects. The files stay chosen.
        return setError("Uppladdningen avbröts. Försök igen.");
      }
      if (!res.ok) {
        if (!res.warnings?.length) return setError(res.error);
        // Nothing was stored: show what the API saw, per file.
        const byFile: Record<number, string[]> = {};
        for (const d of res.warnings)
          byFile[d.file] = [...(byFile[d.file] ?? []), ...d.warnings];
        return setWarnings(byFile);
      }
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
          {herdOptions ? (
            <Autocomplete
              freeSolo
              options={herdOptions.map((h) => h.herd)}
              getOptionLabel={(h) => {
                const name = herdOptions.find((o) => o.herd === h)?.herd_name;
                return name ? `${h} – ${name}` : h;
              }}
              inputValue={herd}
              onInputChange={(_, v) => setHerd(v)}
              renderInput={(params) => (
                <TextField {...params} label="Besättning" size="small" />
              )}
            />
          ) : (
            <>
              <label className="sb-label" htmlFor="inskick-herd">
                Besättning
              </label>
              <select
                id="inskick-herd"
                className="sb-input"
                value={herd}
                onChange={(e) => setHerd(e.target.value)}
              >
                {herds.length !== 1 && (
                  <option value="">Välj besättning</option>
                )}
                {herds.map((h) => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ))}
              </select>
            </>
          )}
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
            Foton eller PDF. Högst 10 bilder och 9 MB per inskick.
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
