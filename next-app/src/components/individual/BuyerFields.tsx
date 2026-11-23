"use client";

import React from "react";
import { Box, Checkbox, FormControlLabel, TextField } from "@mui/material";
import { useTranslation } from "react-i18next";
import report from "@/app/(app)/stamboken/(dashboard)/arsrapport/arsrapport.module.css";

/** The buyer outside the association, sent with a sale to GX1/MX1 (ADR-0016). */
export interface SaleBuyer {
  name: string;
  town: string;
  contact_consent: boolean;
  membership_optin: boolean;
  postal_address?: string;
  email?: string;
  phone?: string;
}

export interface BuyerDraft {
  name: string;
  town: string;
  postal_address: string;
  email: string;
  phone: string;
  contact_consent: boolean;
  membership_optin: boolean;
}

export const EMPTY_BUYER: BuyerDraft = {
  name: "",
  town: "",
  postal_address: "",
  email: "",
  phone: "",
  contact_consent: false,
  membership_optin: false,
};

export const buyerComplete = (d: BuyerDraft, addressRequired = false) =>
  !!d.name.trim() &&
  !!d.town.trim() &&
  (!addressRequired || !!d.postal_address.trim());

/** E-mail and phone only with a yes: a field hidden by an unticked box is never sent. */
export function buyerPayload(d: BuyerDraft): SaleBuyer {
  const kept = (field: "postal_address" | "email" | "phone", ok: boolean) =>
    ok && d[field].trim() ? { [field]: d[field].trim() } : {};
  const contactAllowed = d.contact_consent || d.membership_optin;
  return {
    name: d.name.trim(),
    town: d.town.trim(),
    contact_consent: d.contact_consent,
    membership_optin: d.membership_optin,
    ...kept("postal_address", true),
    ...kept("email", contactAllowed),
    ...kept("phone", contactAllowed),
  };
}

/** Name, town and postal address, the buyer's two yeses and the e-mail and phone they allow, and the proof note. */
export function BuyerFields({
  value,
  onChange,
  size,
  addressRequired = false,
  errors,
  variant,
}: {
  value: BuyerDraft;
  onChange: (value: BuyerDraft) => void;
  size?: "small" | "medium";
  addressRequired?: boolean;
  /** The yearly report's member: the report's larger fields, labels above (RegisterFromCertificate's too). */
  variant?: "member";
  /** A refusal beside its field: aria-invalid, and the text as the field's description. */
  errors?: Partial<
    Record<"name" | "town" | "postal_address" | "phone" | "email", string>
  >;
}) {
  const { t } = useTranslation();
  const set = (changes: Partial<BuyerDraft>) =>
    onChange({ ...value, ...changes });
  const field = (
    key: "name" | "town" | "postal_address" | "email" | "phone",
    label: string,
    required = false,
  ) => (
    <TextField
      label={label}
      value={value[key]}
      onChange={(e) => set({ [key]: e.target.value })}
      required={required}
      error={!!errors?.[key]}
      helperText={errors?.[key]}
      fullWidth
      size={size}
      slotProps={{ htmlInput: { maxLength: 200 } }}
    />
  );
  const box = (key: "contact_consent" | "membership_optin", label: string) => (
    <FormControlLabel
      sx={{ alignItems: "flex-start", ml: 0 }}
      control={
        <Checkbox
          checked={value[key]}
          onChange={(e) => set({ [key]: e.target.checked })}
          sx={{ pt: 0.5 }}
        />
      }
      label={label}
    />
  );
  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", gap: 2 }}
      className={variant === "member" ? report.memberFields : undefined}
      data-testid="sell-buyer"
    >
      {field("name", t("individual.sell.buyerName"), true)}
      {field("town", t("individual.sell.buyerTown"), true)}
      {field(
        "postal_address",
        t("individual.sell.buyerAddress"),
        addressRequired,
      )}
      {box("contact_consent", t("individual.sell.buyerContactConsent"))}
      {box("membership_optin", t("individual.sell.buyerMembershipOptin"))}
      {(value.contact_consent || value.membership_optin) && (
        <>
          {field("email", t("individual.sell.buyerEmail"))}
          {field("phone", t("individual.sell.buyerPhone"))}
        </>
      )}
      <Box
        sx={{
          fontSize: variant === "member" ? 15 : 13,
          color: variant === "member" ? "var(--sb-ink-2)" : "var(--sb-ink-3)",
        }}
      >
        {t("individual.sell.buyerNote")}
      </Box>
    </Box>
  );
}
