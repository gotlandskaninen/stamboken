"use client";

import { useState, useTransition } from "react";
import { FormControlLabel, Switch } from "@mui/material";
import { useSnackbar } from "@/components/SnackbarProvider";
import { setNameOnCheckPage } from "./actions";
import styles from "./profil.module.css";

/* The person's own choice to show her name as "Intygas av" on the public
   check page behind a certificate's QR code (stamboken #6). */
export function IntygareClient({ initial }: { initial: boolean }) {
  const [show, setShow] = useState(initial);
  const [pending, start] = useTransition();
  const { showSnackbar } = useSnackbar();

  const change = (next: boolean) =>
    start(async () => {
      const res = await setNameOnCheckPage(next);
      if (res.ok) {
        setShow(res.show);
        showSnackbar("Valet är sparat", "success");
      } else {
        showSnackbar(res.error, "error");
      }
    });

  return (
    <section className="sb-card">
      <div className={styles.cardHead}>
        <h3 className={`sb-h6 ${styles.cardTitle}`}>Intygens kontrollsida</h3>
      </div>
      <div className={styles.cardBody}>
        <p className={styles.note}>
          Alla som har ett intygs QR-kod kan öppna intygets kontrollsida. Där
          står &quot;Intygas av: Uppfödaren&quot; för intyg som du har utfärdat.
          Väljer du det står ditt namn där i stället. På själva intyget står
          ditt namn alltid.
        </p>
        <FormControlLabel
          className={styles.switchRow}
          /* ADR-0010 touch target: the one-line label alone is 42 px */
          sx={{ minHeight: 44 }}
          labelPlacement="start"
          label="Visa mitt namn på kontrollsidan"
          control={
            <Switch
              checked={show}
              disabled={pending}
              onChange={(e) => change(e.target.checked)}
            />
          }
        />
      </div>
    </section>
  );
}
