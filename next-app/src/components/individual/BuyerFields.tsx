"use client";

import React from "react";
import {
  Box,
  Checkbox,
  FormControl,
  FormControlLabel,
  FormHelperText,
  FormLabel,
  Radio,
  RadioGroup,
  TextField,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import report from "@/app/(app)/stamboken/(dashboard)/arsrapport/arsrapport.module.css";
import { stockholmToday } from "@/utils/saleRules";

/**
 * The buyer outside the association, sent with a sale to GX1/MX1 (ADR-0016). Without a
 * försäljningsbevis (#273): the e-mail only for the association's notice
 * (`notice_only`), or "såld utanför genbanken" with nothing kept (`not_recorded`).
 */
export type SaleBuyer =
  | {
      name: string;
      town: string;
      contact_consent: boolean;
      membership_optin: boolean;
      postal_address?: string;
      email?: string;
      phone?: string;
    }
  | {
      name: string;
      town: string;
      postal_address: string;
      email: string;
      notice_only: true;
    }
  | { not_recorded: true };

/** bevis: the buyer got the försäljningsbevis; epost: no bevis, an e-mail; utan: såld utanför genbanken. */
export type BuyerMode = "bevis" | "epost" | "utan";

/** The choices a sale's year has (#273): the bevis from 2027, the transition until the end of 2027. */
export function buyerModes(year: number): BuyerMode[] {
  if (year < 2027) return ["epost", "utan"];
  if (year === 2027) return ["bevis", "epost", "utan"];
  return ["bevis"];
}

export interface BuyerDraft {
  mode: BuyerMode | null;
  name: string;
  town: string;
  postal_address: string;
  email: string;
  phone: string;
  contact_consent: boolean;
  membership_optin: boolean;
}

export const EMPTY_BUYER: BuyerDraft = {
  mode: null,
  name: "",
  town: "",
  postal_address: "",
  email: "",
  phone: "",
  contact_consent: false,
  membership_optin: false,
};

/** A typed sale date's year (YYYY-MM-DD), or this year in Stockholm while there is none. */
export const saleYear = (date: string | null | undefined) =>
  date && /^\d{4}-/.test(date)
    ? Number(date.slice(0, 4))
    : stockholmToday().getFullYear();

/** The draft's choice if the year has it, the only one if there is one, else none yet. */
export function buyerMode(d: BuyerDraft, year: number): BuyerMode | null {
  const modes = buyerModes(year);
  if (modes.length === 1) return modes[0];
  return d.mode && modes.includes(d.mode) ? d.mode : null;
}

/** A buyer the report or the form already holds, as a draft. */
export function buyerDraft(buyer?: SaleBuyer | null): BuyerDraft {
  if (!buyer) return EMPTY_BUYER;
  if ("not_recorded" in buyer) return { ...EMPTY_BUYER, mode: "utan" };
  if ("notice_only" in buyer)
    return { ...EMPTY_BUYER, ...buyer, mode: "epost" };
  return { ...EMPTY_BUYER, ...buyer, mode: "bevis" };
}

export function buyerComplete(
  d: BuyerDraft,
  addressRequired: boolean,
  year: number,
) {
  const mode = buyerMode(d, year);
  const named = !!d.name.trim() && !!d.town.trim();
  if (mode === "utan") return true;
  if (mode === "epost")
    return named && !!d.postal_address.trim() && !!d.email.trim();
  return (
    mode === "bevis" && named && (!addressRequired || !!d.postal_address.trim())
  );
}

/** E-mail and phone only with a yes: a field hidden by an unticked box is never sent. */
export function buyerPayload(d: BuyerDraft, year: number): SaleBuyer {
  const mode = buyerMode(d, year);
  if (mode === "utan") return { not_recorded: true };
  if (mode === "epost")
    return {
      name: d.name.trim(),
      town: d.town.trim(),
      postal_address: d.postal_address.trim(),
      email: d.email.trim(),
      notice_only: true,
    };
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

/**
 * The choice the sale's year has (#273), then its fields: with the bevis, name, town and postal
 * address, the buyer's two yeses and the e-mail and phone they allow, and the bevis note; without,
 * name, town, postal address and e-mail for the notice, or nothing.
 */
export function BuyerFields({
  value,
  onChange,
  year,
  size,
  addressRequired = false,
  errors,
  variant,
}: {
  value: BuyerDraft;
  onChange: (value: BuyerDraft) => void;
  /** The sale's year, which decides the choice. */
  year: number;
  size?: "small" | "medium";
  addressRequired?: boolean;
  /** The yearly report's member: the report's larger fields, labels above (RegisterFromCertificate's too). */
  variant?: "member";
  /** A refusal beside its field: aria-invalid, and the text as the field's description. */
  errors?: Partial<
    Record<
      "mode" | "name" | "town" | "postal_address" | "phone" | "email",
      string
    >
  >;
}) {
  const { t } = useTranslation();
  const legend = React.useId();
  const modes = buyerModes(year);
  const mode = buyerMode(value, year);
  const before = year < 2027;
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
  const note = (text: string) => (
    <Box
      sx={{
        fontSize: variant === "member" ? 15 : 13,
        color: variant === "member" ? "var(--sb-ink-2)" : "var(--sb-ink-3)",
      }}
    >
      {text}
    </Box>
  );
  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", gap: 2 }}
      className={variant === "member" ? report.memberFields : undefined}
      data-testid="sell-buyer"
    >
      {modes.length > 1 && (
        <FormControl error={!!errors?.mode}>
          <FormLabel id={legend}>
            {t(
              before
                ? "individual.sell.buyerHasEmail"
                : "individual.sell.buyerGotBevis",
            )}
          </FormLabel>
          <RadioGroup
            aria-labelledby={legend}
            value={mode ?? ""}
            onChange={(e) => set({ mode: e.target.value as BuyerMode })}
          >
            {modes.map((m) => (
              <FormControlLabel
                key={m}
                value={m}
                control={
                  <Radio
                    // a refused Spara focuses the first field in error (SoldDialog)
                    slotProps={{
                      input: {
                        "aria-invalid": errors?.mode ? true : undefined,
                      },
                    }}
                  />
                }
                label={t(
                  `individual.sell.buyerMode_${m}${before ? "" : "_2027"}`,
                )}
              />
            ))}
          </RadioGroup>
          {errors?.mode && <FormHelperText>{errors.mode}</FormHelperText>}
        </FormControl>
      )}
      {mode === "epost" && (
        <>
          {field("name", t("individual.sell.buyerName"), true)}
          {field("town", t("individual.sell.buyerTown"), true)}
          {field("postal_address", t("individual.sell.buyerAddress"), true)}
          {field("email", t("individual.sell.buyerEmail"), true)}
          {note(t("individual.sell.buyerNoticeNote"))}
        </>
      )}
      {mode === "utan" && note(t("individual.sell.buyerNotRecordedNote"))}
      {mode === "bevis" && (
        <>
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
          {/* the report's sale has happened: the bevis was given or not */}
          {variant !== "member" && note(t("individual.sell.buyerNote"))}
        </>
      )}
    </Box>
  );
}
