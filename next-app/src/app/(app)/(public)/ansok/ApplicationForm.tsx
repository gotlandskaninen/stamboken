"use client";

import { useState, useTransition } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  Link,
  TextField,
} from "@mui/material";
import { formatPostalCode, isValidPostalCode } from "@/lib/postal";
import { MEMBERSHIP_PAYMENT } from "@/components/public/MembershipSteps";
import { submitApplication } from "./actions";
import styles from "./ApplicationForm.module.css";

const EMPTY_BILLING = {
  billing_name: "",
  billing_address: "",
  billing_postal_code: "",
  billing_city: "",
  billing_email: "",
  billing_reference: "",
};

export function ApplicationForm() {
  const [pending, startTransition] = useTransition();
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    address: "",
    postal_code: "",
    city: "",
    motivation: "",
    gdpr_consent: false,
  });
  // Unticking keeps what was typed, so ticking again brings it back, but only
  // a ticked box sends the billing fields.
  const [billingOn, setBillingOn] = useState(false);
  const [billing, setBilling] = useState(EMPTY_BILLING);
  const billingPostalOk =
    !billingOn || isValidPostalCode(billing.billing_postal_code);

  if (submitted) {
    return (
      <Alert severity="success" sx={{ mt: 2 }}>
        Tack för din ansökan! Föreningen kontaktar dig när den har behandlats.{" "}
        {MEMBERSHIP_PAYMENT}
      </Alert>
    );
  }

  return (
    <Box
      component="form"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        startTransition(async () => {
          const result = await submitApplication(
            billingOn ? { ...form, ...billing } : form,
          );
          if (result.ok) setSubmitted(true);
          else setError(result.error);
        });
      }}
      sx={{ display: "flex", flexDirection: "column", gap: 2 }}
    >
      <TextField
        required
        label="Förnamn"
        value={form.first_name}
        onChange={(e) => setForm({ ...form, first_name: e.target.value })}
      />
      <TextField
        required
        label="Efternamn"
        value={form.last_name}
        onChange={(e) => setForm({ ...form, last_name: e.target.value })}
      />
      <TextField
        required
        type="email"
        label="E-post"
        value={form.email}
        onChange={(e) => setForm({ ...form, email: e.target.value })}
      />
      <TextField
        label="Telefon (valfritt)"
        value={form.phone}
        onChange={(e) => setForm({ ...form, phone: e.target.value })}
      />
      <TextField
        label="Gatuadress (valfritt)"
        value={form.address}
        onChange={(e) => setForm({ ...form, address: e.target.value })}
      />
      <TextField
        label="Postnummer (valfritt)"
        value={form.postal_code}
        onChange={(e) => setForm({ ...form, postal_code: e.target.value })}
        onBlur={() =>
          setForm((f) => ({
            ...f,
            postal_code: formatPostalCode(f.postal_code),
          }))
        }
        error={!isValidPostalCode(form.postal_code)}
        helperText={
          isValidPostalCode(form.postal_code)
            ? "5 siffror"
            : "Postnummer ska vara fem siffror"
        }
        slotProps={{ htmlInput: { inputMode: "numeric", maxLength: 6 } }}
      />
      <TextField
        label="Postort (valfritt)"
        value={form.city}
        onChange={(e) => setForm({ ...form, city: e.target.value })}
        slotProps={{ htmlInput: { maxLength: 100 } }}
      />
      <FormControlLabel
        control={
          <Checkbox
            checked={billingOn}
            onChange={(e) => setBillingOn(e.target.checked)}
          />
        }
        label="Fakturan ska till en annan adress (t.ex. djurpark, förening eller företag)"
      />
      {billingOn ? (
        <div className={styles.billing}>
          <TextField
            label="Fakturamottagare"
            helperText="Person, förening eller företag"
            value={billing.billing_name}
            onChange={(e) =>
              setBilling({ ...billing, billing_name: e.target.value })
            }
            slotProps={{ htmlInput: { maxLength: 200 } }}
          />
          <TextField
            label="Fakturaadress"
            value={billing.billing_address}
            onChange={(e) =>
              setBilling({ ...billing, billing_address: e.target.value })
            }
          />
          <TextField
            label="Fakturapostnummer"
            value={billing.billing_postal_code}
            onChange={(e) =>
              setBilling({ ...billing, billing_postal_code: e.target.value })
            }
            onBlur={() =>
              setBilling((b) => ({
                ...b,
                billing_postal_code: formatPostalCode(b.billing_postal_code),
              }))
            }
            error={!billingPostalOk}
            helperText={
              billingPostalOk ? "5 siffror" : "Postnummer ska vara fem siffror"
            }
            slotProps={{ htmlInput: { inputMode: "numeric", maxLength: 6 } }}
          />
          <TextField
            label="Fakturapostort"
            value={billing.billing_city}
            onChange={(e) =>
              setBilling({ ...billing, billing_city: e.target.value })
            }
            slotProps={{ htmlInput: { maxLength: 100 } }}
          />
          <TextField
            type="email"
            label="E-post för faktura (valfritt)"
            value={billing.billing_email}
            onChange={(e) =>
              setBilling({ ...billing, billing_email: e.target.value })
            }
            slotProps={{ htmlInput: { maxLength: 255 } }}
          />
          <TextField
            label="Fakturareferens (valfritt)"
            helperText="T.ex. Er referens eller kostnadsställe"
            value={billing.billing_reference}
            onChange={(e) =>
              setBilling({ ...billing, billing_reference: e.target.value })
            }
            slotProps={{ htmlInput: { maxLength: 100 } }}
          />
        </div>
      ) : null}
      <TextField
        multiline
        minRows={3}
        label="Berätta kort om dig själv (valfritt)"
        value={form.motivation}
        onChange={(e) => setForm({ ...form, motivation: e.target.value })}
      />
      <FormControlLabel
        control={
          <Checkbox
            required
            checked={form.gdpr_consent}
            onChange={(e) =>
              setForm({ ...form, gdpr_consent: e.target.checked })
            }
          />
        }
        label={
          <>
            Jag godkänner att mina personuppgifter behandlas enligt GDPR. Läs{" "}
            {/* New tab: following the link must not discard a filled-in form. */}
            <Link
              href="/integritetspolicy"
              target="_blank"
              rel="noopener"
              sx={{
                "@media (pointer: coarse)": {
                  display: "inline-block",
                  minHeight: 44,
                  lineHeight: "44px",
                },
              }}
            >
              integritetspolicyn
            </Link>
            .
          </>
        }
      />
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Button
        type="submit"
        variant="contained"
        disabled={
          pending ||
          !form.gdpr_consent ||
          !isValidPostalCode(form.postal_code) ||
          !billingPostalOk
        }
      >
        {pending ? "Skickar..." : "Skicka ansökan"}
      </Button>
    </Box>
  );
}
