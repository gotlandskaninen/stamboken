"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";
import { grantRole, revokeRole } from "../../anvandare/actions"; // shared role actions
import {
  OwnerPickerAutocomplete,
  type UserOption,
} from "../../_components/OwnerPickerAutocomplete";
import { updateGenebank } from "../actions";

export function GenebankEditClient({
  gb,
  isAdmin,
  managers,
  userOptions,
}: {
  gb: { id: number; name: string };
  isAdmin: boolean;
  managers: UserOption[];
  userOptions: UserOption[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState(gb.name);
  const [newManager, setNewManager] = useState<UserOption | null>(null);

  const save = () =>
    startTransition(async () => {
      setError(null);
      const result = await updateGenebank(gb.id, { name });
      if (result?.error) setError(result.error); // success redirects
    });

  const assignManager = () =>
    startTransition(async () => {
      if (!newManager) return;
      setError(null);
      const result = await grantRole(newManager.id, {
        level: "manager",
        genebank: gb.id,
      });
      if (result && "error" in result && result.error) {
        setError(result.error);
        return;
      }
      setNewManager(null);
      router.refresh(); // no-op if grantRole already redirected
    });

  const removeManager = (m: UserOption) =>
    startTransition(async () => {
      setError(null);
      const result = await revokeRole(m.id, {
        level: "manager",
        genebank: gb.id,
      });
      if (result && "error" in result && result.error) {
        setError(result.error);
        return;
      }
      router.refresh();
    });

  return (
    <section className={`sb-card ${ds["ad-form-card"]}`}>
      <div className={ds["ad-form-stack"]}>
        {error && (
          <div
            className={`${ds["ad-banner"]} ${ds["ad-banner-danger"]}`}
            role="alert"
          >
            {error}
          </div>
        )}
        <div>
          <label className="sb-label" htmlFor="gb-name">
            Namn
          </label>
          <input
            id="gb-name"
            className="sb-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className={ds["ad-form-actions"]}>
          <button
            type="button"
            className="sb-btn"
            disabled={pending}
            onClick={save}
          >
            Spara
          </button>
        </div>

        {isAdmin && (
          <>
            <hr className="sb-rule" />
            <h3 className={`sb-h6 ${ds["ad-section-title"]}`}>
              Genbanksansvariga
            </h3>
            <ul className={styles["ad-role-list"]}>
              {managers.map((m) => (
                <li key={m.id} className={styles["ad-role-row"]}>
                  <span>{m.username}</span>
                  {m.fullname && <span className="sb-meta">{m.fullname}</span>}
                  <button
                    type="button"
                    className={`sb-btn sb-btn-ghost sb-btn-sm ${ds["ad-row-end"]}`}
                    disabled={pending}
                    onClick={() => removeManager(m)}
                  >
                    Ta bort ansvar
                  </button>
                </li>
              ))}
              {managers.length === 0 && (
                <li className={styles["ad-role-row"]}>
                  Det finns inga genbanksansvariga.
                </li>
              )}
            </ul>
            <OwnerPickerAutocomplete
              users={userOptions}
              value={newManager}
              onChange={setNewManager}
              label="Ny genbanksansvarig"
              helperText="Sök efter användarnamn eller fullständigt namn."
            />
            <div className={ds["ad-form-actions"]}>
              <button
                type="button"
                className="sb-btn sb-btn-secondary"
                disabled={pending || !newManager}
                onClick={assignManager}
              >
                Lägg till genbanksansvarig
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
