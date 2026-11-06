"use client";

import { useState, useTransition } from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
} from "@mui/material";
import {
  addMyPerson,
  createMyGrant,
  removeMyPerson,
  renewMyGrant,
  revokeMyGrant,
} from "./actions";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { ROLE_LABELS } from "./types";
import type { MyGrant, MyHerd, MyPerson } from "./types";
import styles from "./profil.module.css";

const EMPTY_FORM = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  role: "familjemedlem" as "familjemedlem" | "skotare",
};

function grantChip(g: MyGrant): { label: string; className: string } {
  if (g.revoked_at) {
    return { label: `${g.herd}: återkallad`, className: "" };
  }
  const today = new Date().toISOString().slice(0, 10);
  if (g.valid_until && g.valid_until < today) {
    return {
      label: `${g.herd}: utgången ${g.valid_until}`,
      className: styles.badgeWarning,
    };
  }
  return {
    label: g.valid_until ? `${g.herd} t.o.m. ${g.valid_until}` : g.herd,
    className: "sb-badge-mossa",
  };
}

export function PersonerClient({
  isMainMember,
  persons,
  herds,
}: {
  isMainMember: boolean;
  persons: MyPerson[];
  herds: MyHerd[];
}) {
  const [pending, startTransition] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [grantPerson, setGrantPerson] = useState<MyPerson | null>(null);
  const [grantHerd, setGrantHerd] = useState<number | "">("");
  const [personToRemove, setPersonToRemove] = useState<MyPerson | null>(null);

  const notify = (
    message: string,
    type: "error" | "warning",
    title: string,
  ) => {
    showSnackbar(message, type);
    addNotification({ title, message, type });
  };

  const handleAdd = () => {
    startTransition(async () => {
      const result = await addMyPerson({
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        email: form.email.trim() || undefined,
        phone: form.phone.trim() || undefined,
        role: form.role,
      });
      if (result.ok) {
        setAddOpen(false);
        setForm(EMPTY_FORM);
        if (result.duplicateEmail) {
          notify(
            "Personen är tillagd, men e-postadressen används redan av en annan aktiv person.",
            "warning",
            "Dubblett av e-postadress",
          );
        } else {
          showSnackbar("Person tillagd", "success");
        }
      } else {
        notify(result.error, "error", "Kunde inte lägga till personen");
      }
    });
  };

  const handleGrant = () => {
    if (!grantPerson || grantHerd === "") return;
    startTransition(async () => {
      const result = await createMyGrant(grantPerson.id, grantHerd);
      if (result.ok) {
        setGrantPerson(null);
        setGrantHerd("");
        showSnackbar("Åtkomst beviljad", "success");
      } else {
        notify(result.error, "error", "Kunde inte ge åtkomst");
      }
    });
  };

  const handleRenew = (grantId: number) => {
    startTransition(async () => {
      const result = await renewMyGrant(grantId);
      if (result.ok) {
        showSnackbar("Åtkomst förnyad", "success");
      } else {
        notify(result.error, "error", "Kunde inte förnya åtkomsten");
      }
    });
  };

  const handleRevoke = (grantId: number) => {
    startTransition(async () => {
      const result = await revokeMyGrant(grantId);
      if (result.ok) {
        showSnackbar("Åtkomst återkallad", "success");
      } else {
        notify(result.error, "error", "Kunde inte återkalla åtkomsten");
      }
    });
  };

  const handleRemove = () => {
    if (!personToRemove) return;
    startTransition(async () => {
      const result = await removeMyPerson(personToRemove.id);
      setPersonToRemove(null);
      if (result.ok) {
        showSnackbar("Person borttagen", "success");
      } else {
        notify(result.error, "error", "Kunde inte ta bort personen");
      }
    });
  };

  return (
    <section className="sb-card">
      <div className={styles.cardHead}>
        <h3 className={`sb-h6 ${styles.cardTitle}`}>Personer i medlemskapet</h3>
        {isMainMember && (
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            disabled={pending}
            onClick={() => setAddOpen(true)}
          >
            Lägg till person
          </button>
        )}
      </div>
      <table className={styles.tbl}>
        <thead>
          <tr>
            <th>Namn</th>
            <th>Roll</th>
            <th>Besättningsåtkomst</th>
            <th className={styles.r} />
          </tr>
        </thead>
        <tbody>
          {persons.map((p) => (
            <tr key={p.id}>
              <td data-label="Namn">
                {p.first_name} {p.last_name}
              </td>
              <td data-label="Roll">{ROLE_LABELS[p.role]}</td>
              <td data-label="Besättningsåtkomst">
                <div className={styles.grantList}>
                  {p.grants.map((g) => {
                    const chip = grantChip(g);
                    return (
                      <span key={g.id} className={styles.grant}>
                        <span className={`sb-badge ${chip.className}`}>
                          {chip.label}
                        </span>
                        {!g.revoked_at && g.valid_until && isMainMember && (
                          <button
                            type="button"
                            className={`sb-btn sb-btn-ghost ${styles.btnXs}`}
                            disabled={pending}
                            onClick={() => handleRenew(g.id)}
                          >
                            Förnya
                          </button>
                        )}
                        {!g.revoked_at && isMainMember && (
                          <button
                            type="button"
                            className={`sb-btn ${styles.btnDanger} ${styles.btnXs}`}
                            disabled={pending}
                            onClick={() => handleRevoke(g.id)}
                          >
                            Återkalla
                          </button>
                        )}
                      </span>
                    );
                  })}
                </div>
              </td>
              <td className={styles.r}>
                {isMainMember && (
                  <div className={styles.cellActions}>
                    {herds.length > 0 && (
                      <button
                        type="button"
                        className={`sb-btn sb-btn-ghost ${styles.btnXs}`}
                        disabled={pending}
                        onClick={() => {
                          setGrantPerson(p);
                          setGrantHerd(herds.length === 1 ? herds[0].id : "");
                        }}
                      >
                        Ge åtkomst
                      </button>
                    )}
                    {p.role !== "huvudmedlem" && (
                      <button
                        type="button"
                        className={`sb-btn ${styles.btnDanger} ${styles.btnXs}`}
                        disabled={pending}
                        onClick={() => setPersonToRemove(p)}
                      >
                        Ta bort
                      </button>
                    )}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!isMainMember && (
        <p className={`${styles.hint} ${styles.tblFoot}`}>
          Kontakta huvudmedlemmen för ändringar av medlemskapet.
        </p>
      )}

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} fullWidth>
        <DialogTitle>Lägg till person</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 2 }}>
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
              type="email"
              label="E-post"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
            <TextField
              label="Telefon"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
            <TextField
              select
              label="Roll"
              value={form.role}
              onChange={(e) =>
                setForm({
                  ...form,
                  role: e.target.value as "familjemedlem" | "skotare",
                })
              }
              helperText="Skötare får tidsbegränsad åtkomst (1 år, förnybar); familjemedlemmar utan tidsgräns."
            >
              <MenuItem value="familjemedlem">Familjemedlem</MenuItem>
              <MenuItem value="skotare">Skötare</MenuItem>
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <button
            type="button"
            className="sb-btn sb-btn-ghost"
            onClick={() => setAddOpen(false)}
          >
            Avbryt
          </button>
          <button
            type="button"
            className="sb-btn"
            disabled={
              pending || !form.first_name.trim() || !form.last_name.trim()
            }
            onClick={handleAdd}
          >
            Lägg till
          </button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={grantPerson !== null}
        onClose={() => setGrantPerson(null)}
        fullWidth
      >
        <DialogTitle>Ge besättningsåtkomst</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {grantPerson
              ? `${grantPerson.first_name} ${grantPerson.last_name} får redigera vald besättning.`
              : ""}
          </DialogContentText>
          <TextField
            select
            fullWidth
            label="Besättning"
            value={grantHerd}
            onChange={(e) => setGrantHerd(Number(e.target.value))}
            sx={{ mt: 2 }}
          >
            {herds.map((h) => (
              <MenuItem key={h.id} value={h.id}>
                {h.herd}
                {h.herd_name ? ` — ${h.herd_name}` : ""}
              </MenuItem>
            ))}
          </TextField>
        </DialogContent>
        <DialogActions>
          <button
            type="button"
            className="sb-btn sb-btn-ghost"
            onClick={() => setGrantPerson(null)}
          >
            Avbryt
          </button>
          <button
            type="button"
            className="sb-btn"
            disabled={pending || grantHerd === ""}
            onClick={handleGrant}
          >
            Ge åtkomst
          </button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={personToRemove !== null}
        onClose={() => setPersonToRemove(null)}
      >
        <DialogTitle>Ta bort person?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {personToRemove
              ? `${personToRemove.first_name} ${personToRemove.last_name} tas bort från medlemskapet och all besättningsåtkomst återkallas.`
              : ""}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <button
            type="button"
            className="sb-btn sb-btn-ghost"
            onClick={() => setPersonToRemove(null)}
          >
            Avbryt
          </button>
          <button
            type="button"
            className={`sb-btn ${styles.btnDanger}`}
            disabled={pending}
            onClick={handleRemove}
          >
            Ta bort
          </button>
        </DialogActions>
      </Dialog>
    </section>
  );
}
