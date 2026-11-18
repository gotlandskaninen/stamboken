"use client";

import { useId, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { assignHerd, assignItem, takeItem } from "./actions";
import type { Person } from "./lib";
import styles from "./inkorg.module.css";

function PersonSelect({
  people,
  value,
  onChange,
  label,
}: {
  people: Person[];
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
  return (
    <select
      className="sb-input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label}
    >
      <option value="">Välj person</option>
      {people.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}

/** "Jag tar den" on an untaken row, and assigning for managers and admins. */
export function RowActions({
  id,
  canTake,
  canAssign,
  people,
}: {
  id: number;
  canTake: boolean;
  canAssign: boolean;
  people: Person[];
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [to, setTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (!canTake && !canAssign) return null;

  const take = () =>
    start(async () => {
      const res = await takeItem(id);
      if (res.ok) router.push(`/stamboken/inkorg/${id}`);
      else setError(res.problem.detail);
    });
  const assign = () =>
    start(async () => {
      const res = await assignItem(id, Number(to));
      setError(res.ok ? null : res.problem.detail);
    });

  return (
    <div className={styles.rowActions}>
      {canTake && (
        <button
          type="button"
          className="sb-btn sb-btn-sm"
          disabled={pending}
          onClick={take}
        >
          Jag tar den
        </button>
      )}
      {canAssign && (
        <>
          <PersonSelect
            people={people}
            value={to}
            onChange={setTo}
            label={`Tilldela ärende ${id} till`}
          />
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            disabled={pending || !to}
            onClick={assign}
          >
            Tilldela
          </button>
        </>
      )}
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
    </div>
  );
}

/** Every open item of one herd to one person (POST /inkorg/tilldela). */
export function AssignHerd({ people }: { people: Person[] }) {
  const [pending, start] = useTransition();
  const [herd, setHerd] = useState("");
  const [to, setTo] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const herdId = useId();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    start(async () => {
      const res = await assignHerd(herd, Number(to));
      setMessage(
        res.ok
          ? {
              ok: true,
              text: res.data.assigned.length
                ? `Tilldelade ärende ${res.data.assigned.join(", ")}.`
                : "Besättningen har inga öppna ärenden.",
            }
          : { ok: false, text: res.problem.detail },
      );
    });
  };

  return (
    <section className={`sb-card ${styles.card}`}>
      <h2 className={styles.cardTitle}>Tilldela en hel besättning</h2>
      <p className={styles.muted}>
        Alla öppna ärenden för besättningen går till samma person.
      </p>
      <form className={styles.filters} onSubmit={submit}>
        <label htmlFor={herdId}>
          Besättning
          <input
            id={herdId}
            className="sb-input"
            value={herd}
            onChange={(e) => setHerd(e.target.value)}
            placeholder="G1274"
            size={8}
            required
          />
        </label>
        <label>
          Till
          <PersonSelect
            people={people}
            value={to}
            onChange={setTo}
            label="Till"
          />
        </label>
        <button
          type="submit"
          className="sb-btn sb-btn-sm"
          disabled={pending || !to || !herd.trim()}
        >
          Tilldela alla öppna
        </button>
      </form>
      {message && (
        <p
          role={message.ok ? "status" : "alert"}
          className={message.ok ? styles.muted : styles.error}
        >
          {message.text}
        </p>
      )}
    </section>
  );
}
