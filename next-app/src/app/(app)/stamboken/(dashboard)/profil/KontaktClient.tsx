"use client";

import { useState, useTransition } from "react";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { formatPostalCode, isValidPostalCode } from "@/lib/postal";
import { updateContact } from "./actions";
import styles from "./profil.module.css";

export type Contact = {
  phone: string;
  email: string;
  address: string;
  postal_code: string;
  city: string;
};

export function KontaktClient({
  readOnly = false,
  initial,
}: {
  readOnly?: boolean;
  initial: Contact;
}) {
  const [contact, setContact] = useState(initial);
  const [pending, start] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();
  const postalOk = isValidPostalCode(contact.postal_code);
  const set =
    (key: keyof Contact) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setContact({ ...contact, [key]: e.target.value });

  const save = () =>
    start(async () => {
      // MATR2026 rows may have no e-postadress. The API validates a present
      // `email` before it looks at the address fields (blueprints/members.py),
      // so a blank one must be omitted, not sent as "" — otherwise a member
      // without an e-mail could never save a postnummer.
      const patch: Partial<Contact> = {
        ...contact,
        email: contact.email.trim(),
      };
      if (!patch.email) delete patch.email;
      const result = await updateContact(patch);
      if (result.ok) {
        showSnackbar("Kontaktuppgifter sparade", "success");
      } else {
        showSnackbar(result.error, "error");
        addNotification({
          title: "Kunde inte spara kontaktuppgifterna",
          message: result.error,
          type: "error",
        });
      }
    });

  return (
    <section className="sb-card">
      <div className={styles.cardHead}>
        <h3 className={`sb-h6 ${styles.cardTitle}`}>Kontaktuppgifter</h3>
      </div>
      <div className={styles.cardBody}>
        {readOnly && (
          <div className={`${styles.banner} ${styles.bannerInfo}`}>
            Endast huvudmedlemmen kan ändra medlemskapets uppgifter.
          </div>
        )}
        <p className={styles.note}>
          Uppgifterna används i medlemsmatrikeln och för föreningens utskick.
          Vad som trycks i Koharen styr du under Publicering i Koharen.
        </p>
        <div className={styles.form}>
          <div className={styles.field}>
            <label className="sb-label" htmlFor="kontakt-phone">
              Telefon
            </label>
            <input
              id="kontakt-phone"
              className="sb-input"
              disabled={readOnly}
              value={contact.phone}
              onChange={set("phone")}
            />
          </div>
          <div className={styles.field}>
            <label className="sb-label" htmlFor="kontakt-email">
              E-post
            </label>
            <input
              id="kontakt-email"
              className="sb-input"
              type="email"
              disabled={readOnly}
              value={contact.email}
              onChange={set("email")}
            />
          </div>
          <div className={styles.field}>
            <label className="sb-label" htmlFor="kontakt-address">
              Gatuadress
            </label>
            <input
              id="kontakt-address"
              className="sb-input"
              disabled={readOnly}
              value={contact.address}
              onChange={set("address")}
            />
          </div>
          <div className={styles.formRow}>
            <div className={styles.field}>
              <label className="sb-label" htmlFor="kontakt-postal-code">
                Postnummer
              </label>
              <input
                id="kontakt-postal-code"
                className={`sb-input ${styles.mono}`}
                inputMode="numeric"
                maxLength={6}
                disabled={readOnly}
                value={contact.postal_code}
                onChange={set("postal_code")}
                onBlur={() =>
                  setContact((c) => ({
                    ...c,
                    postal_code: formatPostalCode(c.postal_code),
                  }))
                }
                aria-invalid={!postalOk}
              />
              <p className={postalOk ? styles.hint : styles.error}>
                {postalOk ? "5 siffror" : "Postnummer ska vara fem siffror"}
              </p>
            </div>
            <div className={styles.field}>
              <label className="sb-label" htmlFor="kontakt-city">
                Postort
              </label>
              <input
                id="kontakt-city"
                className="sb-input"
                maxLength={100}
                disabled={readOnly}
                value={contact.city}
                onChange={set("city")}
              />
            </div>
          </div>
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className="sb-btn"
            disabled={readOnly || pending || !postalOk}
            onClick={save}
          >
            {pending ? "Sparar..." : "Spara"}
          </button>
        </div>
      </div>
    </section>
  );
}
