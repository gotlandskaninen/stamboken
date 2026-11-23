"use client";

import { useState, useTransition } from "react";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { formatPostalCode, isValidPostalCode } from "@/lib/postal";
import { updateContact, verifyEmailCode } from "./actions";
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
  // "code": a code went to the new address; "done": the address is changed and the session has ended.
  const [emailStep, setEmailStep] = useState<"none" | "code" | "done">("none");
  const [code, setCode] = useState("");
  const waiting = emailStep === "code";
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
      // While a code waits the address is locked: sending it again would ask
      // for another code and spend one of the day's five.
      const patch: Partial<Contact> = {
        ...contact,
        email: contact.email.trim(),
      };
      if (!patch.email || waiting) delete patch.email;
      const result = await updateContact(patch);
      if (result.ok) {
        showSnackbar(
          result.codeSent
            ? "Sparat. Skriv koden för att byta e-postadress."
            : "Kontaktuppgifter sparade",
          "success",
        );
        if (result.emailRefused) showSnackbar(result.emailRefused, "warning");
        if (result.codeSent) {
          setCode("");
          setEmailStep("code");
        }
      } else {
        showSnackbar(result.error, "error");
        addNotification({
          title: "Kunde inte spara kontaktuppgifterna",
          message: result.error,
          type: "error",
        });
      }
    });

  const cancel = () => {
    setContact((c) => ({ ...c, email: initial.email }));
    setCode("");
    setEmailStep("none");
  };

  const verify = () =>
    start(async () => {
      const result = await verifyEmailCode(code);
      if (result.ok) {
        setEmailStep("done");
      } else {
        showSnackbar(result.error, "error");
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
              disabled={readOnly || waiting || emailStep === "done"}
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
            disabled={readOnly || pending || !postalOk || emailStep === "done"}
            onClick={save}
          >
            {pending ? "Sparar..." : "Spara"}
          </button>
        </div>
        {waiting && (
          <div className={styles.form} style={{ marginTop: 16 }}>
            <p className={styles.note}>
              Vi har skickat en kod till <strong>{contact.email.trim()}</strong>
              . Skriv in den här. Koden gäller i tio minuter. Sedan byts din
              adress.
            </p>
            <div className={styles.field}>
              <label className="sb-label" htmlFor="kontakt-kod">
                Kod
              </label>
              <input
                id="kontakt-kod"
                className={`sb-input ${styles.mono}`}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={9}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
            <div className={styles.actions}>
              <button
                type="button"
                className="sb-btn"
                disabled={pending || !code.trim()}
                onClick={verify}
              >
                Byt adress
              </button>
              <button
                type="button"
                className="sb-btn sb-btn-ghost"
                disabled={pending}
                onClick={cancel}
              >
                Avbryt
              </button>
            </div>
          </div>
        )}
        {emailStep === "done" && (
          <div
            className={`${styles.banner} ${styles.bannerInfo}`}
            role="status"
            style={{ marginTop: 16 }}
          >
            Nu är adressen bytt. Du är utloggad och får logga in igen.{" "}
            <a href="/auth/sign-in?return_to=/stamboken/profil">Logga in</a>
          </div>
        )}
      </div>
    </section>
  );
}
