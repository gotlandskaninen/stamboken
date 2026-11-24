"use client";

import React, { useTransition } from "react";
import { useRouter } from "next/navigation";

import { updateHerd } from "./actions";
import { useNotifications } from "@/contexts/NotificationContext";
import { useSnackbar } from "@/components/SnackbarProvider";
import PrivacyChips from "@/components/herd-contact/PrivacyChips";
import {
  CONFLICT_TEXT,
  isConflict,
  type Privacy,
} from "@/components/herd-contact/contactTypes";
import { MbCard, MbPrivacy } from "./min-besattning-ui";
import styles from "@/components/herd-contact/herd-contact.module.css";

/* The place: flat herd fields, not part of the register's contact. herd_name has no privacy column. */
const ROWS: {
  key: "herd_name" | "location" | "www" | "wire_phone";
  label: string;
  chips?: string;
  url?: boolean;
}[] = [
  { key: "herd_name", label: "Besättningens namn" },
  { key: "location", label: "Ort", chips: "Vem ser orten" },
  { key: "www", label: "Hemsida", chips: "Vem ser hemsidan", url: true },
  {
    key: "wire_phone",
    label: "Fast telefon",
    chips: "Vem ser fasta telefonen",
  },
];

type Data = Record<string, string>;
const fromHerd = (h: any): Data => {
  const d: Data = {};
  for (const r of ROWS) {
    d[r.key] = h?.[r.key] ?? "";
    if (r.chips) d[`${r.key}_privacy`] = h?.[`${r.key}_privacy`] || "private";
  }
  return d;
};

export default function BesattningCard({
  herd,
  herdNumber,
}: {
  herd: any;
  herdNumber: string;
}) {
  const router = useRouter();
  const { addNotification } = useNotifications();
  const { showSnackbar } = useSnackbar();
  const [editing, setEditing] = React.useState(false);
  const [isPending, startTransition] = useTransition();
  const [data, setData] = React.useState<Data>(() => fromHerd(herd));
  const [seen, setSeen] = React.useState(herd);
  if (seen !== herd) {
    setSeen(herd);
    setData(fromHerd(herd));
  }

  const save = () =>
    startTransition(async () => {
      const before = fromHerd(herd);
      const changed = Object.keys(data).filter((k) => data[k] !== before[k]);
      const body: Record<string, unknown> = Object.fromEntries(
        changed.map((k) => [
          k,
          k.endsWith("_privacy") ? data[k] : data[k] || null,
        ]),
      );
      // the place, website and fixed phone are saved only against the row the form showed (409 otherwise)
      const place = (["location", "www", "wire_phone"] as const).filter((k) =>
        changed.some((c) => c === k || c === `${k}_privacy`),
      );
      if (place.length)
        body.place_shown = Object.fromEntries(
          place.map((k) => [
            k,
            { value: before[k] || null, privacy: before[`${k}_privacy`] },
          ]),
        );
      const result = changed.length
        ? await updateHerd(herdNumber, body)
        : { success: true as const };
      if (result.success) {
        setEditing(false);
        showSnackbar("Besättningsuppgifter sparade", "success");
        addNotification({
          title: "Besättningsuppgifter sparade",
          message:
            "Uppgifterna om besättningen och deras synlighet är uppdaterade.",
          type: "success",
        });
      } else {
        // the form was out of date: fetch the herd again, and the form follows it
        const conflict = isConflict(result);
        if (conflict) router.refresh();
        showSnackbar("Kunde inte spara ändringarna", "error");
        addNotification({
          title: "Kunde inte spara ändringarna",
          message: conflict
            ? CONFLICT_TEXT
            : result.error || "Ett okänt fel uppstod.",
          type: "error",
        });
      }
    });

  const shown = ROWS.filter((r) => data[r.key]);

  return (
    <MbCard
      title="Din besättning"
      sub="Där kaninerna finns. Uppgifterna gäller bara besättningen."
      action={
        editing ? (
          <span style={{ display: "inline-flex", gap: 8 }}>
            <button
              type="button"
              className="sb-btn sb-btn-ghost sb-btn-sm"
              disabled={isPending}
              onClick={() => {
                setData(fromHerd(herd));
                setEditing(false);
              }}
            >
              Avbryt
            </button>
            <button
              type="button"
              className="sb-btn sb-btn-sm"
              disabled={isPending}
              onClick={save}
            >
              {isPending ? "Sparar…" : "Spara"}
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="sb-btn sb-btn-ghost sb-btn-sm"
            onClick={() => setEditing(true)}
          >
            Redigera
          </button>
        )
      }
    >
      {!editing ? (
        shown.length === 0 ? (
          <p className="sb-meta" style={{ margin: 0 }}>
            Inga uppgifter om besättningen ännu. Tryck Redigera.
          </p>
        ) : (
          <dl className={styles.rows}>
            {shown.map((r) => (
              <div key={r.key} className={styles.row}>
                <dt>{r.label}</dt>
                <dd>
                  {r.url ? (
                    <a
                      className={`sb-link ${styles.value}`}
                      href={
                        data[r.key].startsWith("http")
                          ? data[r.key]
                          : `https://${data[r.key]}`
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {data[r.key]}
                    </a>
                  ) : (
                    <span className={styles.value}>{data[r.key]}</span>
                  )}
                  {r.chips && (
                    <span className={styles.metaLine}>
                      <MbPrivacy level={data[`${r.key}_privacy`]} />
                    </span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )
      ) : (
        <div className={styles.edit}>
          {ROWS.map((r) => (
            <div key={r.key}>
              <label className={styles.label} htmlFor={`herd-${r.key}`}>
                {r.label}
              </label>
              <input
                id={`herd-${r.key}`}
                className="sb-input"
                value={data[r.key]}
                onChange={(e) =>
                  setData((d) => ({ ...d, [r.key]: e.target.value }))
                }
              />
              {r.chips && (
                <PrivacyChips
                  label={r.chips}
                  value={data[`${r.key}_privacy`] as Privacy}
                  onChange={(p) =>
                    setData((d) => ({ ...d, [`${r.key}_privacy`]: p }))
                  }
                />
              )}
            </div>
          ))}
        </div>
      )}
    </MbCard>
  );
}
