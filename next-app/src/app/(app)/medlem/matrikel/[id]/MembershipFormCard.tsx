"use client";

import { useState, useTransition } from "react";
import { Checkbox, FormControlLabel, MenuItem, Select } from "@mui/material";
import { ConfirmDialog } from "@/app/(app)/stamboken/(dashboard)/admin/_components/ConfirmDialog";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { formatPostalCode, isValidPostalCode } from "@/lib/postal";
import { retireMembership, updateMembership } from "../actions";
import type { MembershipPatch } from "../actions";
import { BILLING_KEYS, hasBillingAddress } from "../types";
import type { BillingAddress, MembershipDetail } from "../types";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../medlem.module.css";

type BillingForm = Record<keyof BillingAddress, string>;

const toBillingForm = (m: BillingAddress) =>
  Object.fromEntries(BILLING_KEYS.map((k) => [k, m[k] ?? ""])) as BillingForm;

export function MembershipFormCard({
  membership,
}: {
  membership: MembershipDetail;
}) {
  const [pending, startTransition] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();

  const [status, setStatus] = useState(membership.membership_status);
  const [memberNumber, setMemberNumber] = useState(
    membership.member_number?.toString() ?? "",
  );
  const [address, setAddress] = useState(membership.address ?? "");
  const [postalCode, setPostalCode] = useState(membership.postal_code ?? "");
  const [city, setCity] = useState(membership.city ?? "");
  const [paymentNote, setPaymentNote] = useState(membership.payment_note ?? "");
  const [notes, setNotes] = useState(membership.notes ?? "");
  // The checkbox is the source of truth: unticked saves an empty billing
  // address (the invoice goes to the postal address), ticked saves the fields.
  const [billingOn, setBillingOn] = useState(hasBillingAddress(membership));
  const [billing, setBilling] = useState(() => toBillingForm(membership));
  const setBillingField = (key: keyof BillingAddress, value: string) =>
    setBilling((b) => ({ ...b, [key]: value }));
  const [retireOpen, setRetireOpen] = useState(false);
  // Set on a confirmed retire: the Avsluta button must vanish at once, not
  // when the revalidated prop arrives — a second click in that window wrote
  // another membership_retired audit row.
  const [retired, setRetired] = useState(false);
  const postalOk = isValidPostalCode(postalCode);
  const billingPostalOk =
    !billingOn || isValidPostalCode(billing.billing_postal_code);
  // Medlemsnummer is free text (artboard:185): empty means "leave it alone",
  // anything else must parse to a positive integer — the API's own rule. Gate
  // Spara on it instead of dropping the key, which would silently discard the
  // edit behind a "Medlemskapet sparat" snackbar.
  const parsedNumber = memberNumber.trim() === "" ? null : Number(memberNumber);
  const numberOk =
    parsedNumber === null ||
    (Number.isInteger(parsedNumber) && parsedNumber > 0);

  const run = (
    fn: () => Promise<{ ok: true } | { ok: false; error: string }>,
    errorTitle: string,
    success: string,
  ) => {
    startTransition(async () => {
      const result = await fn();
      if (!result.ok) {
        showSnackbar(result.error, "error");
        addNotification({
          title: errorTitle,
          message: result.error,
          type: "error",
        });
        return;
      }
      showSnackbar(success, "success");
      setRetireOpen(false);
    });
  };

  const saveMembership = () => {
    const patch: MembershipPatch = {
      ...(Object.fromEntries(
        BILLING_KEYS.map((k) => [k, billingOn ? billing[k] || null : null]),
      ) as BillingAddress),
      membership_status: status,
      address: address || null,
      postal_code: postalCode || null,
      city: city || null,
      payment_note: paymentNote || null,
      notes: notes || null,
    };
    if (parsedNumber !== null && parsedNumber !== membership.member_number) {
      patch.member_number = parsedNumber;
    }
    run(
      () => updateMembership(membership.id, patch),
      "Kunde inte spara medlemskapet",
      "Medlemskapet sparat",
    );
  };

  return (
    <section className="sb-card">
      <div className={ds["ad-card-head"]}>
        <h3 className={`sb-h6 ${ds["ad-card-title"]}`}>Medlemskap</h3>
      </div>
      <div className={ds["ad-card-body"]}>
        {/* Artboard matrikel-koppla-konto.html:182 — samma .ad-form men 640px. */}
        <div className={`${ds["ad-form"]} ${styles.formWide}`}>
          <div className={ds["ad-form-row"]}>
            <div>
              <span className="sb-label" id="ms-status-label">
                Status
              </span>
              <Select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                aria-labelledby="ms-status-label"
                size="small"
                fullWidth
              >
                <MenuItem value="active">Aktiv</MenuItem>
                <MenuItem value="inactive">Inaktiv</MenuItem>
                <MenuItem value="pending">Väntar</MenuItem>
                <MenuItem value="friexemplar">Friexemplar</MenuItem>
              </Select>
            </div>
            <div>
              <label className="sb-label" htmlFor="ms-number">
                Medlemsnummer
              </label>
              <input
                id="ms-number"
                className={`sb-input ${styles.mono} ${numberOk ? "" : ds["ad-input-error"]}`}
                type="text"
                inputMode="numeric"
                value={memberNumber}
                onChange={(e) => setMemberNumber(e.target.value)}
              />
              {numberOk ? null : (
                <p className={ds["ad-field-error"]}>
                  Medlemsnummer ska vara ett heltal större än 0
                </p>
              )}
            </div>
          </div>
          <p className={ds["ad-field-hint"]}>
            Ändringar auditloggas; ett nummer över märket höjer räknaren.
          </p>
          <div>
            <label className="sb-label" htmlFor="ms-address">
              Gatuadress
            </label>
            <input
              id="ms-address"
              className="sb-input"
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </div>
          {/* Artboard:188 — postnummer 140px fast, postort tar resten. */}
          <div className={`${ds["ad-form-row"]} ${styles.postalRow}`}>
            <div className={styles.postalCode}>
              <label className="sb-label" htmlFor="ms-postal-code">
                Postnummer
              </label>
              <input
                id="ms-postal-code"
                className={`sb-input ${styles.mono} ${postalOk ? "" : ds["ad-input-error"]}`}
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={postalCode}
                onChange={(e) => setPostalCode(e.target.value)}
                onBlur={() => setPostalCode((c) => formatPostalCode(c))}
              />
              <p
                className={
                  postalOk ? ds["ad-field-hint"] : ds["ad-field-error"]
                }
              >
                {postalOk ? "5 siffror" : "Postnummer ska vara fem siffror"}
              </p>
            </div>
            <div className={styles.postalCity}>
              <label className="sb-label" htmlFor="ms-city">
                Postort
              </label>
              <input
                id="ms-city"
                className="sb-input"
                type="text"
                maxLength={100}
                value={city}
                onChange={(e) => setCity(e.target.value)}
              />
            </div>
          </div>
          <FormControlLabel
            control={
              <Checkbox
                checked={billingOn}
                onChange={(e) => setBillingOn(e.target.checked)}
              />
            }
            label="Annan fakturaadress"
          />
          {billingOn ? (
            <div className={styles.billing}>
              <div>
                <label className="sb-label" htmlFor="ms-billing-name">
                  Fakturamottagare
                </label>
                <input
                  id="ms-billing-name"
                  className="sb-input"
                  type="text"
                  maxLength={200}
                  value={billing.billing_name}
                  onChange={(e) =>
                    setBillingField("billing_name", e.target.value)
                  }
                />
                <p className={ds["ad-field-hint"]}>
                  Person, förening eller företag
                </p>
              </div>
              <div>
                <label className="sb-label" htmlFor="ms-billing-address">
                  Fakturaadress
                </label>
                <input
                  id="ms-billing-address"
                  className="sb-input"
                  type="text"
                  value={billing.billing_address}
                  onChange={(e) =>
                    setBillingField("billing_address", e.target.value)
                  }
                />
              </div>
              <div className={`${ds["ad-form-row"]} ${styles.postalRow}`}>
                <div className={styles.postalCode}>
                  <label className="sb-label" htmlFor="ms-billing-postal-code">
                    Fakturapostnummer
                  </label>
                  <input
                    id="ms-billing-postal-code"
                    className={`sb-input ${styles.mono} ${billingPostalOk ? "" : ds["ad-input-error"]}`}
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={billing.billing_postal_code}
                    onChange={(e) =>
                      setBillingField("billing_postal_code", e.target.value)
                    }
                    onBlur={() =>
                      setBillingField(
                        "billing_postal_code",
                        formatPostalCode(billing.billing_postal_code),
                      )
                    }
                  />
                  <p
                    className={
                      billingPostalOk
                        ? ds["ad-field-hint"]
                        : ds["ad-field-error"]
                    }
                  >
                    {billingPostalOk
                      ? "5 siffror"
                      : "Postnummer ska vara fem siffror"}
                  </p>
                </div>
                <div className={styles.postalCity}>
                  <label className="sb-label" htmlFor="ms-billing-city">
                    Fakturapostort
                  </label>
                  <input
                    id="ms-billing-city"
                    className="sb-input"
                    type="text"
                    maxLength={100}
                    value={billing.billing_city}
                    onChange={(e) =>
                      setBillingField("billing_city", e.target.value)
                    }
                  />
                </div>
              </div>
              <div>
                <label className="sb-label" htmlFor="ms-billing-email">
                  E-post för faktura
                </label>
                <input
                  id="ms-billing-email"
                  className="sb-input"
                  type="email"
                  maxLength={255}
                  value={billing.billing_email}
                  onChange={(e) =>
                    setBillingField("billing_email", e.target.value)
                  }
                />
              </div>
              <div>
                <label className="sb-label" htmlFor="ms-billing-reference">
                  Fakturareferens
                </label>
                <input
                  id="ms-billing-reference"
                  className="sb-input"
                  type="text"
                  maxLength={100}
                  value={billing.billing_reference}
                  onChange={(e) =>
                    setBillingField("billing_reference", e.target.value)
                  }
                />
                <p className={ds["ad-field-hint"]}>
                  T.ex. Er referens eller kostnadsställe
                </p>
              </div>
            </div>
          ) : (
            <p className={ds["ad-field-hint"]}>
              {hasBillingAddress(membership)
                ? "Fakturaadressen tas bort när du sparar."
                : "Fakturan går till postadressen."}
            </p>
          )}
          <div>
            <label className="sb-label" htmlFor="ms-payment-note">
              Betalningsnotering
            </label>
            <input
              id="ms-payment-note"
              className="sb-input"
              type="text"
              value={paymentNote}
              onChange={(e) => setPaymentNote(e.target.value)}
            />
          </div>
          <div>
            <label className="sb-label" htmlFor="ms-notes">
              Anteckningar
            </label>
            <textarea
              id="ms-notes"
              className={`sb-input ${styles.notes}`}
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <div className={ds["ad-form-actions"]}>
            <button
              type="button"
              className="sb-btn"
              onClick={saveMembership}
              disabled={pending || !postalOk || !billingPostalOk || !numberOk}
            >
              {pending ? "Sparar..." : "Spara"}
            </button>
            {membership.membership_status !== "inactive" && !retired ? (
              <button
                type="button"
                className={`sb-btn ${ds["ad-btn-danger"]}`}
                disabled={pending}
                onClick={() => setRetireOpen(true)}
              >
                Avsluta medlemskap
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={retireOpen}
        title="Avsluta medlemskap?"
        body={
          "Medlemskapet sätts till inaktivt, alla personer avslutas och " +
          "deras åtkomster återkallas. Detta går inte att ångra automatiskt."
        }
        confirmLabel="Bekräfta"
        confirmColor="error"
        busy={pending}
        onConfirm={() =>
          run(
            async () => {
              const result = await retireMembership(membership.id);
              // The RSC page revalidates, but useState never re-reads its
              // initial prop — without this the Status select keeps the
              // pre-retire value and the next Spara would PATCH it back.
              if (result.ok) {
                setStatus("inactive");
                setRetired(true);
              }
              return result;
            },
            "Kunde inte avsluta medlemskapet",
            "Medlemskapet avslutat",
          )
        }
        onClose={() => setRetireOpen(false)}
      />
    </section>
  );
}
