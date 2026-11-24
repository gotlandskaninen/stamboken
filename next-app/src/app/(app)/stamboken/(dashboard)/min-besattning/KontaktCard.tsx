"use client";

import React from "react";
import { useRouter } from "next/navigation";

import { updateHerd } from "./actions";
import { useNotifications } from "@/contexts/NotificationContext";
import { useSnackbar } from "@/components/SnackbarProvider";
import ContactView from "@/components/herd-contact/ContactView";
import ContactEditor from "@/components/herd-contact/ContactEditor";
import type { Contact, OnSave } from "@/components/herd-contact/contactTypes";
import { MbCard } from "./min-besattning-ui";

export default function KontaktCard({
  herd,
  herdNumber,
}: {
  herd: any;
  herdNumber: string;
}) {
  const router = useRouter();
  const { addNotification } = useNotifications();
  const { showSnackbar } = useSnackbar();
  const [editing, setEditing] = React.useState(false);
  const contact: Contact | undefined = herd?.contact;
  if (!contact) return null;

  const onSave: OnSave = (patch) => updateHerd(herdNumber, patch);
  const onReload = () => router.refresh();
  const onDone = () => {
    setEditing(false);
    showSnackbar("Kontaktuppgifter sparade", "success");
    addNotification({
      title: "Kontaktuppgifter sparade",
      message: "Kontakten för besättningen och dess synlighet är uppdaterad.",
      type: "success",
    });
    router.refresh();
  };

  return (
    <MbCard
      title="Kontakt för besättningen"
      sub="Hämtas från ditt medlemskap, så en rättelse där gäller överallt. En rad kan ha en egen uppgift för besättningen."
      action={
        editing ? null : (
          <button
            type="button"
            className="sb-btn sb-btn-ghost sb-btn-sm"
            onClick={() => setEditing(true)}
          >
            Redigera
          </button>
        )
      }
    >
      {editing ? (
        <ContactEditor
          herd={herd}
          contact={contact}
          onSave={onSave}
          onReload={onReload}
          onDone={onDone}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <ContactView
          herd={herd}
          contact={contact}
          onSave={onSave}
          onReload={onReload}
        />
      )}
    </MbCard>
  );
}
