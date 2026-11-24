import React from "react";
import { PRIVACY_LABEL, type Privacy } from "./contactTypes";
import styles from "./herd-contact.module.css";

const LEVELS: Privacy[] = ["private", "authenticated"];

export default function PrivacyChips({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Privacy;
  onChange: (p: Privacy) => void;
}) {
  return (
    <div className={styles.chips} role="group" aria-label={label}>
      {(value === "public" ? [...LEVELS, value] : LEVELS).map((p) => (
        <button
          key={p}
          type="button"
          className={styles.chip}
          aria-pressed={value === p}
          onClick={() => onChange(p)}
        >
          {PRIVACY_LABEL[p]}
        </button>
      ))}
    </div>
  );
}
