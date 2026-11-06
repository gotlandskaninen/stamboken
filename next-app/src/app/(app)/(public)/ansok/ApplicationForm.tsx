"use client";

import { useState, useTransition } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  TextField,
} from "@mui/material";
import { formatPostalCode, isValidPostalCode } from "@/lib/postal";
import { submitApplication } from "./actions";

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

  if (submitted) {
    return (
      <Alert severity="success" sx={{ mt: 2 }}>
        Tack för din ansökan! Föreningen kontaktar dig när den har behandlats.
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
          const result = await submitApplication(form);
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
        label="Jag godkänner att mina personuppgifter behandlas enligt GDPR"
      />
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Button
        type="submit"
        variant="contained"
        disabled={
          pending || !form.gdpr_consent || !isValidPostalCode(form.postal_code)
        }
      >
        {pending ? "Skickar..." : "Skicka ansökan"}
      </Button>
    </Box>
  );
}
