"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  TextField,
} from "@mui/material";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import {
  CREATABLE_STATUSES,
  MEMBERSHIP_STATUS,
  type MembershipStatus,
} from "@/lib/membershipStatus";
import { formatPostalCode, isValidPostalCode } from "@/lib/postal";
import { createMembership } from "./actions";
import styles from "../medlem.module.css";

const EMPTY_CREATE_FORM = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  address: "",
  postal_code: "",
  city: "",
  membership_status: "active" as MembershipStatus,
  allocate: true,
};

/** Masthead affordance — owns the open state so the RSC page stays a server component. */
export function NewMembershipButton() {
  const [open, setOpen] = useState(false);
  // Remount the dialog on every open: its form state lives in useState, so a
  // draft cancelled with Avbryt/Escape would otherwise come back prefilled
  // with the previous person's data.
  const [session, setSession] = useState(0);
  return (
    <>
      <button
        type="button"
        className="sb-btn sb-btn-sm"
        onClick={() => {
          setSession((s) => s + 1);
          setOpen(true);
        }}
      >
        Nytt medlemskap
      </button>
      <NewMembershipDialog
        key={session}
        open={open}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

export function NewMembershipDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();
  const [form, setForm] = useState(EMPTY_CREATE_FORM);
  const [pending, startTransition] = useTransition();
  const postalOk = isValidPostalCode(form.postal_code);

  const submit = () => {
    startTransition(async () => {
      const result = await createMembership({
        first_name: form.first_name,
        last_name: form.last_name,
        email: form.email || null,
        phone: form.phone || null,
        address: form.address || null,
        postal_code: form.postal_code || null,
        city: form.city || null,
        membership_status: form.membership_status,
        allocate: form.allocate,
      });
      if (!result.ok) {
        showSnackbar(result.error, "error");
        addNotification({
          title: "Kunde inte skapa medlemskap",
          message: result.error,
          type: "error",
        });
        return;
      }
      setForm(EMPTY_CREATE_FORM);
      onClose();
      showSnackbar("Medlemskap skapat", "success");
      if (result.id) router.push(`/medlem/matrikel/${result.id}`);
    });
  };

  return (
    <Dialog
      open={open}
      onClose={pending ? undefined : onClose}
      fullWidth
      maxWidth="sm"
    >
      <DialogTitle>Nytt medlemskap</DialogTitle>
      <DialogContent>
        <div className={styles.dialogBody}>
          <TextField
            label="Förnamn"
            required
            value={form.first_name}
            onChange={(e) => setForm({ ...form, first_name: e.target.value })}
          />
          <TextField
            label="Efternamn"
            required
            value={form.last_name}
            onChange={(e) => setForm({ ...form, last_name: e.target.value })}
          />
          <TextField
            label="E-post"
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
          <TextField
            label="Telefon"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
          <TextField
            label="Gatuadress"
            value={form.address}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
          />
          <TextField
            label="Postnummer"
            value={form.postal_code}
            onChange={(e) => setForm({ ...form, postal_code: e.target.value })}
            onBlur={() =>
              setForm((f) => ({
                ...f,
                postal_code: formatPostalCode(f.postal_code),
              }))
            }
            error={!postalOk}
            helperText={
              postalOk ? "5 siffror" : "Postnummer ska vara fem siffror"
            }
            slotProps={{ htmlInput: { inputMode: "numeric", maxLength: 6 } }}
          />
          <TextField
            label="Postort"
            value={form.city}
            onChange={(e) => setForm({ ...form, city: e.target.value })}
            slotProps={{ htmlInput: { maxLength: 100 } }}
          />
          <TextField
            select
            label="Status"
            value={form.membership_status}
            onChange={(e) =>
              setForm({
                ...form,
                membership_status: e.target.value as MembershipStatus,
              })
            }
          >
            {CREATABLE_STATUSES.map((s) => (
              <MenuItem key={s} value={s}>
                {MEMBERSHIP_STATUS[s].label}
              </MenuItem>
            ))}
          </TextField>
          <FormControlLabel
            control={
              <Checkbox
                checked={form.allocate}
                onChange={(e) =>
                  setForm({ ...form, allocate: e.target.checked })
                }
              />
            }
            label="Tilldela medlemsnummer automatiskt"
          />
        </div>
      </DialogContent>
      <DialogActions>
        <button
          type="button"
          className="sb-btn sb-btn-ghost"
          disabled={pending}
          onClick={onClose}
        >
          Avbryt
        </button>
        <button
          type="button"
          className="sb-btn"
          disabled={pending || !form.first_name || !form.last_name || !postalOk}
          onClick={submit}
        >
          {pending ? "Skapar..." : "Skapa"}
        </button>
      </DialogActions>
    </Dialog>
  );
}
