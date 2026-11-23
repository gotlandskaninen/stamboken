"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useOptionalUser } from "@/lib/user-context";
import { sendTyckTill, type TyckTillResult } from "./actions";
import { captureAround, describe, pickable, shrink } from "./pointing";
import styles from "./tyck-till.module.css";

const MAX_IMAGES = 4;
const MAX_FILE = 25 * 1024 * 1024; // a phone need not read in more than this
const MAX_TOTAL = 9 * 1024 * 1024; // nginx takes 10 MB, multipart overhead on top
const RETRIES = 5;
const TOO_LARGE =
  "Bilderna är för stora tillsammans. Ta bort en bild och försök igen.";
const SEND_FAILED =
  "Det gick inte att skicka just nu. Texten finns kvar, så du kan försöka igen om en stund.";
const SIGNED_OUT =
  "Du har blivit utloggad. Logga in igen och skicka, texten finns kvar.";
const HINT = {
  fel: "Vad gjorde du, och vad hände?",
  onskemal: "Vad vill du kunna göra, och varför?",
};

type Shot = {
  kind: "pek" | "fil";
  blob: Blob | null;
  url: string | null;
  cap: string;
  desc?: string;
};
type Errors = Partial<
  Record<"typ" | "text" | "email" | "file" | "send", string>
>;
type Done = Extract<TyckTillResult, { ok: true }>;

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

function Icon({ d, children }: { d?: string; children?: React.ReactNode }) {
  return (
    <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
      {d ? <path d={d} /> : children}
    </svg>
  );
}

