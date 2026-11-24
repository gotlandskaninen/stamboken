"use client";

import { useEffect, useState, useTransition } from "react";
import { useTranslation } from "react-i18next";
import { assignHerd, assignItem, previewHerd } from "./actions";
import { useQueueUndo } from "./QueueUndo";
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
  const { t } = useTranslation();
  return (
    <select
      className="sb-input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label}
    >
      <option value="">{t("queueAssignment.choose")}</option>
      {people.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}

export function AssignItem({ id, people }: { id: number; people: Person[] }) {
  const { t } = useTranslation();
  const { offerUndo } = useQueueUndo();
  const [pending, start] = useTransition();
  const [to, setTo] = useState("");
  const [error, setError] = useState("");
  const person = people.find((p) => p.id === Number(to));
  const assign = () => {
    if (!person) return;
    start(async () => {
      const res = await assignItem(id, person.id);
      if (!res.ok) return setError(res.problem.detail);
      setError("");
      offerUndo(
        res.data.undo,
        t("queueAssignment.assignedItem", { id, name: person.name }),
      );
    });
  };
  return (
    <div className={styles.rowActions}>
      <PersonSelect
        people={people}
        value={to}
        onChange={setTo}
        label={t("queueAssignment.assignTo", { id })}
      />
      <button
        type="button"
        className="sb-btn sb-btn-secondary"
        disabled={pending || !person}
        onClick={assign}
      >
        {t("queueAssignment.assign")}
      </button>
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
    </div>
  );
}

type PreviewResult = Awaited<ReturnType<typeof previewHerd>>;

export function AssignHerd({ people }: { people: Person[] }) {
  const { t, i18n } = useTranslation();
  const { offerUndo, revision } = useQueueUndo();
  const [pending, start] = useTransition();
  const [herd, setHerd] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loaded, setLoaded] = useState<{
    key: string;
    result: PreviewResult;
  } | null>(null);
  const code = herd.trim().toUpperCase();
  const key = `${code}/${revision}/${refresh}`;
  const result = loaded?.key === key ? loaded.result : null;
  const preview = result?.ok ? result.data : null;
  const person = people.find((p) => p.id === Number(to));
  const others = preview?.assignees.filter((p) => p.id !== Number(to)) ?? [];
  const othersCount = others.reduce((sum, p) => sum + p.count, 0);

  // Look up the whole herd, independently of the list's pagination and filters.
  useEffect(() => {
    if (!code) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      const result = await previewHerd(code);
      if (active) setLoaded({ key, result });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [key, code]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!preview?.total || !person || pending) return;
    setError("");
    start(async () => {
      const res = await assignHerd(code, person.id, preview.revision);
      if (!res.ok) {
        setError(res.problem.detail);
        if (res.problem.status === 409) setRefresh((v) => v + 1);
        return;
      }

      offerUndo(
        res.data.undo,
        t("queueAssignment.assignedCount", {
          count: res.data.assigned.length,
          name: person.name,
        }),
      );
    });
  }

  return (
    <details className={styles.assignHerd}>
      <summary>{t("queueAssignment.herdTitle")}</summary>
      <form className={styles.filters} onSubmit={submit}>
        <label>
          {t("queueAssignment.herd")}
          <input
            className="sb-input"
            value={herd}
            onChange={(e) => {
              setHerd(e.target.value);
              setError("");
            }}
            placeholder={t("queueAssignment.example")}
            autoComplete="off"
            required
          />
        </label>
        <label>
          {t("queueAssignment.to")}
          <PersonSelect
            people={people}
            value={to}
            onChange={(value) => {
              setTo(value);
              setError("");
            }}
            label={t("queueAssignment.to")}
          />
        </label>
        <div className={styles.assignPreview} aria-live="polite">
          {preview &&
            (preview.total ? (
              <>
                <strong>
                  {t("queueAssignment.count", {
                    count: preview.total,
                    herd: code,
                  })}
                </strong>
                {othersCount > 0 &&
                  t("queueAssignment.others", {
                    count: othersCount,
                    names: new Intl.ListFormat(i18n.language).format(
                      others.map((p) => p.name),
                    ),
                  })}
                .
              </>
            ) : (
              t("queueAssignment.none")
            ))}
        </div>
        {result && !result.ok && (
          <div>
            <p role="alert" className={styles.error}>
              {result.problem.detail}
            </p>
            <button
              type="button"
              className="sb-btn sb-btn-secondary"
              onClick={() => setRefresh((v) => v + 1)}
            >
              {t("queueAssignment.retry")}
            </button>
          </div>
        )}
        <button
          type="submit"
          className="sb-btn"
          disabled={pending || !person || !preview?.total}
        >
          {preview?.total
            ? t("queueAssignment.assignCount", { count: preview.total })
            : t("queueAssignment.assign")}
        </button>
        {error && (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}
      </form>
    </details>
  );
}
