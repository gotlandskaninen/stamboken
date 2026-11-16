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
  getColors,
  registerRabbit,
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
// One rabbit's form. The kit is first; a parent added from its form lies above it until saved.
type Draft = {
  form: CertForm;
  where: Where | null;
  photo: Photo;
  parent?: Parent;
  file?: File; // the downscaled photo, for "Försök igen"; never stored
};

const draftKey = (env: Mode | undefined, herd: string, year: number) =>
  `arsrapport:kanin:${env ?? "link"}:${herd}:${year}`;
const fresh = (parent?: Parent, number = ""): Draft => ({
  form: {
    ...initialCertForm(null),
    paper_number: number,
    sex: parent === "mother" ? "female" : parent === "father" ? "male" : "",
  },
  where: null,
  photo: { status: "tom" },
  ...(parent ? { parent } : {}),
});

// The browser copy of an unsaved form ("Spara som utkast"). A photo still on its way is not kept: it is chosen again.
function readDrafts(key: string): Draft[] | null {
  try {
    const stored = JSON.parse(localStorage.getItem(key) ?? "null");
    if (!Array.isArray(stored) || stored.length === 0) return null;
    return stored.map((d: Draft) =>
      d.photo.status === "klar" ? d : { ...d, photo: { status: "tom" } },
    );
  } catch {
    return null;
  }
}
function writeDrafts(key: string, drafts: Draft[] | null) {
  try {
    if (drafts === null) localStorage.removeItem(key);
    else
      localStorage.setItem(
        key,
        JSON.stringify(drafts.map(({ file: _file, ...d }) => d)),
      );
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
 * something is typed.
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
  const key = draftKey(env, herd, year);
  const [stack, setStack] = React.useState<Draft[]>(
    () => readDrafts(key) ?? [fresh()],
  );
  const [touched, setTouched] = React.useState(() => readDrafts(key) !== null);
  const [ask, setAsk] = React.useState(false);
  const [colors, setColors] = React.useState<string[]>([]);
  const top = stack[stack.length - 1];
  const level = stack.length - 1;

  React.useEffect(() => {
    if (touched) writeDrafts(key, stack);
  }, [key, stack, touched]);
  React.useEffect(() => {
    let cancelled = false;
    getColors(herd, year, env)
      .then((r) => {
        if (!cancelled && r.ok) setColors(r.data.farger);
      })
      .catch(() => undefined); // free text then; the registration refuses no colour
    return () => {
      cancelled = true;
    };
  }, [herd, year, env]);

  // Back closes the dialog: one history entry while it is open.
  const pushed = React.useRef(false);
  const touchedRef = React.useRef(touched);
  React.useEffect(() => {
    touchedRef.current = touched;
  });
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
  const requestClose = () => (touched ? setAsk(true) : leave());

  const updateAt = (index: number, change: (d: Draft) => Draft) =>
    setStack((s) => s.map((d, i) => (i === index ? change(d) : d)));
  const touch = () => setTouched(true);

  // Only the photo is sent again: what was typed stays (Review Focus 4).
  const send = async (index: number, file: File) => {
    updateAt(index, (d) => ({ ...d, file, photo: { status: "skickar" } }));
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
    updateAt(index, (d) => ({ ...d, photo }));
  };
  const pick = async (file: File | undefined) => {
    if (!file) return;
    touch();
    const index = level;
    updateAt(index, (d) => ({ ...d, photo: { status: "skickar" } }));
    send(index, await prepare(file));
  };

  const lookup: Lookup = React.useCallback(
    (number) => findRabbit(herd, year, number, env),
    [herd, year, env],
  );

  const save = async (
    payload: Record<string, unknown>,
  ): Promise<SaveResult> => {
    let res;
    try {
      res = await registerRabbit(
        herd,
        year,
        { ...payload, item_id: top.photo.item_id ?? null },
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
    }
    if (!res.ok) return res;
    registered.current.push([res.data, top.where]);
    if (top.parent) {
      // the parent is in: back to the kit's form, with the parent's number as Stamboken gave it
      const parent = top.parent;
      setStack((s) =>
        s
          .slice(0, -1)
          .map((d, i, rest) =>
            i === rest.length - 1
              ? { ...d, form: { ...d.form, [parent]: res.data.number } }
              : d,
          ),
      );
      return { ok: true };
    }
    writeDrafts(key, null);
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
              onClick={() => send(level, top.file!)}
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
                onClick={leave}
              >
                Spara som utkast
              </button>{" "}
              <button
                type="button"
                className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                onClick={() => {
                  writeDrafts(key, null);
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
              key={level}
              mode="ny_kanin"
              form={top.form}
              onChange={(field, value) => {
                touch();
                updateAt(level, (d) => ({
                  ...d,
                  form: { ...d.form, [field]: value },
                }));
              }}
              colors={colors}
              lookup={lookup}
              onSave={save}
              canSave={top.photo.status === "klar"}
              submitLabel="Spara"
              conflictHint="Stämmer pappret? Kontakta genbanksansvarig."
              photo={photo}
              where={top.where}
              onWhere={(where) => {
                touch();
                updateAt(level, (d) => ({ ...d, where }));
              }}
              onAddParent={(parent, number) => {
                touch();
                setStack((s) => [...s, fresh(parent, number)]);
              }}
              buttons={
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary"
                  onClick={() =>
                    top.parent
                      ? setStack((s) => s.slice(0, -1))
                      : requestClose()
                  }
                >
                  Avbryt
                </button>
              }
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
