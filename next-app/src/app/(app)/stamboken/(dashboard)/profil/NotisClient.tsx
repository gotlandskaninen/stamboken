"use client";

import { useState, useTransition } from "react";
import { FormControlLabel, Switch } from "@mui/material";
import { useSnackbar } from "@/components/SnackbarProvider";
import { setMailNotices } from "../notiser/actions";
import styles from "./profil.module.css";

export function NotisClient({ initial }: { initial: boolean }) {
  const [enabled, setEnabled] = useState(initial);
  const [pending, start] = useTransition();
  const { showSnackbar } = useSnackbar();

  const change = (next: boolean) =>
    start(async () => {
      const res = await setMailNotices(next);
      if (res.ok) {
        setEnabled(res.mailEnabled);
        showSnackbar("Notisinställningen sparad", "success");
      } else {
        showSnackbar(res.error, "error");
      }
    });

  return (
    <section className="sb-card">
      <div className={styles.cardHead}>
        <h3 className={`sb-h6 ${styles.cardTitle}`}>Notiser</h3>
      </div>
      <div className={styles.cardBody}>
        <p className={styles.note}>
          Notiserna syns alltid i Stamboken. Här väljer du om de också ska komma
          på e-post.
        </p>
        <FormControlLabel
          className={styles.switchRow}
          labelPlacement="start"
          label="Skicka notiser per e-post en gång om dagen"
          control={
            <Switch
              checked={enabled}
              disabled={pending}
              onChange={(e) => change(e.target.checked)}
            />
          }
        />
      </div>
    </section>
  );
}
