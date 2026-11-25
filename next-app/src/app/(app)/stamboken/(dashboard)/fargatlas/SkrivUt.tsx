"use client";

import styles from "@/components/fargatlas/fargatlas.module.css";

export function SkrivUt() {
  return (
    <button
      type="button"
      className={`sb-btn ${styles.skrivUt}`}
      onClick={async () => {
        // Photos further down have not loaded yet (loading="lazy"); print them too.
        const bilder = [
          ...document.querySelectorAll<HTMLImageElement>("img[loading=lazy]"),
        ];
        bilder.forEach((img) => (img.loading = "eager"));
        await Promise.allSettled(bilder.map((img) => img.decode()));
        window.print();
      }}
    >
      Skriv ut
    </button>
  );
}
