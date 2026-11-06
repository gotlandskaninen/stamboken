"use client";

import { useState, useTransition } from "react";
import { ConfirmDialog } from "../../_components/ConfirmDialog";
import { massLogout } from "../actions";
import ds from "@/styles/ds-admin.module.css";

export function MassLogoutClient() {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const confirm = () =>
    startTransition(async () => {
      const result = await massLogout();
      if ("error" in result) {
        setError(result.error);
        setOpen(false);
        return;
      }
      // Our own session was just cleared with everyone else's — land on the
      // sign-in page like everyone else.
      window.location.assign("/auth/sign-in");
    });

  return (
    <section className={`sb-card ${ds["ad-card-danger"]} ${ds["ad-card-gap"]}`}>
      <div className={ds["ad-card-head"]}>
        <h3 className={`sb-h6 ${ds["ad-card-title"]}`}>Massutloggning</h3>
      </div>
      <div className={ds["ad-card-body"]}>
        <p className={ds["ad-hint"]}>
          Använd detta om du misstänker att någon obehörig har fått åtkomst till
          ett konto. Alla inloggade användare loggas ut — inklusive du själv.
        </p>
        {error && (
          <div className={`${ds["ad-banner"]} ${ds["ad-banner-danger"]}`}>
            {error}
          </div>
        )}
        <button
          type="button"
          className={`sb-btn ${ds["ad-btn-danger"]}`}
          disabled={pending}
          onClick={() => setOpen(true)}
        >
          Logga ut alla användare
        </button>
      </div>
      {/* ConfirmDialog: body is a string prop and the
          type-to-confirm prop is `typeToConfirm` (the dialog renders its
          own "Skriv LOGGA UT ALLA för att bekräfta" text field). */}
      <ConfirmDialog
        open={open}
        title="Logga ut alla användare?"
        body="Alla inloggade användare loggas ut — inklusive du själv."
        confirmLabel="Logga ut alla"
        confirmColor="error"
        typeToConfirm="LOGGA UT ALLA"
        onClose={() => setOpen(false)}
        onConfirm={confirm}
      />
    </section>
  );
}
