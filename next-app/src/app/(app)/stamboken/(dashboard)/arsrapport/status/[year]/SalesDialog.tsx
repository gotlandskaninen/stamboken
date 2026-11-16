"use client";

import { useEffect, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormLabel,
  Radio,
  RadioGroup,
  TextField,
} from "@mui/material";
import type { Mode } from "@/lib/mode";
import type { ActionResult } from "../../../inkorg/actions";
import { approveSale, rejectSale, saleProposals } from "../../actions";
import { fmtDate, type SaleProposalRow } from "../../lib";
import inkorg from "../../../inkorg/inkorg.module.css";

type Then = "kvar" | "valj_igen";

// "Försäljningar" (5.9): the herd's pending sale proposals, each approved, or
// rejected with a reason and what happens to the rabbit.
export function SalesDialog({
  herd,
  year,
  env,
  onDecided,
  onClose,
}: {
  herd: string;
  year: number;
  env: Mode;
  onDecided: () => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<SaleProposalRow[] | null>(null);
  const [version, setVersion] = useState(0); // a decision reloads the list
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [then, setThen] = useState<Then | null>(null);

  useEffect(() => {
    let cancelled = false;
    saleProposals(herd, year, env)
      .then((res) => {
        if (cancelled) return;
        if (res.ok) setItems(res.data.forslag);
        else setError(res.problem.detail || res.problem.title);
      })
      .catch(() => {
        if (!cancelled) setError("Det gick inte att nå servern. Försök igen.");
      });
    return () => {
      cancelled = true;
    };
  }, [herd, year, env, version]);

  async function decide(action: () => Promise<ActionResult<unknown>>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await action();
      if (!res.ok) {
        setError(res.problem.detail || res.problem.title);
        return;
      }
      setRejecting(null);
      setVersion((v) => v + 1);
      onDecided();
    } catch {
      setError("Det gick inte att nå servern. Försök igen.");
    } finally {
      setBusy(false);
    }
  }

  const startReject = (id: number) => {
    setRejecting(rejecting === id ? null : id);
    setReason("");
    setThen(null);
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>Försäljningar från {herd}</DialogTitle>
      <DialogContent>
        {error && (
          <p role="alert" className={inkorg.error}>
            {error}
          </p>
        )}
        {items === null && !error && <p className={inkorg.muted}>Hämtar …</p>}
        {items?.length === 0 && (
          <p className={inkorg.muted}>Inga försäljningar väntar.</p>
        )}
        {items?.map((p) => (
          <section
            key={p.id}
            aria-label={p.number}
            style={{ marginBottom: 16 }}
          >
            <p style={{ margin: "8px 0 4px" }}>
              <strong>
                {p.number}
                {p.name ? ` ${p.name}` : ""}
              </strong>
              {" · "}
              {p.to_herd
                ? `till ${p.to_herd}`
                : `utanför genbanken, ${[p.buyer?.name, p.buyer?.town].filter(Boolean).join(", ")}`}
              {" · "}
              {fmtDate(p.sale_date)}
            </p>
            {p.buyer_notified_at && (
              <p className={inkorg.muted} style={{ margin: "0 0 4px" }}>
                Köparen har anmält köpet
              </p>
            )}
            <div className={inkorg.rowActions}>
              <Button
                variant="contained"
                size="small"
                disabled={busy}
                onClick={() => decide(() => approveSale(p.id, env))}
              >
                Godkänn
              </Button>
              <Button
                variant="outlined"
                size="small"
                disabled={busy}
                aria-expanded={rejecting === p.id}
                onClick={() => startReject(p.id)}
              >
                Avvisa …
              </Button>
            </div>
            {rejecting === p.id && (
              <div style={{ marginTop: 8 }}>
                <TextField
                  fullWidth
                  multiline
                  minRows={2}
                  size="small"
                  required
                  label="Orsak"
                  helperText="Medlemmen får orsaken i ett mejl. Skriv inte köparens namn."
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <FormControl sx={{ mt: 1 }}>
                  <FormLabel id={`then-${p.id}`}>Kaninen</FormLabel>
                  <RadioGroup
                    aria-labelledby={`then-${p.id}`}
                    value={then ?? ""}
                    onChange={(e) => setThen(e.target.value as Then)}
                  >
                    <FormControlLabel
                      value="kvar"
                      control={<Radio />}
                      label="Finns kvar 31 december"
                    />
                    <FormControlLabel
                      value="valj_igen"
                      control={<Radio />}
                      label="Låt medlemmen välja igen"
                    />
                  </RadioGroup>
                </FormControl>
                <div>
                  <Button
                    variant="contained"
                    color="error"
                    size="small"
                    disabled={busy || !reason.trim() || then === null}
                    onClick={() =>
                      then && decide(() => rejectSale(p.id, reason, then, env))
                    }
                  >
                    Avvisa
                  </Button>
                </div>
              </div>
            )}
          </section>
        ))}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} variant="outlined" disabled={busy}>
          Stäng
        </Button>
      </DialogActions>
    </Dialog>
  );
}