function Sheet({
  open,
  onClose,
  onFinished,
}: {
  open: boolean;
  onClose: () => void;
  onFinished: () => void;
}) {
  const pathname = usePathname();
  const user = useOptionalUser();
  const loggedIn = user !== null;
  const dlgRef = useRef<HTMLDialogElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const layerRef = useRef<HTMLDivElement>(null);
  const doneTitleRef = useRef<HTMLHeadingElement>(null);
  // One per sheet, kept over failures: a retry cannot make a duplicate (docs/tyck-till.md).
  const [inskickId] = useState(() => crypto.randomUUID());
  const [typ, setTyp] = useState<"fel" | "onskemal" | "">("");
  const [shots, setShots] = useState<Shot[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState<Done | null>(null);
  const [pointing, setPointing] = useState(false);
  const [pickMsg, setPickMsg] = useState("");
  const [canUse, setCanUse] = useState(false);
  const [capturing, setCapturing] = useState(false);
  // Read by the dialog's close event, which fires inside the effect that closes it for pointing.
  const pointingRef = useRef(false);
  const hovered = useRef<Element | null>(null);
  const marked = useRef<Element | null>(null);

  const markEl = (el: Element | null, state: "hover" | "picked") => {
    el?.setAttribute("data-tyck-pick", state);
  };
  const unmark = (el: Element | null) => el?.removeAttribute("data-tyck-pick");

  useEffect(() => {
    const dlg = dlgRef.current;
    if (!dlg) return;
    if (open && !pointing) {
      if (!dlg.open) dlg.showModal();
    } else if (dlg.open) dlg.close();
  }, [open, pointing]);

  useEffect(
    () => () => {
      unmark(hovered.current);
      unmark(marked.current);
      document.body.removeAttribute("data-tyck-pointing");
    },
    [],
  );

  // The blob URLs of the previews are freed when the sheet goes.
  const shotsRef = useRef(shots);
  useEffect(() => {
    shotsRef.current = shots;
  });
  useEffect(
    () => () =>
      shotsRef.current.forEach((s) => s.url && URL.revokeObjectURL(s.url)),
    [],
  );

  const setShotList = (next: Shot[]) => {
    shots.forEach(
      (s) => s.url && !next.includes(s) && URL.revokeObjectURL(s.url),
    );
    setShots(next);
  };
  const clearError = (k: keyof Errors) =>
    setErrors((e) => (e[k] ? { ...e, [k]: undefined } : e));

  // ---- images ----
  const pek = shots.find((s) => s.kind === "pek");
  const full = shots.length >= MAX_IMAGES;

  const addFiles = async (files: FileList | null) => {
    setErrors((e) => ({ ...e, file: undefined }));
    let list = shots;
    let error: string | undefined;
    // One at a time: decoded phone photos are large.
    for (const f of Array.from(files ?? [])) {
      if (list.length >= MAX_IMAGES) break;
      if (!f.type.startsWith("image/")) {
        error = `”${f.name}” är ingen bild. Välj en bildfil.`;
        continue;
      }
      if (f.size > MAX_FILE) {
        error = `”${f.name}”: Bilden är för stor.`;
        continue;
      }
      const blob = await shrink(f);
      list = [
        ...list,
        { kind: "fil", blob, url: URL.createObjectURL(blob), cap: f.name },
      ];
      setShots(list);
    }
    if (error) setErrors((e) => ({ ...e, file: error }));
    if (fileRef.current) fileRef.current.value = "";
  };

  // ---- pointing ----
  const pickAt = (x: number, y: number): Element | null => {
    const layer = layerRef.current;
    if (!layer) return null;
    layer.style.pointerEvents = "none";
    const hit = document.elementFromPoint(x, y);
    layer.style.pointerEvents = "";
    if (!hit || hit === document.body || hit === document.documentElement)
      return null;
    if (hit.closest("[data-tyck-ui]")) return null;
    return pickable(hit);
  };

  const startPointing = () => {
    pointingRef.current = true;
    marked.current = null;
    document.body.setAttribute("data-tyck-pointing", "");
    setPickMsg("Tryck på det som är fel på sidan.");
    setCanUse(false);
    setPointing(true);
  };
  const stopPointing = () => {
    pointingRef.current = false;
    document.body.removeAttribute("data-tyck-pointing");
    unmark(hovered.current);
    unmark(marked.current);
    hovered.current = marked.current = null;
    setPointing(false);
  };
  // The sheet reopens on the next tick: a modal opened inside this keydown
  // would take the same Escape and close at once.
  useEffect(() => {
    if (!pointing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      setTimeout(stopPointing);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stopPointing only touches refs and setters
  }, [pointing]);

  const onLayerMove = (e: React.MouseEvent) => {
    const el = pickAt(e.clientX, e.clientY);
    if (el === hovered.current) return;
    unmark(hovered.current);
    hovered.current = el && el !== marked.current ? el : null;
    markEl(hovered.current, "hover");
  };
  const onLayerClick = (e: React.MouseEvent) => {
    const el = pickAt(e.clientX, e.clientY);
    if (!el) return;
    unmark(marked.current);
    unmark(hovered.current);
    hovered.current = null;
    marked.current = el;
    markEl(el, "picked");
    setCanUse(true);
    setPickMsg(
      `Du har valt ${describe(el)}. Tryck på något annat för att byta.`,
    );
  };
  const usePicked = async () => {
    const el = marked.current;
    if (!el) return;
    const desc = describe(el);
    setCapturing(true);
    unmark(hovered.current);
    hovered.current = null;
    setPickMsg("Tar bild av sidan …");
    const blob = await captureAround(el, document.body);
    const shot: Shot = blob
      ? {
          kind: "pek",
          blob,
          url: URL.createObjectURL(blob),
          desc,
          cap: `Bild av sidan. Du pekade på ${desc}.`,
        }
      : {
          kind: "pek",
          blob: null,
          url: null,
          desc,
          cap: `Det gick inte att ta en bild i den här webbläsaren. Vi skickar vad du pekade på: ${desc}. Ta gärna en skärmdump själv och välj Bifoga bild.`,
        };
    setShotList([shot, ...shots.filter((s) => s.kind !== "pek")]);
    setCapturing(false);
    stopPointing();
  };

  // ---- send ----
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    const text = String(fd.get("text") ?? "").trim();
    const email = String(fd.get("email") ?? "").trim();
    const next: Errors = {};
    if (!typ)
      next.typ = "Välj om något inte fungerar eller om du önskar något.";
    if (!text) next.text = "Skriv några ord om vad det gäller.";
    const emailField = form.elements.namedItem(
      "email",
    ) as HTMLInputElement | null;
    if (!loggedIn && !(email && emailField?.checkValidity()))
      next.email = "Skriv en e-postadress, till exempel namn@exempel.se.";
    if (shots.reduce((n, s) => n + (s.blob?.size ?? 0), 0) > MAX_TOTAL)
      next.file = TOO_LARGE;
    setErrors(next);
    const first = (["typ", "text", "email", "file"] as const).find(
      (k) => next[k],
    );
    if (first) {
      const target = {
        typ: "typ-fel",
        text: "tt-text",
        email: "tt-email",
        file: "tt-attach",
      }[first];
      document.getElementById(target)?.focus();
      return;
    }

    fd.set("inskick_id", inskickId);
    fd.set("sida", pathname);
    fd.set("version", process.env.NEXT_PUBLIC_APP_VERSION ?? "");
    fd.set(
      "enhet",
      window.matchMedia("(max-width: 719px)").matches ? "mobil" : "dator",
    );
    if (pek?.desc) fd.set("pekat", pek.desc);
    shots.forEach(
      (s, i) => s.blob && fd.append("bilder", s.blob, `bild-${i + 1}.jpg`),
    );

    setSending(true);
    let res: TyckTillResult;
    try {
      res = await sendTyckTill(fd);
      // 409: the first call is still working. Same inskick_id, so it cannot double.
      for (let n = 0; !res.ok && res.status === 409 && n < RETRIES; n++) {
        await wait(2000);
        res = await sendTyckTill(fd);
      }
    } catch {
      res = { ok: false, status: 0, error: "" };
    }
    setSending(false);
    if (res.ok) {
      setDone(res);
      return;
    }
    const detail = res.error;
    if (res.status === 400 && res.field === "email" && loggedIn)
      return setErrors({ send: SIGNED_OUT });
    if (
      res.status === 400 &&
      (res.field === "typ" || res.field === "text" || res.field === "email")
    )
      return setErrors({ [res.field]: detail });
    if (res.status === 400 && res.field === "bilder")
      return setErrors({ file: detail });
    if (res.status === 413) return setErrors({ file: TOO_LARGE });
    if ([400, 415, 429].includes(res.status) && detail)
      return setErrors({ send: detail });
    setErrors({ send: SEND_FAILED });
  };

  useEffect(() => {
    if (done) doneTitleRef.current?.focus();
  }, [done]);

  const closeButton = (
    <button
      type="button"
      className={styles.iconBtn}
      aria-label="Stäng"
      onClick={() => dlgRef.current?.close()}
    >
      <Icon d="M6 6l12 12M18 6L6 18" />
    </button>
  );

  return (
    <>
      {pointing && (
        <>
          <div
            ref={layerRef}
            className={styles.layer}
            data-tyck-ui=""
            data-tyck-till="dolj"
            onMouseMove={onLayerMove}
            onClick={onLayerClick}
          />
          <div className={styles.pickbar} data-tyck-ui="" data-tyck-till="dolj">
            <p role="status" aria-live="polite">
              {pickMsg}
            </p>
            <div className={styles.pickActions}>
              {canUse && (
                <button
                  type="button"
                  className="sb-btn sb-btn-accent"
                  disabled={capturing}
                  onClick={usePicked}
                >
                  Använd
                </button>
              )}
              <button
                type="button"
                className="sb-btn sb-btn-ghost"
                autoFocus
                disabled={capturing}
                onClick={stopPointing}
              >
                Avbryt
              </button>
            </div>
          </div>
        </>
      )}
      <dialog
        ref={dlgRef}
        className={styles.sheet}
        aria-labelledby={done ? "tt-done-title" : "tt-title"}
        onClose={() => {
          if (pointingRef.current) return;
          onClose();
          if (done) onFinished();
        }}
      >
        {done ? (
          <div className={styles.done}>
            <div className={styles.head}>
              <h2 id="tt-done-title" ref={doneTitleRef} tabIndex={-1}>
                Tack! Vi har fått din synpunkt.
              </h2>
              {closeButton}
            </div>
            <div className={styles.body}>
              <span className={styles.doneMark} aria-hidden="true">
                <Icon d="M5 12.5l4.5 4.5L19 7.5" />
              </span>
              {done.issueUrl ? (
                <p>
                  Den finns nu öppet på GitHub.{" "}
                  <a href={done.issueUrl} target="_blank" rel="noopener">
                    Se ärendet
                  </a>
                </p>
              ) : (
                <p>Bara föreningen kan läsa den.</p>
              )}
              {done.images > 0 && (
                <p>Bilderna skickas till föreningen med mejl.</p>
              )}
              {done.replyTo && <p>Vi svarar till {done.replyTo}.</p>}
            </div>
            <div className={styles.foot}>
              <button
                type="button"
                className={`sb-btn ${styles.send}`}
                onClick={() => dlgRef.current?.close()}
              >
                Stäng
              </button>
            </div>
          </div>
        ) : (
          <form
            ref={formRef}
            className={styles.form}
            noValidate
            onSubmit={submit}
          >
            <div className={styles.head}>
              <h2 id="tt-title">Tyck till om Stamboken</h2>
              {closeButton}
            </div>
            <div className={styles.body}>
              <p className={styles.lead}>
                Berätta vad som krånglar eller vad du saknar. Vi läser allt.
              </p>

              <fieldset
                className={`${styles.field} ${errors.typ ? styles.invalid : ""}`}
                aria-describedby="tt-err-typ"
              >
                <legend>Vad gäller det?</legend>
                <div className={styles.choice2}>
                  <label className={styles.choice}>
                    <input
                      type="radio"
                      name="typ"
                      value="fel"
                      id="typ-fel"
                      checked={typ === "fel"}
                      onChange={() => {
                        setTyp("fel");
                        clearError("typ");
                      }}
                    />
                    <span>Något fungerar inte</span>
                  </label>
                  <label className={styles.choice}>
                    <input
                      type="radio"
                      name="typ"
                      value="onskemal"
                      checked={typ === "onskemal"}
                      onChange={() => {
                        setTyp("onskemal");
                        clearError("typ");
                      }}
                    />
                    <span>Jag önskar något</span>
                  </label>
                </div>
                {errors.typ && (
                  <p className={styles.err} id="tt-err-typ">
                    {errors.typ}
                  </p>
                )}
              </fieldset>

              <div className={styles.field}>
                <label htmlFor="tt-text">Beskriv med egna ord</label>
                <p className={styles.hint} id="tt-text-hint">
                  {HINT[typ || "fel"]}
                </p>
                <textarea
                  className={styles.input}
                  id="tt-text"
                  name="text"
                  rows={5}
                  maxLength={5000}
                  aria-describedby="tt-text-hint tt-err-text"
                  aria-invalid={errors.text ? true : undefined}
                  onInput={(e) =>
                    e.currentTarget.value.trim() && clearError("text")
                  }
                />
                {errors.text && (
                  <p className={styles.err} id="tt-err-text">
                    {errors.text}
                  </p>
                )}
              </div>

              <div className={styles.field}>
                <span className={styles.label} id="tt-bild-label">
                  Bild, om du vill
                </span>
                <div
                  className={styles.imgBtns}
                  role="group"
                  aria-labelledby="tt-bild-label"
                >
                  <button
                    type="button"
                    className="sb-btn sb-btn-secondary"
                    disabled={full && !pek}
                    onClick={startPointing}
                  >
                    <Icon>
                      <circle cx="12" cy="12" r="7" />
                      <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
                    </Icon>
                    <span>{pek ? "Peka om" : "Peka på sidan"}</span>
                  </button>
                  <button
                    type="button"
                    id="tt-attach"
                    className="sb-btn sb-btn-secondary"
                    disabled={full}
                    onClick={() => fileRef.current?.click()}
                  >
                    <Icon>
                      <rect x="3" y="5" width="18" height="14" rx="2" />
                      <circle cx="9" cy="10" r="1.75" />
                      <path d="M21 16l-5-5-8 8" />
                    </Icon>
                    <span>Bifoga bild</span>
                  </button>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/*"
                    multiple
                    hidden
                    onChange={(e) => addFiles(e.currentTarget.files)}
                  />
                </div>
                <div className={styles.shots}>
                  {shots.map((s, i) => (
                    <div
                      key={s.url ?? `${s.kind}-${i}`}
                      className={`${styles.shot} ${s.kind === "fil" || !s.url ? styles.shotSmall : ""}`}
                    >
                      {s.url && (
                        // eslint-disable-next-line @next/next/no-img-element -- a blob: preview
                        <img
                          src={s.url}
                          alt={
                            s.kind === "pek"
                              ? "Bild av sidan med det du pekade på inringat"
                              : "Bifogad bild"
                          }
                        />
                      )}
                      <p className={styles.shotCap}>{s.cap}</p>
                      <div className={styles.shotActions}>
                        {s.kind === "pek" && (
                          <button
                            type="button"
                            className="sb-btn sb-btn-ghost"
                            onClick={startPointing}
                          >
                            Peka om
                          </button>
                        )}
                        <button
                          type="button"
                          className={styles.iconBtn}
                          aria-label="Ta bort bilden"
                          onClick={() =>
                            setShotList(shots.filter((x) => x !== s))
                          }
                        >
                          <Icon d="M6 6l12 12M18 6L6 18" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                {errors.file && (
                  <p className={styles.err} role="alert">
                    {errors.file}
                  </p>
                )}
                <p className={styles.hint}>
                  {full
                    ? "Högst fyra bilder. Ta bort en om du vill lägga till en annan."
                    : "Bilder mejlas bara till föreningen. De läggs aldrig ut öppet."}
                </p>
              </div>

              {loggedIn ? (
                <>
                  <fieldset className={styles.field}>
                    <legend>Vem får läsa det du skriver?</legend>
                    <label className={styles.radio}>
                      <input
                        type="radio"
                        name="vem"
                        value="privat"
                        defaultChecked
                      />
                      <span>
                        <strong>Bara föreningen</strong>
                        <small>De som utvecklar Stamboken läser den.</small>
                      </span>
                    </label>
                    <label className={styles.radio}>
                      <input type="radio" name="vem" value="publik" />
                      <span>
                        <strong>Alla</strong>
                        <small>
                          Den läggs ut öppet på GitHub, utan ditt namn. Skriv
                          inte andras namn eller kaninnummer.
                        </small>
                      </span>
                    </label>
                  </fieldset>
                  <div className={styles.field}>
                    <label className={styles.check}>
                      <input type="checkbox" name="kontakt" value="1" />
                      <span>
                        Skicka med mina kontaktuppgifter, jag vill ha svar
                        <small>
                          Vi svarar till {user?.email}, adressen på ditt konto.
                        </small>
                      </span>
                    </label>
                  </div>
                </>
              ) : (
                <div className={styles.field}>
                  <label htmlFor="tt-email">Din e-postadress</label>
                  <p className={styles.hint} id="tt-email-hint">
                    Vi använder den bara för att svara dig.
                  </p>
                  <input
                    className={styles.input}
                    type="email"
                    id="tt-email"
                    name="email"
                    autoComplete="email"
                    inputMode="email"
                    aria-describedby="tt-email-hint tt-err-email"
                    aria-invalid={errors.email ? true : undefined}
                    onInput={(e) =>
                      e.currentTarget.checkValidity() && clearError("email")
                    }
                  />
                  {errors.email && (
                    <p className={styles.err} id="tt-err-email">
                      {errors.email}
                    </p>
                  )}
                </div>
              )}

              <div className={styles.trap} aria-hidden="true">
                <label>
                  Lämna tomt
                  <input
                    type="text"
                    name="webbplats"
                    tabIndex={-1}
                    autoComplete="off"
                  />
                </label>
              </div>

              {errors.send && (
                <p className={`${styles.err} ${styles.errSend}`} role="alert">
                  {errors.send}
                </p>
              )}
            </div>
            <div className={styles.foot}>
              <button
                type="button"
                className="sb-btn sb-btn-ghost"
                onClick={() => dlgRef.current?.close()}
              >
                Avbryt
              </button>
              <button
                type="submit"
                className={`sb-btn ${styles.send}`}
                disabled={sending}
              >
                {sending ? "Skickar …" : "Skicka"}
              </button>
            </div>
          </form>
        )}
      </dialog>
    </>
  );
}

export function TyckTillDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  // Nothing is built until the first opening; a new sheet (new inskick_id) after a receipt.
  const [seen, setSeen] = useState(open);
  const [generation, setGeneration] = useState(0);
  if (open && !seen) setSeen(true);
  if (!seen) return null;
  return (
    <Sheet
      key={generation}
      open={open}
      onClose={onClose}
      onFinished={() => setGeneration((g) => g + 1)}
    />
  );
}

/** A link-style button that owns its sheet. */
export function TyckTillLink({
  className,
  children = "Tyck till",
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={className ?? styles.link}
        onClick={() => setOpen(true)}
      >
        {children}
      </button>
      <TyckTillDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
