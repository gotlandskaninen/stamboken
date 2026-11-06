"use client";

import { useState, useTransition } from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Menu,
  MenuItem,
  TextField,
} from "@mui/material";
import { SbIcon } from "@/components/shell/SbIcon";
import { ConfirmDialog } from "@/app/(app)/stamboken/(dashboard)/admin/_components/ConfirmDialog";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import {
  addPerson,
  anonymizePerson,
  createGrant,
  removePerson,
  renewGrant,
  revokeGrant,
  setMainMember,
  unlinkPersonUser,
  updatePerson,
} from "../actions";
import { ROLE_LABELS } from "../types";
import type { Grant, MembershipDetail, Person } from "../types";
import { KopplaKontoDialog } from "./KopplaKontoDialog";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../medlem.module.css";

/**
 * Kontaktcellen. E-postadressen sätter annars tabellens min-bredd: dess enda
 * naturliga brytpunkt är ett bindestreck, så "member@test.local" hålls ihop.
 * <wbr /> lägger till en mjuk brytpunkt framför @ — adressen bryts alltså bara
 * mellan lokaldel och domän, aldrig mitt i ett ord. Ett telefonnummer (eller
 * vad som helst utan @) renderas som det är.
 */
function contactContent(person: Person) {
  const value = person.email || person.phone;
  if (!value) return "–";
  const at = value.lastIndexOf("@");
  if (at === -1) return value;
  return (
    <>
      {value.slice(0, at)}
      <wbr />
      {value.slice(at)}
    </>
  );
}

function grantIsActive(grant: Grant, person: Person): boolean {
  if (person.end_date || grant.revoked_at) return false;
  if (grant.valid_until === null) return true;
  return grant.valid_until >= new Date().toISOString().slice(0, 10);
}

type MutationResult =
  | { ok: true }
  | { ok: true; duplicateContactEmail: boolean }
  | { ok: false; error: string };

// A mutation plus the Swedish texts its snackbar/notification uses.
type Mutation = {
  run: () => Promise<MutationResult>;
  errorTitle: string;
  success: string;
};

const EMPTY_PERSON_FORM = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  role: "familjemedlem",
};

