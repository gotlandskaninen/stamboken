"use client";

import { useState, useTransition } from "react";
import { reviewBuyerEmail } from "../../actions";
import styles from "../../../inskick/inskick.module.css";

export type ReviewBuyer = { id: number; name: string; email: string };

export function BuyerEmailReview({ buyer }: { buyer: ReviewBuyer }) {
  const [name, setName] = useState(buyer.name);
  const [email, setEmail] = useState(buyer.email);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [pending, start] = useTransition();
  const changed = name !== buyer.name || email !== buyer.email;
  if (done) return <p role="status">Adressen är kontrollerad.</p>;
  return (
    <form
      className="sb-card"
      onSubmit={(e) => {
        e.preventDefault();
        start(async () => {
          const result = await reviewBuyerEmail(
            buyer.id,
            changed ? { name, email } : { confirm: true },
          );
          if (result.ok) setDone(true);
          else setError(result.error);
        });
      }}
    >
      <fieldset className={styles.cardBody} disabled={pending}>
        <legend>Köparuppgifter</legend>
        <p>
          Kontrollera mot försäljningsbeviset. Rätta uppgifterna eller bekräfta
          att adressen tillhör samma person vid båda köpen.
        </p>
        <label className={styles.field}>
          Köparens namn
          <input
            className="sb-input"
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          E-postadress
          <input
            className="sb-input"
            required
            type="email"
            maxLength={200}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <button className="sb-btn sb-btn-primary" type="submit">
          {changed ? "Spara rättelse" : "Bekräfta att det är samma person"}
        </button>
      </fieldset>
    </form>
  );
}
