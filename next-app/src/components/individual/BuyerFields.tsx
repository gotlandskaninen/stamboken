"use client";

import React from "react";
import { Box, Checkbox, FormControlLabel, TextField } from "@mui/material";
import { useTranslation } from "react-i18next";

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

export const buyerComplete = (d: BuyerDraft) =>
  !!d.name.trim() && !!d.town.trim();

/** Only what the buyer said yes to: a field hidden by an unticked box is never sent. */
export function buyerPayload(d: BuyerDraft): SaleBuyer {
  const kept = (field: "postal_address" | "email" | "phone", ok: boolean) =>
    ok && d[field].trim() ? { [field]: d[field].trim() } : {};
  const contactAllowed = d.contact_consent || d.membership_optin;
  return {
    name: d.name.trim(),
    town: d.town.trim(),
    contact_consent: d.contact_consent,
    membership_optin: d.membership_optin,
    ...kept("postal_address", d.contact_consent),
    ...kept("email", contactAllowed),
    ...kept("phone", contactAllowed),
  };
}

/** Name and town, the buyer's two yeses and the contact details they allow, and the proof note. */
export function BuyerFields({
  value,
  onChange,
  size,
}: {
  value: BuyerDraft;
  onChange: (value: BuyerDraft) => void;
  size?: "small" | "medium";
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
      data-testid="sell-buyer"
    >
      {field("name", t("individual.sell.buyerName"), true)}
      {field("town", t("individual.sell.buyerTown"), true)}
      {box("contact_consent", t("individual.sell.buyerContactConsent"))}
      {box("membership_optin", t("individual.sell.buyerMembershipOptin"))}
      {value.contact_consent &&
        field("postal_address", t("individual.sell.buyerAddress"))}
      {(value.contact_consent || value.membership_optin) && (
        <>
          {field("email", t("individual.sell.buyerEmail"))}
          {field("phone", t("individual.sell.buyerPhone"))}
        </>
      )}
      <Box sx={{ fontSize: 13, color: "var(--sb-ink-3)" }}>
        {t("individual.sell.buyerNote")}
      </Box>
    </Box>
  );
}