export function PersonsCard({
  membership,
  canEdit,
}: {
  membership: MembershipDetail;
  canEdit: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();

  // Person add/edit dialog
  const [personOpen, setPersonOpen] = useState(false);
  const [editPersonId, setEditPersonId] = useState<number | null>(null);
  const [personForm, setPersonForm] = useState(EMPTY_PERSON_FORM);

  // Grant dialog
  const [grantPerson, setGrantPerson] = useState<Person | null>(null);
  const [grantHerd, setGrantHerd] = useState<number | "">("");
  const [grantValidUntil, setGrantValidUntil] = useState("");

  // Koppla användarkonto dialog
  const [linkPerson, setLinkPerson] = useState<Person | null>(null);

  // Radmenyn ⋯ "Fler åtgärder" — allt utom Redigera bor här så att
  // Åtgärder-kolumnen är två kontroller bred i stället för fem staplade.
  const [menu, setMenu] = useState<{
    anchor: HTMLElement;
    person: Person;
  } | null>(null);
  const menuPerson = menu?.person ?? null;
  const closeMenu = () => setMenu(null);

  // Shared confirm dialog (remove / anonymize / revoke / swap main / unlink)
  const [confirm, setConfirm] = useState<
    ({ title: string; text: string } & Mutation) | null
  >(null);

  const notify = (
    message: string,
    type: "error" | "warning",
    title: string,
  ) => {
    showSnackbar(message, type);
    addNotification({ title, message, type });
  };

  const run = ({ run: fn, errorTitle, success }: Mutation) => {
    startTransition(async () => {
      const result = await fn();
      if (!result.ok) {
        notify(result.error, "error", errorTitle);
        return;
      }
      if ("duplicateContactEmail" in result && result.duplicateContactEmail) {
        notify(
          "Personen sparades, men e-postadressen används redan av en annan aktiv person i matrikeln.",
          "warning",
          "Dubblett av e-postadress",
        );
      } else {
        showSnackbar(success, "success");
      }
      setPersonOpen(false);
      setGrantPerson(null);
      setConfirm(null);
    });
  };

  const openAddPerson = () => {
    setEditPersonId(null);
    setPersonForm(EMPTY_PERSON_FORM);
    setPersonOpen(true);
  };

  const openEditPerson = (p: Person) => {
    setEditPersonId(p.id);
    setPersonForm({
      first_name: p.first_name,
      last_name: p.last_name,
      email: p.email ?? "",
      phone: p.phone ?? "",
      role: p.role,
    });
    setPersonOpen(true);
  };

  const savePerson = () => {
    const payload = {
      first_name: personForm.first_name,
      last_name: personForm.last_name,
      email: personForm.email || null,
      phone: personForm.phone || null,
    };
    if (editPersonId === null) {
      run({
        run: () =>
          addPerson(membership.id, { ...payload, role: personForm.role }),
        errorTitle: "Kunde inte lägga till personen",
        success: "Person tillagd",
      });
    } else {
      run({
        run: () => updatePerson(membership.id, editPersonId, payload),
        errorTitle: "Kunde inte spara personen",
        success: "Person sparad",
      });
    }
  };

  const saveGrant = () => {
    if (!grantPerson || grantHerd === "") return;
    run({
      run: () =>
        createGrant(membership.id, grantPerson.id, {
          herd_id: grantHerd,
          ...(grantValidUntil ? { valid_until: grantValidUntil } : {}),
        }),
      errorTitle: "Kunde inte ge åtkomst",
      success: "Åtkomst beviljad",
    });
  };

  const openGrant = (p: Person) => {
    setGrantPerson(p);
    setGrantHerd(membership.herds.length === 1 ? membership.herds[0].id : "");
    setGrantValidUntil("");
  };
  const confirmSetMain = (p: Person) =>
    setConfirm({
      title: "Byt huvudmedlem?",
      text: `${p.first_name} ${p.last_name} blir ny huvudmedlem; nuvarande huvudmedlem blir familjemedlem. Bytet sker atomiskt.`,
      run: () => setMainMember(membership.id, p.id),
      errorTitle: "Kunde inte byta huvudmedlem",
      success: "Huvudmedlem bytt",
    });
  const confirmRemove = (p: Person) =>
    setConfirm({
      title: "Ta bort person?",
      text: "Personen avslutas (mjuk borttagning) och alla besättningsåtkomster återkallas i samma transaktion.",
      run: () => removePerson(membership.id, p.id),
      errorTitle: "Kunde inte ta bort personen",
      success: "Person borttagen",
    });
  const confirmAnonymize = (p: Person) =>
    setConfirm({
      title: "Anonymisera person?",
      text: "Personuppgifterna ersätts med platshållare, kontaktuppgifter tas bort, personuppgifter i auditloggen maskeras och alla åtkomster återkallas. Detta kan inte ångras.",
      run: () => anonymizePerson(membership.id, p.id),
      errorTitle: "Kunde inte anonymisera personen",
      success: "Person anonymiserad",
    });

  return (
    <section className="sb-card">
      <div className={ds["ad-card-head"]}>
        <h3 className={`sb-h6 ${ds["ad-card-title"]}`}>Personer</h3>
        {canEdit ? (
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            onClick={openAddPerson}
          >
            Lägg till person
          </button>
        ) : null}
      </div>
      <div className={styles.tblWrap}>
        <table className={styles.tbl}>
          <thead>
            <tr>
              <th>Namn</th>
              <th>Roll</th>
              <th>Kontakt</th>
              <th>Konto</th>
              <th>Åtkomster</th>
              {canEdit ? <th className={styles.r}>Åtgärder</th> : null}
            </tr>
          </thead>
          <tbody>
            {membership.persons.map((p) => (
              <tr key={p.id}>
                <td data-label="Namn">
                  {p.first_name} {p.last_name}
                  {p.end_date ? " (avslutad)" : ""}
                </td>
                <td data-label="Roll">{ROLE_LABELS[p.role] ?? p.role}</td>
                <td data-label="Kontakt">{contactContent(p)}</td>
                <td data-label="Konto">
                  {p.user ? (
                    <span className={styles.userCell}>
                      <span className={styles.mono}>
                        {p.user.username ?? p.user.email}
                      </span>
                      {canEdit && (
                        <button
                          type="button"
                          className={`sb-btn sb-btn-ghost ${styles.btnXs}`}
                          disabled={pending}
                          onClick={() =>
                            setConfirm({
                              title: "Koppla bort konto?",
                              text: "Kontot förlorar åtkomsten som medlemskapet ger. Fortsätt?",
                              run: () => unlinkPersonUser(membership.id, p.id),
                              errorTitle: "Kunde inte koppla bort kontot",
                              success: "Konto bortkopplat",
                            })
                          }
                        >
                          Koppla bort
                        </button>
                      )}
                    </span>
                  ) : p.end_date === null && canEdit ? (
                    <button
                      type="button"
                      className={`sb-btn sb-btn-secondary ${styles.btnXs}`}
                      disabled={pending}
                      onClick={() => setLinkPerson(p)}
                    >
                      Koppla konto…
                    </button>
                  ) : (
                    "—"
                  )}
                </td>
                <td data-label="Åtkomster">
                  <div className={styles.badgeRow}>
                    {p.grants.map((g) => (
                      <span key={g.id} className={styles.grant}>
                        <span
                          className={`sb-badge ${grantIsActive(g, p) ? "sb-badge-mossa" : ""}`}
                        >
                          {`${g.herd}${g.valid_until ? ` t.o.m. ${g.valid_until}` : ""}${
                            g.revoked_at ? " (återkallad)" : ""
                          }`}
                        </span>
                        {canEdit && !g.revoked_at ? (
                          <button
                            type="button"
                            className={`sb-btn ${styles.btnDanger} ${styles.btnXs}`}
                            disabled={pending}
                            onClick={() =>
                              setConfirm({
                                title: "Återkalla åtkomst?",
                                text: `Personens åtkomst till ${g.herd} återkallas direkt.`,
                                run: () => revokeGrant(membership.id, g.id),
                                errorTitle: "Kunde inte återkalla åtkomsten",
                                success: "Åtkomst återkallad",
                              })
                            }
                          >
                            Återkalla
                          </button>
                        ) : null}
                      </span>
                    ))}
                    {canEdit && p.end_date === null
                      ? p.grants
                          .filter(
                            (g) => !g.revoked_at && g.valid_until !== null,
                          )
                          .map((g) => (
                            <button
                              key={`renew-${g.id}`}
                              type="button"
                              className={`sb-btn sb-btn-ghost ${styles.btnXs}`}
                              disabled={pending}
                              onClick={() =>
                                run({
                                  run: () => renewGrant(membership.id, g.id),
                                  errorTitle: "Kunde inte förnya åtkomsten",
                                  success: "Åtkomst förnyad",
                                })
                              }
                            >
                              Förnya {g.herd}
                            </button>
                          ))
                      : null}
                  </div>
                </td>
                {canEdit ? (
                  <td className={styles.r} data-label="Åtgärder">
                    <div className={styles.rowActions}>
                      <button
                        type="button"
                        className={`sb-btn sb-btn-ghost ${styles.btnXs}`}
                        onClick={() => openEditPerson(p)}
                      >
                        Redigera
                      </button>
                      <button
                        type="button"
                        className={`sb-btn sb-btn-ghost ${styles.btnXs} ${styles.moreBtn}`}
                        aria-label={`Fler åtgärder för ${p.first_name} ${p.last_name}`}
                        aria-haspopup="menu"
                        aria-expanded={menuPerson?.id === p.id}
                        onClick={(e) =>
                          setMenu({ anchor: e.currentTarget, person: p })
                        }
                      >
                        <SbIcon name="more" size={18} />
                      </button>
                    </div>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Menu
        anchorEl={menu?.anchor ?? null}
        open={menu !== null}
        onClose={closeMenu}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
      >
        {menuPerson && menuPerson.end_date === null && (
          <MenuItem
            onClick={() => {
              closeMenu();
              openGrant(menuPerson);
            }}
          >
            Ge åtkomst
          </MenuItem>
        )}
        {menuPerson &&
          menuPerson.end_date === null &&
          menuPerson.role !== "huvudmedlem" && (
            <MenuItem
              onClick={() => {
                closeMenu();
                confirmSetMain(menuPerson);
              }}
            >
              Gör till huvudmedlem
            </MenuItem>
          )}
        {menuPerson && menuPerson.end_date === null && (
          <MenuItem
            className={styles.menuDanger}
            onClick={() => {
              closeMenu();
              confirmRemove(menuPerson);
            }}
          >
            Ta bort
          </MenuItem>
        )}
        {menuPerson && (
          <MenuItem
            className={styles.menuDanger}
            onClick={() => {
              closeMenu();
              confirmAnonymize(menuPerson);
            }}
          >
            Anonymisera
          </MenuItem>
        )}
      </Menu>

      <Dialog open={personOpen} onClose={() => setPersonOpen(false)} fullWidth>
        <DialogTitle>
          {editPersonId === null ? "Lägg till person" : "Redigera person"}
        </DialogTitle>
        <DialogContent>
          <div className={styles.dialogBody}>
            <TextField
              label="Förnamn"
              value={personForm.first_name}
              onChange={(e) =>
                setPersonForm({ ...personForm, first_name: e.target.value })
              }
            />
            <TextField
              label="Efternamn"
              value={personForm.last_name}
              onChange={(e) =>
                setPersonForm({ ...personForm, last_name: e.target.value })
              }
            />
            <TextField
              label="E-post"
              value={personForm.email}
              onChange={(e) =>
                setPersonForm({ ...personForm, email: e.target.value })
              }
            />
            <TextField
              label="Telefon"
              value={personForm.phone}
              onChange={(e) =>
                setPersonForm({ ...personForm, phone: e.target.value })
              }
            />
            {editPersonId === null ? (
              <TextField
                select
                label="Roll"
                value={personForm.role}
                onChange={(e) =>
                  setPersonForm({ ...personForm, role: e.target.value })
                }
                helperText="Huvudmedlem byts via 'Gör till huvudmedlem'."
              >
                <MenuItem value="familjemedlem">Familjemedlem</MenuItem>
                <MenuItem value="skotare">Skötare</MenuItem>
              </TextField>
            ) : null}
          </div>
        </DialogContent>
        <DialogActions>
          <button
            type="button"
            className="sb-btn sb-btn-ghost"
            onClick={() => setPersonOpen(false)}
          >
            Avbryt
          </button>
          <button
            type="button"
            className="sb-btn"
            onClick={savePerson}
            disabled={
              pending ||
              !personForm.first_name.trim() ||
              !personForm.last_name.trim()
            }
          >
            Spara
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
          <div className={styles.dialogBody}>
            <TextField
              select
              label="Besättning"
              value={grantHerd}
              onChange={(e) =>
                setGrantHerd(
                  e.target.value === "" ? "" : Number(e.target.value),
                )
              }
            >
              {membership.herds.map((h) => (
                <MenuItem key={h.id} value={h.id}>
                  {h.herd_name ? `${h.herd} — ${h.herd_name}` : h.herd}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Giltig till"
              type="date"
              value={grantValidUntil}
              onChange={(e) => setGrantValidUntil(e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
              helperText="Lämna tomt: familjemedlem gäller tills vidare, skötare får +1 år."
            />
          </div>
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
            onClick={saveGrant}
            disabled={pending || grantHerd === ""}
          >
            Ge åtkomst
          </button>
        </DialogActions>
      </Dialog>

      <KopplaKontoDialog
        open={linkPerson !== null}
        person={linkPerson}
        membershipId={membership.id}
        membershipNumber={membership.member_number}
        onClose={() => setLinkPerson(null)}
      />

      <ConfirmDialog
        open={confirm !== null}
        busy={pending}
        title={confirm?.title ?? ""}
        body={confirm?.text ?? ""}
        confirmLabel="Bekräfta"
        confirmColor="error"
        onConfirm={() => confirm && run(confirm)}
        onClose={() => setConfirm(null)}
      />
    </section>
  );
}
