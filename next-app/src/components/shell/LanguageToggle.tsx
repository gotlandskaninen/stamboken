"use client";

import { useTranslation } from "react-i18next";
import { SbIcon } from "./SbIcon";
import styles from "./topbar.module.css";

export function LanguageToggle() {
  const { i18n } = useTranslation();
  const current = i18n.language === "en" ? "en" : "sv";
  const next = current === "sv" ? "en" : "sv";
  return (
    <button
      type="button"
      aria-label={`Byt språk till ${next === "en" ? "engelska" : "svenska"}`}
      onClick={() => i18n.changeLanguage(next)}
      className={styles.langBtn}
    >
      <SbIcon name="globe" size={18} />
      {current.toUpperCase()}
    </button>
  );
}
