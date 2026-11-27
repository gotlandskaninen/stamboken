"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useMode } from "@/lib/mode-context";
import type { Mode } from "@/lib/mode";
import { turn } from "../../../inkorg/image";
import { updateDocument } from "../../../inkorg/actions";
import { PhotoViewer } from "../../../inkorg/[id]/PhotoViewer";
import type { InboxDetail } from "../../../inkorg/lib";
import { nextPaperForm } from "../../actions";
import { formDocumentIds, intygPending, type ReportView } from "../../lib";
import { ReportForm, type ReportActions } from "../../ReportForm";
import styles from "../../arsrapport.module.css";

const WIDE = "(min-width: 1100px)";
const subscribe = (cb: () => void) => {
  const m = window.matchMedia?.(WIDE);
  m?.addEventListener("change", cb);
  return () => m?.removeEventListener("change", cb);
};

// "Från blankett": the photo of the form beside the report form. From 1100 px
// the photo stands on the left; below that it waits behind "Visa blanketten".
export function PaperEntry({
  view,
  item,
  actions,
  post,
  env,
}: {
  view: ReportView;
  item: InboxDetail;
  actions: ReportActions;
  post: number;
  env: Mode;
}) {
  const router = useRouter();
  const leaving = React.useRef(false);
  const { showSnackbar } = useSnackbar();
  const mode = useMode();
  const apiBase =
    mode === "demo" && process.env.NEXT_PUBLIC_API_TEST_URL
      ? process.env.NEXT_PUBLIC_API_TEST_URL
      : "/api";
  const pages = item.documents.filter((d) => d.doc_type === "arsblankett");
  const [selected, setSelected] = React.useState(pages[0]?.id ?? null);
  const [turns, setTurns] = React.useState<Record<number, number>>({});
  const [shown, setShown] = React.useState(false);
  const wide = React.useSyncExternalStore(
    subscribe,
    () => !!window.matchMedia?.(WIDE).matches,
    () => false,
  );
  const doc = pages.find((d) => d.id === selected) ?? null;

  return (
    <div className={styles.paperPage}>
      <section className={styles.photoPane} aria-label="Blanketten">
        <button
          type="button"
          className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary} ${styles.photoToggle}`}
          aria-expanded={shown}
          onClick={() => setShown((v) => !v)}
        >
          {shown ? "Dölj blanketten" : "Visa blanketten"}
        </button>
        {(wide || shown) && doc && (
          <>
            {pages.length > 1 && (
              <div className={styles.filters} role="group" aria-label="Sida">
                {pages.map((d, i) => (
                  <button
                    key={d.id}
                    type="button"
                    className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                    aria-pressed={d.id === selected}
                    onClick={() => setSelected(d.id)}
                  >
                    Sida {i + 1}
                  </button>
                ))}
              </div>
            )}
            <PhotoViewer
              key={doc.id}
              src={`${apiBase}/v2/inkorg/${item.id}/dokument/${doc.id}/original`}
              rotation={turns[doc.id] ?? doc.rotation}
              onRotate={(q) =>
                setTurns((t) => ({
                  ...t,
                  [doc.id]: turn(t[doc.id] ?? doc.rotation, q),
                }))
              }
            />
          </>
        )}
      </section>
      <ReportForm
        key={env}
        env={env}
        view={view}
        actions={actions}
        post={post}
        stickyTop={56}
        paper={{
          documentIds: formDocumentIds(item),
          intygPending: intygPending(item),
          archive: (id) =>
            updateDocument(item.id, id, { dismissed: true }, env),
          leave: async (message, destination) => {
            if (leaving.current) return;
            leaving.current = true;
            const inbox = "/stamboken/inkorg";
            const href =
              destination === "next"
                ? await nextPaperForm(env).catch(() => inbox)
                : inbox;
            if (message) showSnackbar(message);
            router.push(href);
          },
        }}
      />
    </div>
  );
}
