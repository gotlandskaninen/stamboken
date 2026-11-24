import React from "react";
import { SbIcon } from "@/components/shell/SbIcon";
import { PRIVACY_LABEL } from "./contactTypes";
import styles from "./herd-contact.module.css";

export default function PrivacyBadge({ level }: { level: string }) {
  const open = level === "authenticated" || level === "public";
  return (
    <span
      className={`${styles.priv}${open ? ` ${styles.privOpen}` : ""}`}
      title="Vem ser uppgiften"
    >
      <SbIcon
        name={level === "public" ? "globe" : open ? "users" : "shield"}
        size={14}
      />
      {PRIVACY_LABEL[level] ?? PRIVACY_LABEL.private}
    </span>
  );
}
