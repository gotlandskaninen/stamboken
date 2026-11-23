"use client";

import React, { useTransition } from "react";

import { useUser } from "@/lib/user-context";
import { updateHerd as updateHerdAction } from "./actions";
import { useNotifications } from "@/contexts/NotificationContext";
import { useSnackbar } from "@/components/SnackbarProvider";
import { getErrorDetails, formatErrorForAdmin } from "@/utils/errorHandling";
import { MbCard, MbPrivacy, MB_PRIVACY_LABEL } from "./min-besattning-ui";
import styles from "./min-besattning.module.css";

type Privacy = "private" | "authenticated";

interface ContactData {
  name: string;
  email: string;
  mobile_phone: string;
  wire_phone: string;
  www: string;
  physical_address: string;
  name_privacy: Privacy;
  email_privacy: Privacy;
  mobile_phone_privacy: Privacy;
  wire_phone_privacy: Privacy;
  www_privacy: Privacy;
  physical_address_privacy: Privacy;
}

interface BesattningsuppgifterCardProps {
  herd: any;
  herdNumber: string;
}

/* value field key -> label; the privacy key is always `${key}_privacy` */
const CONTACT_ROWS: { key: string; label: string; kind?: "email" | "url" }[] = [
  { key: "name", label: "Kontaktperson" },
  { key: "email", label: "E-post", kind: "email" },
  { key: "mobile_phone", label: "Mobil" },
  { key: "wire_phone", label: "Fast telefon" },
  { key: "www", label: "Hemsida", kind: "url" },
  { key: "physical_address", label: "Adress" },
];

/* Single source for both the initial state and the Avbryt reset (the shape is
   the one moved verbatim in B1). */
const contactFromHerd = (h: any): ContactData => ({
  name: h?.name || "",
  email: h?.email || "",
  mobile_phone: h?.mobile_phone || "",
  wire_phone: h?.wire_phone || "",
  www: h?.www || "",
  physical_address: h?.physical_address?.split("|")[0] || "",
  name_privacy: h?.name_privacy || "private",
  email_privacy: h?.email_privacy || "private",
  mobile_phone_privacy: h?.mobile_phone_privacy || "private",
  wire_phone_privacy: h?.wire_phone_privacy || "private",
  www_privacy: h?.www_privacy || "private",
  physical_address_privacy: h?.physical_address_privacy || "private",
});

