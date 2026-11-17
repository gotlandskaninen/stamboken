"use client";

import React from "react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  LinearProgress,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { Mode } from "@/lib/mode";
import {
  RegisterFromCertificate,
  type Lookup,
  type Parent,
  type SaveResult,
  type Where,
} from "@/components/register/RegisterFromCertificate";
import { initialCertForm, type CertForm } from "../inkorg/lib";
import { prepare } from "../inskick/ny/prepare";
import {
  findRabbit,
  getFormSetup,
  registerRabbit,
  suggestNumber,
  uploadPhoto,
  type Registered,
} from "./rabbitActions";
import styles from "./arsrapport.module.css";

export const ADD_FROM_CERTIFICATE =
  "Finns kaninen inte i listan, lägg till den från intyget.";
export const RABBIT_SAVED =
  "Kaninen är registrerad i Stamboken nu. Den finns kvar även om du drar tillbaka rapporten.";
const MAX_BYTES = 10 * 1024 * 1024; // the server's limit, checked before the photo is sent
const INTRO: Record<Parent, string> = {
  mother: "Modern till ungen. När hon är sparad visas ungens uppgifter igen.",
  father: "Fadern till ungen. När han är sparad visas ungens uppgifter igen.",
};

type Photo = {
  status: "tom" | "skickar" | "klar" | "fel";
  item_id?: number;
  error?: string;
};
// One rabbit's form, by its own id. The kit is first; a parent added from its form (`of`: the kit's id) lies above
// it until saved or cancelled.
type Draft = {
  id: number;
  form: CertForm;
  where: Where | null;
  photo: Photo;
  parent?: Parent;
  of?: number;
  file?: File; // the downscaled photo, for "Försök igen"; in memory only
};
// "Spara som utkast": what is kept in the browser. Never a photo or anything that names one.
type Stored = {
  saved_at: number;
  drafts: Pick<Draft, "id" | "form" | "where" | "parent" | "of">[];
};

const blank = (
  id: number,
  parent?: Parent,
  number = "",
  of?: number,
): Draft => ({
  id,
  form: {
    ...initialCertForm(null),
    paper_number: number,
    sex: parent === "mother" ? "female" : parent === "father" ? "male" : "",
  },
  where: null,
  photo: { status: "tom" },
  ...(parent ? { parent, of } : {}),
});

export const DRAFT_DAYS = 7;
// The demo is a copy of production with the same accounts and codes, in the same browser: the environment is in it
export const draftKey = (
  env: Mode,
  actor: string,
  herd: string,
  year: number,
) => `arsrapport:kanin:${env}:${actor}:${herd}:${year}`;

// A draft saved more than DRAFT_DAYS ago is gone, as is one that cannot be read.
function readDrafts(key: string, now = Date.now()): Draft[] | null {
  try {
    const stored: Stored | null = JSON.parse(
      localStorage.getItem(key) ?? "null",
    );
    if (!stored || !Array.isArray(stored.drafts) || !stored.drafts.length)
      return null;
    if (now - stored.saved_at > DRAFT_DAYS * 24 * 3600 * 1000) {
      localStorage.removeItem(key);
      return null;
    }
    return stored.drafts.map((d) => ({ ...d, photo: { status: "tom" } }));
  } catch {
    return null;
  }
}
function writeDrafts(key: string, drafts: Draft[] | null) {
  try {
    if (drafts === null) return localStorage.removeItem(key);
    const stored: Stored = {
      saved_at: Date.now(),
      drafts: drafts.map(({ id, form, where, parent, of }) => ({
        id,
        form,
        where,
        ...(parent ? { parent, of } : {}),
      })),
    };
    localStorage.setItem(key, JSON.stringify(stored));
  } catch {
    // a full or blocked storage: the form still works, only the copy is lost
  }
}

/**
 * "Lägg till kanin från intyget" (spec 5.8): the certificate's photo first,
 * sent while the form is filled in, then the shared registration form. A
 * missing mother or father is added from her or his own certificate, and the
 * kit's form comes back afterwards. Back closes the dialog (it is one entry in
 * the browser's history) and first asks "Spara som utkast eller släng?" once
 * something is typed. Only that choice keeps anything in the browser, for this
 * actor in this environment and for DRAFT_DAYS, and never the photo.
 */
