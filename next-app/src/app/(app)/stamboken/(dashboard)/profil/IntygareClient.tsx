"use client";

import { useState, useTransition } from "react";
import { FormControlLabel, Switch } from "@mui/material";
import { useSnackbar } from "@/components/SnackbarProvider";
import { setNameOnCheckPage } from "./actions";
import styles from "./profil.module.css";

/* The person's own choice to show her name as "Intygas av" on the public
   check page behind a certificate's QR code (stamboken #6). null = not chosen
   yet: the page then shows her role, "Uppfödaren". */
export function IntygareClient({ initial }: { initial: boolean | null }) {
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
          står ditt namn som intygare om du väljer det, annars din roll, till
          exempel &quot;Uppfödaren&quot;. Valet gäller alla intyg du har
          utfärdat och kan ändras när som helst. På själva intyget står ditt
          namn alltid. Valet gäller dina riktiga intyg, också när du provar
          Stamboken i testläget.
        </p>
        {show === null ? (
          <>
            <p className={styles.note}>
              <strong>Du har inte valt än.</strong> Tills du väljer står din
              roll på kontrollsidan, till exempel &quot;Uppfödaren&quot;.
            </p>
            <div className={styles.actions}>
              <button
                type="button"
                className="sb-btn sb-btn-ghost"
                disabled={pending}
                onClick={() => change(false)}
              >
                Visa inte mitt namn
              </button>
              <button
                type="button"
                className="sb-btn"
                disabled={pending}
                onClick={() => change(true)}
              >
                Visa mitt namn
              </button>
            </div>
          </>
        ) : (
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
        )}
      </div>
    </section>
  );
}