export default function BesattningsuppgifterCard({
  herd,
  herdNumber,
}: BesattningsuppgifterCardProps) {
  const user = useUser();
  const { addNotification } = useNotifications();
  const { showSnackbar } = useSnackbar();

  const [isEditingContact, setIsEditingContact] = React.useState(false);
  const [isPending, startTransition] = useTransition();

  // Local state for editing contact information
  const [contactData, setContactData] = React.useState<ContactData>(() =>
    contactFromHerd(herd),
  );

  // Update local state when herd data loads
  React.useEffect(() => {
    if (herd) {
      setContactData(contactFromHerd(herd));
    }
  }, [herd]);

  const handleContactChange = (field: string, value: string) => {
    setContactData((prev) => ({ ...prev, [field]: value }));
  };

  const handleSaveContact = () =>
    startTransition(async () => {
      if (!herd?.id) {
        const errorDetails = getErrorDetails(
          { errorType: "Validation Error", message: "Ingen herd ID" },
          user?.username || user?.email || "unknown",
        );
        addNotification({
          title: "Tekniskt fel",
          message: `Besättnings-ID saknas. Kontakta admin@gotlandskaninen.se\n\n${formatErrorForAdmin(errorDetails)}`,
          type: "error",
          action: {
            label: "Kopiera felinfo",
            onClick: () => {
              navigator.clipboard.writeText(formatErrorForAdmin(errorDetails));
              showSnackbar("Felinfo kopierad till clipboard", "info");
            },
          },
        });
        return;
      }

      // Prepare data in the format expected by the API
      const updateData: Record<string, unknown> = {
        name: contactData.name || null,
        email: contactData.email || null,
        mobile_phone: contactData.mobile_phone || null,
        wire_phone: contactData.wire_phone || null,
        www: contactData.www || null,
        physical_address: contactData.physical_address || null,
        name_privacy: contactData.name_privacy,
        email_privacy: contactData.email_privacy,
        mobile_phone_privacy: contactData.mobile_phone_privacy,
        wire_phone_privacy: contactData.wire_phone_privacy,
        www_privacy: contactData.www_privacy,
        physical_address_privacy: contactData.physical_address_privacy,
      };

      const result = await updateHerdAction(herdNumber, updateData);

      if (result.success) {
        setIsEditingContact(false);

        // Immediate feedback with snackbar
        showSnackbar("Kontaktinformation sparad", "success");

        // Long-term notification for session history
        addNotification({
          title: "Kontaktinformation sparad",
          message:
            "Dina kontaktuppgifter och integritetsinställningar har uppdaterats.",
          type: "success",
        });
      } else {
        // Immediate feedback
        showSnackbar("Kunde inte spara ändringarna", "error");

        // Detailed notification
        addNotification({
          title: "Kunde inte spara ändringarna",
          message: result.error || "Ett okänt fel uppstod.",
          type: "error",
        });
      }
    });

  const handleCancelContact = () => {
    setContactData(contactFromHerd(herd));
    setIsEditingContact(false);
  };

  const val = (k: string) =>
    (contactData as unknown as Record<string, string>)[k];
  const priv = (k: string) =>
    (contactData as unknown as Record<string, string>)[`${k}_privacy`];

  const filledRows = CONTACT_ROWS.filter((r) => val(r.key));

  return (
    <MbCard
      title="Besättningsuppgifter"
      action={
        isEditingContact ? (
          <span style={{ display: "inline-flex", gap: 8 }}>
            <button
              type="button"
              className="sb-btn sb-btn-ghost sb-btn-sm"
              onClick={handleCancelContact}
              disabled={isPending}
            >
              Avbryt
            </button>
            <button
              type="button"
              className="sb-btn sb-btn-ghost sb-btn-sm"
              onClick={handleSaveContact}
              disabled={isPending}
            >
              {isPending ? "Sparar…" : "Klar"}
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="sb-btn sb-btn-ghost sb-btn-sm"
            onClick={() => setIsEditingContact(true)}
          >
            Redigera
          </button>
        )
      }
    >
      {!isEditingContact ? (
        filledRows.length === 0 ? (
          <p className="sb-meta" style={{ margin: 0 }}>
            Inga besättningsuppgifter angivna ännu — tryck Redigera.
          </p>
        ) : (
          <dl className={styles["mb-contact"]}>
            {filledRows.map((r) => (
              <div key={r.key} className={styles["mb-contact-row"]}>
                <dt>{r.label}</dt>
                <dd>
                  {r.kind === "email" ? (
                    <a className="sb-link" href={`mailto:${val(r.key)}`}>
                      {val(r.key)}
                    </a>
                  ) : r.kind === "url" ? (
                    <a
                      className="sb-link"
                      href={
                        val(r.key).startsWith("http")
                          ? val(r.key)
                          : `https://${val(r.key)}`
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {val(r.key)}
                    </a>
                  ) : (
                    val(r.key)
                  )}
                  <div style={{ marginTop: 4 }}>
                    <MbPrivacy level={priv(r.key)} />
                  </div>
                </dd>
              </div>
            ))}
          </dl>
        )
      ) : (
        <div className={styles["mb-stack"]}>
          {CONTACT_ROWS.map((r) => (
            <div key={r.key}>
              <label className="sb-label" htmlFor={`contact-${r.key}`}>
                {r.label}
              </label>
              <input
                id={`contact-${r.key}`}
                className="sb-input"
                value={val(r.key)}
                onChange={(e) => handleContactChange(r.key, e.target.value)}
              />
              <div className={styles["mb-privacy-toggle"]}>
                {(["private", "authenticated"] as Privacy[]).map((p) => (
                  <button
                    key={p}
                    type="button"
                    aria-pressed={priv(r.key) === p}
                    className={`${styles["mb-herd-chip"]}${
                      priv(r.key) === p ? ` ${styles["is-active"]}` : ""
                    }`}
                    onClick={() => handleContactChange(`${r.key}_privacy`, p)}
                  >
                    {MB_PRIVACY_LABEL[p]}
                  </button>
                ))}
              </div>
            </div>
          ))}

          {/* Kept from the pre-B7 card: the medlemsmatrikel notice is real
              user guidance, not MUI chrome, so it survives the rebuild. */}
          <div
            style={{ fontSize: 13, lineHeight: 1.5, color: "var(--sb-ink-3)" }}
          >
            <p style={{ margin: "0 0 8px" }}>
              <strong>Du bestämmer över dina uppgifter.</strong> Du som är
              besättningsinnehavare fyller själv i de kontaktuppgifter du vill
              att andra besättningar ska se för att underlätta kommunikation
              mellan besättningarna. Du kan själv, när som helst, gå in och
              ändra i dina kontaktuppgifter.
            </p>
            <p style={{ margin: 0 }}>
              <strong style={{ color: "var(--sb-lera)" }}>
                OBS! Tänk på medlemsmatrikeln.
              </strong>{" "}
              En ändring här slår inte igenom till föreningens medlemsmatrikel,
              så om du exempelvis flyttat eller bytt e-post, måste du också
              meddela det till föreningens kassör, för ändring i
              medlemsmatrikeln. Medlemsmatrikeln används bara för föreningens
              interna administration, och är inte offentlig.
            </p>
          </div>
        </div>
      )}
    </MbCard>
  );
}