export function AddRabbitDialog({
  herd,
  year,
  env,
  onClose,
}: {
  herd: string;
  year: number;
  env?: Mode; // undefined: the personal link
  /** On closing: the rabbits registered meanwhile, each with "var är kaninen nu". */
  onClose: (registered: [Registered, Where | null][]) => void;
}) {
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("sm"));
  const ids = React.useRef(1); // draft ids and upload attempts, never reused while the dialog is open
  const nextId = () => ++ids.current;
  const [stack, setStack] = React.useState<Draft[]>(() => [blank(1)]);
  const [touched, setTouched] = React.useState(false);
  const [restored, setRestored] = React.useState(false);
  const [ask, setAsk] = React.useState(false);
  // A registration in progress: set outside React's transition, so a close or a cancel sees it at once
  const committing = React.useRef(false);
  const [colors, setColors] = React.useState<string[]>([]);
  const [key, setKey] = React.useState<string | null>(null); // known once the server has said who the actor is
  const top = stack[stack.length - 1];

  // The colours, and a draft this actor saved, put back if nothing is typed yet.
  const touchedRef = React.useRef(touched);
  React.useEffect(() => {
    touchedRef.current = touched;
  });
  React.useEffect(() => {
    let cancelled = false;
    getFormSetup(herd, year, env)
      .then((r) => {
        if (cancelled || !r.ok) return;
        setColors(r.data.farger);
        const actorKey = draftKey(env ?? "prod", r.data.aktor, herd, year); // the link is production's
        setKey(actorKey);
        const drafts = readDrafts(actorKey);
        if (drafts && !touchedRef.current) {
          ids.current = Math.max(ids.current, ...drafts.map((d) => d.id));
          setStack(drafts);
          setTouched(true);
          setRestored(true);
        }
      })
      .catch(() => undefined); // free text then, and no draft
    return () => {
      cancelled = true;
    };
  }, [herd, year, env]);

  // Back closes the dialog: one history entry while it is open.
  const pushed = React.useRef(false);
  const registered = React.useRef<[Registered, Where | null][]>([]);
  const done = () => onClose(registered.current);
  const doneRef = React.useRef(done);
  React.useEffect(() => {
    doneRef.current = done;
  });
  React.useEffect(() => {
    // once: StrictMode mounts twice in development
    if (!window.history.state?.kanin)
      window.history.pushState({ kanin: true }, "");
    pushed.current = true;
    const onPop = () => {
      if (committing.current) {
        // Back waits for the registration, as Stäng does: the browser took the entry, so it is put back
        window.history.pushState({ kanin: true }, "");
        return;
      }
      pushed.current = false;
      if (touchedRef.current) setAsk(true);
      else doneRef.current();
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const leave = () => {
    if (pushed.current) {
      pushed.current = false;
      window.history.back();
    }
    done();
  };
  // Not while a registration commits: its answer decides what the dialog shows next.
  const requestClose = () => {
    if (committing.current) return;
    if (touched) setAsk(true);
    else leave();
  };

  const updateDraft = (id: number, change: (d: Draft) => Draft) =>
    setStack((s) => s.map((d) => (d.id === id ? change(d) : d)));
  const touch = () => setTouched(true);

  // Only the photo is sent again: what was typed stays (Review Focus 4). A draft's latest attempt starts when its
  // photo is chosen, before it is prepared: an earlier photo still being prepared is not sent, and an earlier
  // upload's answer is dropped. A cancelled form has no draft to answer.
  const latest = React.useRef(new Map<number, number>());
  const begin = (draftId: number) => {
    const attempt = nextId();
    latest.current.set(draftId, attempt);
    updateDraft(draftId, (d) => ({
      ...d,
      photo: { status: "skickar" },
    }));
    return attempt;
  };
  const send = async (draftId: number, file: File, attempt: number) => {
    updateDraft(draftId, (d) => ({ ...d, file }));
    let photo: Photo;
    if (file.size > MAX_BYTES) {
      photo = { status: "fel", error: "Filen är för stor. Max 10 MB." };
    } else {
      const data = new FormData();
      data.set("file", file);
      try {
        const res = await uploadPhoto(herd, year, data, env);
        photo = res.ok
          ? { status: "klar", item_id: res.data.item_id }
          : { status: "fel", error: res.problem.detail };
      } catch {
        photo = { status: "fel", error: "Uppladdningen avbröts. Försök igen." };
      }
    }
    if (latest.current.get(draftId) === attempt)
      updateDraft(draftId, (d) => ({ ...d, photo }));
  };
  const pick = async (file: File | undefined) => {
    if (!file) return;
    touch();
    const draftId = top.id;
    const attempt = begin(draftId);
    const prepared = await prepare(file);
    if (latest.current.get(draftId) === attempt)
      send(draftId, prepared, attempt);
  };

  const lookup: Lookup = React.useCallback(
    (number) => findRabbit(herd, year, number, env),
    [herd, year, env],
  );
  const suggest = React.useCallback(
    (litterId: number) => suggestNumber(herd, year, litterId, env),
    [herd, year, env],
  );

  const save = async (
    payload: Record<string, unknown>,
  ): Promise<SaveResult> => {
    const draft = top;
    committing.current = true;
    let res;
    try {
      res = await registerRabbit(
        herd,
        year,
        { ...payload, item_id: draft.photo.item_id ?? null },
        env,
      );
    } catch {
      return {
        ok: false,
        problem: {
          status: 502,
          title: "Bad Gateway",
          detail: "Det gick inte att nå servern. Försök igen.",
        },
      };
    } finally {
      committing.current = false;
    }
    if (!res.ok) return res;
    registered.current.push([res.data, draft.where]);
    if (draft.parent) {
      // the parent is in: back to the kit's form, with the parent's number as Stamboken gave it
      const parent = draft.parent;
      setStack((s) =>
        s
          .filter((d) => d.id !== draft.id)
          .map((d) =>
            d.id === draft.of
              ? { ...d, form: { ...d.form, [parent]: res.data.number } }
              : d,
          ),
      );
      return { ok: true };
    }
    if (key) writeDrafts(key, null);
    setTouched(false);
    touchedRef.current = false;
    leave();
    return { ok: true };
  };

  const photo = (
    <div className={styles.detail}>
      <label className={styles.label}>
        Foto av intyget
        <input
          type="file"
          accept="image/*,.heic,.pdf"
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </label>
      <p className={styles.meta}>Fotot laddas upp medan du fyller i resten.</p>
      {restored && top.photo.status === "tom" && (
        <p className={styles.meta} role="status">
          Utkastet är tillbaka. Ladda upp fotot av intyget igen.
        </p>
      )}
      {top.photo.status === "skickar" && (
        <LinearProgress aria-label="Fotot laddas upp" />
      )}
      {top.photo.status === "klar" && (
        <p className={styles.meta} role="status">
          Fotot är uppladdat.
        </p>
      )}
      {top.photo.status === "fel" && (
        <p className={styles.errorText} role="alert">
          {top.photo.error}{" "}
          {top.file && (
            <button
              type="button"
              className="sb-btn sb-btn-secondary sb-btn-sm"
              onClick={() => send(top.id, top.file!, begin(top.id))}
            >
              Försök igen
            </button>
          )}
        </p>
      )}
    </div>
  );

  return (
    <Dialog
      open
      onClose={requestClose}
      fullScreen={mobile}
      fullWidth
      maxWidth="md"
      aria-labelledby="kanin-title"
    >
      <DialogTitle id="kanin-title" sx={{ pr: 6 }}>
        Lägg till kanin från intyget
        <IconButton
          aria-label="Stäng"
          onClick={requestClose}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers={mobile}>
        {ask ? (
          <div role="alertdialog" aria-label="Spara som utkast eller släng?">
            <p>Spara som utkast eller släng?</p>
            <div className={styles.detail}>
              <button
                type="button"
                className={`sb-btn ${styles.btn}`}
                onClick={() => {
                  if (committing.current) return;
                  if (key) writeDrafts(key, stack);
                  leave();
                }}
              >
                Spara som utkast
              </button>{" "}
              <button
                type="button"
                className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                onClick={() => {
                  if (committing.current) return;
                  if (key) writeDrafts(key, null);
                  leave();
                }}
              >
                Släng
              </button>
            </div>
          </div>
        ) : (
          <>
            {top.parent && <p className={styles.meta}>{INTRO[top.parent]}</p>}
            <RegisterFromCertificate
              key={top.id}
              mode="ny_kanin"
              form={top.form}
              onChange={(field, value) => {
                touch();
                updateDraft(top.id, (d) => ({
                  ...d,
                  form: { ...d.form, [field]: value },
                }));
              }}
              colors={colors}
              lookup={lookup}
              suggest={suggest}
              onSave={save}
              canSave={top.photo.status === "klar"}
              submitLabel="Spara"
              conflictHint="Stämmer pappret? Kontakta genbanksansvarig."
              photo={photo}
              where={top.where}
              onWhere={(where) => {
                touch();
                updateDraft(top.id, (d) => ({ ...d, where }));
              }}
              onAddParent={(parent, number) => {
                touch();
                setStack((s) => [
                  ...s,
                  blank(nextId(), parent, number, top.id),
                ]);
              }}
              buttons={(saving) => (
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary"
                  disabled={saving}
                  onClick={() => {
                    if (committing.current) return;
                    if (top.parent)
                      setStack((s) => s.filter((d) => d.id !== top.id));
                    else requestClose();
                  }}
                >
                  Avbryt
                </button>
              )}
            />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Under "Sålda under Y" and in an empty list: the way to a rabbit that is not in Stamboken. */
export function AddRabbitPrompt({
  saved,
  onOpen,
}: {
  saved: boolean;
  onOpen: () => void;
}) {
  return (
    <div className={styles.detail}>
      <p>{ADD_FROM_CERTIFICATE}</p>
      <button
        type="button"
        className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
        onClick={onOpen}
      >
        Lägg till kanin från intyget
      </button>
      {saved && <p role="status">{RABBIT_SAVED}</p>}
    </div>
  );
}
