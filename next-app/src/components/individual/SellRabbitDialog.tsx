"use client";

import React from "react";
import {
  Dialog,
  DialogContent,
  DialogActions,
  TextField,
  Autocomplete,
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import type { PickersActionBarProps } from "@mui/x-date-pickers/PickersActionBar";
import {
  usePickerActionsContext,
  usePickerTranslations,
} from "@mui/x-date-pickers/hooks";
import { useTranslation } from "react-i18next";
import {
  type GenebankHerd,
  isOutsideGenebankHerd,
  minSaleDate,
  stockholmToday,
  toIsoDate,
  validateSaleDate,
} from "@/utils/saleRules";

/**
 * "Idag" action: MUI's built-in `today` uses the browser's timezone, but the API
 * validates against Stockholm's calendar date, so set that explicitly.
 */
function StockholmTodayActionBar({ className, sx }: PickersActionBarProps) {
  const { setValue } = usePickerActionsContext();
  const translations = usePickerTranslations();
  return (
    <DialogActions className={className} sx={sx}>
      <Button onClick={() => setValue(stockholmToday(), { source: "view" })}>
        {translations.todayButtonLabel}
      </Button>
    </DialogActions>
  );
}

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

type LoadHerdsResult =
  | { success: true; herds: GenebankHerd[] }
  | { success: false; error: string };

interface SellRabbitDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (herd: string, sellingDate: string, buyer?: SaleBuyer) => void;
  loadHerds: () => Promise<LoadHerdsResult>;
  individualName: string;
  individualNumber: string;
  currentHerd: { herd: string; herd_name?: string | null };
  birthDate: string | null | undefined;
  herdTracking: { date: string | null }[] | null | undefined;
  isRegistered: boolean;
  isSaving: boolean;
  /** Problem detail from the last failed attempt; shown inline (the snackbar sits behind the modal). */
  error?: string | null;
}

const herdText = (herd: string, name?: string | null) =>
  name ? `${herd} – ${name}` : herd;

const summaryRow = {
  display: "flex",
  gap: 1.5,
  py: 1,
  borderTop: "1px solid var(--sb-line-faint)",
  "&:first-of-type": { borderTop: 0 },
} as const;

/**
 * The inner dialog is remounted on every opening, so a previous destination,
 * acknowledgement, date or error never survives a close (whichever way it closed).
 */
export function SellRabbitDialog(props: SellRabbitDialogProps) {
  const [openings, setOpenings] = React.useState(0);
  const [wasOpen, setWasOpen] = React.useState(props.open);
  if (props.open !== wasOpen) {
    setWasOpen(props.open);
    if (props.open) setOpenings((n) => n + 1);
  }
  return <SellRabbitDialogContent key={openings} {...props} />;
}

function SellRabbitDialogContent({
  open,
  onClose,
  onConfirm,
  loadHerds,
  individualName,
  individualNumber,
  currentHerd,
  birthDate,
  herdTracking,
  isRegistered,
  isSaving,
  error,
}: SellRabbitDialogProps) {
  const { t } = useTranslation();
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));
  // Stockholm calendar date, recomputed on every render and on submit so a dialog
  // left open past midnight does not validate against a stale "today".
  const today = stockholmToday();
  const minDate = React.useMemo(
    () => minSaleDate(birthDate, herdTracking),
    [birthDate, herdTracking],
  );

  const [herdsResult, setHerdsResult] = React.useState<LoadHerdsResult | null>(
    null,
  );
  const [target, setTarget] = React.useState<GenebankHerd | null>(null);
  const [date, setDate] = React.useState<Date | null>(() => stockholmToday());
  const [acknowledged, setAcknowledged] = React.useState(false);
  const [buyer, setBuyer] = React.useState({
    name: "",
    town: "",
    postal_address: "",
    email: "",
    phone: "",
  });
  const [contactConsent, setContactConsent] = React.useState(false);
  const [membershipOptin, setMembershipOptin] = React.useState(false);

  // Load the herd list when the dialog opens (picker data is not needed earlier).
  React.useEffect(() => {
    if (!open || herdsResult !== null) return;
    let cancelled = false;
    loadHerds().then((result) => {
      if (!cancelled) setHerdsResult(result);
    });
    return () => {
      cancelled = true;
    };
  }, [open, herdsResult, loadHerds]);
  const herds = herdsResult?.success ? herdsResult.herds : null;
  const herdsError = herdsResult !== null && !herdsResult.success;

  const options = React.useMemo(
    () =>
      (herds ?? [])
        .filter(
          (h) =>
            // GX1 to GX1 too: a buyer outside the association sells to another.
            (h.herd !== currentHerd.herd || isOutsideGenebankHerd(h.herd)) &&
            (isRegistered || isOutsideGenebankHerd(h.herd)),
        )
        // The outside-genebank herd first: it is the common choice.
        .sort(
          (a, b) =>
            Number(isOutsideGenebankHerd(b.herd)) -
              Number(isOutsideGenebankHerd(a.herd)) ||
            a.herd.localeCompare(b.herd, "sv", { numeric: true }),
        ),
    [herds, currentHerd.herd, isRegistered],
  );

  const dateProblem = validateSaleDate(date, minDate, today);
  const outsideCode = options.find((h) => isOutsideGenebankHerd(h.herd))?.herd;
  const targetOutside = target ? isOutsideGenebankHerd(target.herd) : false;
  const buyerComplete = !!buyer.name.trim() && !!buyer.town.trim();
  const canSubmit =
    !!target &&
    !dateProblem &&
    acknowledged &&
    (!targetOutside || buyerComplete) &&
    !isSaving;

  const optionLabel = (h: GenebankHerd) =>
    herdText(
      h.herd,
      isOutsideGenebankHerd(h.herd)
        ? h.herd_name || t("individual.sell.outsideGenebank")
        : h.herd_name,
    ) +
    (h.is_active || isOutsideGenebankHerd(h.herd)
      ? ""
      : ` (${t("individual.sell.inactive")})`);

  // Escape/backdrop must not close the dialog while a save is in flight.
  const handleClose = () => {
    if (isSaving) return;
    onClose();
  };

  const handleConfirm = () => {
    if (!target || !date || validateSaleDate(date, minDate, stockholmToday())) {
      return;
    }
    if (!targetOutside) {
      onConfirm(target.herd, toIsoDate(date));
      return;
    }
    // Only what the buyer said yes to: a field hidden by an unticked box is never sent.
    const kept = (
      field: "postal_address" | "email" | "phone",
      allowed: boolean,
    ) =>
      allowed && buyer[field].trim() ? { [field]: buyer[field].trim() } : {};
    const contactAllowed = contactConsent || membershipOptin;
    onConfirm(target.herd, toIsoDate(date), {
      name: buyer.name.trim(),
      town: buyer.town.trim(),
      contact_consent: contactConsent,
      membership_optin: membershipOptin,
      ...kept("postal_address", contactConsent),
      ...kept("email", contactAllowed),
      ...kept("phone", contactAllowed),
    });
  };

  const buyerField = (
    field: keyof typeof buyer,
    label: string,
    required = false,
  ) => (
    <TextField
      label={label}
      value={buyer[field]}
      onChange={(e) => setBuyer((b) => ({ ...b, [field]: e.target.value }))}
      required={required}
      fullWidth
      slotProps={{ htmlInput: { maxLength: 200 } }}
    />
  );

  const displayName = individualName || individualNumber;
  const dateError = dateProblem
    ? t(`individual.sell.date_${dateProblem}`, {
        min: minDate ? toIsoDate(minDate) : "",
      })
    : null;

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="sm"
      fullWidth
      fullScreen={fullScreen}
      aria-labelledby="sell-rabbit-title"
    >
      <DialogContent sx={{ pt: 3 }}>
        <span className="sb-badge sb-badge-lera">
          {t("individual.sell.badge")}
        </span>
        <Box
          component="h2"
          id="sell-rabbit-title"
          sx={{
            fontFamily: "var(--sb-display)",
            fontWeight: 400,
            fontSize: 27,
            lineHeight: 1.12,
            letterSpacing: "-0.015em",
            m: "12px 0 4px",
          }}
        >
          {t("individual.sell.title", { name: displayName })}
        </Box>
        <Box
          component="p"
          sx={{
            fontSize: 14.5,
            lineHeight: 1.5,
            color: "var(--sb-ink-2)",
            m: "0 0 16px",
          }}
        >
          {t("individual.sell.intro")}
        </Box>

        <Box
          className="sb-card"
          sx={{ p: "14px 16px", mb: 2.5 }}
          data-testid="sell-rabbit-card"
        >
          <Box
            sx={{
              fontFamily: "var(--sb-mono)",
              fontSize: 13,
              fontWeight: 500,
              color: "var(--sb-skog)",
            }}
          >
            {individualNumber}
          </Box>
          <Box
            sx={{
              fontFamily: "var(--sb-display)",
              fontSize: 22,
              fontWeight: 600,
              lineHeight: 1.15,
            }}
          >
            {displayName}
          </Box>
          <Box sx={{ fontSize: 13, color: "var(--sb-ink-3)" }}>
            {t("individual.sell.currentHerd")}:{" "}
            {herdText(currentHerd.herd, currentHerd.herd_name)}
          </Box>
        </Box>

        {!isRegistered && (
          <Alert severity="info" sx={{ mb: 2 }}>
            {t("individual.sell.unregisteredInfo", {
              code: outsideCode ?? "GX1/MX1",
            })}
          </Alert>
        )}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} data-testid="sell-error">
            {error}
          </Alert>
        )}
        {herdsError && (
          <Alert
            severity="error"
            sx={{ mb: 2 }}
            action={
              <button
                type="button"
                className="sb-btn sb-btn-secondary sb-btn-sm"
                onClick={() => setHerdsResult(null)}
              >
                {t("individual.sell.retry")}
              </button>
            }
          >
            {t("individual.sell.herdsError")}
          </Alert>
        )}

        <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
          <Autocomplete
            options={options}
            value={target}
            onChange={(_, value) => setTarget(value)}
            getOptionLabel={optionLabel}
            isOptionEqualToValue={(a, b) => a.herd === b.herd}
            loading={herds === null && !herdsError}
            noOptionsText={t("individual.sell.noOptions")}
            renderInput={(params) => (
              <TextField
                {...params}
                label={t("individual.sell.herdLabel")}
                helperText={t("individual.sell.herdHelper", {
                  code: outsideCode ?? "GX1/MX1",
                })}
              />
            )}
          />
          <DatePicker
            label={t("individual.sell.dateLabel")}
            value={date}
            onChange={setDate}
            minDate={minDate ?? undefined}
            maxDate={today}
            format="yyyy-MM-dd"
            slotProps={{
              textField: {
                fullWidth: true,
                error: !!dateProblem,
                helperText:
                  dateError ??
                  (minDate
                    ? t("individual.sell.dateHelper", {
                        min: toIsoDate(minDate),
                      })
                    : undefined),
              },
            }}
            slots={{ actionBar: StockholmTodayActionBar }}
          />
        </Box>

        {targetOutside && (
          <Box
            sx={{ display: "flex", flexDirection: "column", gap: 2, mt: 2.5 }}
            data-testid="sell-buyer"
          >
            {buyerField("name", t("individual.sell.buyerName"), true)}
            {buyerField("town", t("individual.sell.buyerTown"), true)}
            <FormControlLabel
              sx={{ alignItems: "flex-start", ml: 0 }}
              control={
                <Checkbox
                  checked={contactConsent}
                  onChange={(e) => setContactConsent(e.target.checked)}
                  sx={{ pt: 0.5 }}
                />
              }
              label={t("individual.sell.buyerContactConsent")}
            />
            <FormControlLabel
              sx={{ alignItems: "flex-start", ml: 0 }}
              control={
                <Checkbox
                  checked={membershipOptin}
                  onChange={(e) => setMembershipOptin(e.target.checked)}
                  sx={{ pt: 0.5 }}
                />
              }
              label={t("individual.sell.buyerMembershipOptin")}
            />
            {contactConsent &&
              buyerField("postal_address", t("individual.sell.buyerAddress"))}
            {(contactConsent || membershipOptin) && (
              <>
                {buyerField("email", t("individual.sell.buyerEmail"))}
                {buyerField("phone", t("individual.sell.buyerPhone"))}
              </>
            )}
            <Box sx={{ fontSize: 13, color: "var(--sb-ink-3)" }}>
              {t("individual.sell.buyerNote")}
            </Box>
          </Box>
        )}

        {target && !dateProblem && date && (
          <Box
            className="sb-card"
            sx={{ p: "8px 16px", mt: 2.5 }}
            data-testid="sell-summary"
          >
            {[
              [
                t("individual.sell.summaryFrom"),
                herdText(currentHerd.herd, currentHerd.herd_name),
              ],
              [t("individual.sell.summaryTo"), optionLabel(target)],
              [t("individual.sell.summaryDate"), toIsoDate(date)],
            ].map(([label, value]) => (
              <Box key={label} sx={summaryRow}>
                <Box
                  sx={{
                    flex: "0 0 88px",
                    fontFamily: "var(--sb-mono)",
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                    color: "var(--sb-ink-3)",
                    pt: "3px",
                  }}
                >
                  {label}
                </Box>
                <Box sx={{ fontSize: 14.5, fontWeight: 600 }}>{value}</Box>
              </Box>
            ))}
            {targetOutside && (
              <Box sx={{ fontSize: 13, color: "var(--sb-ink-3)", pb: 1 }}>
                {t("individual.sell.summaryOutside")}
              </Box>
            )}
          </Box>
        )}

        <FormControlLabel
          sx={{ mt: 2, alignItems: "flex-start", ml: 0 }}
          control={
            <Checkbox
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              sx={{ pt: 0.5 }}
            />
          }
          label={
            <Box
              sx={{
                fontSize: 13.5,
                lineHeight: 1.45,
                color: "var(--sb-ink-2)",
              }}
            >
              {t("individual.sell.acknowledge")}
            </Box>
          }
        />
        <Box
          sx={{
            fontSize: 12,
            color: "var(--sb-ink-4)",
            lineHeight: 1.5,
            mt: 1,
          }}
        >
          {t("individual.sell.lockNote")}
        </Box>
      </DialogContent>
      <DialogActions
        sx={{
          px: 3,
          pb: 2.5,
          flexDirection: { xs: "column-reverse", sm: "row" },
          alignItems: "stretch",
          gap: 1.25,
          "& > :not(style) ~ :not(style)": { ml: 0 },
        }}
      >
        <button
          type="button"
          className="sb-btn sb-btn-secondary"
          style={{ justifyContent: "center" }}
          onClick={handleClose}
          disabled={isSaving}
        >
          {t("common.cancel")}
        </button>
        <button
          type="button"
          className="sb-btn"
          style={{ justifyContent: "center" }}
          onClick={handleConfirm}
          disabled={!canSubmit}
        >
          {isSaving
            ? t("individual.edit.saving")
            : t("individual.sell.confirmButton")}
        </button>
      </DialogActions>
    </Dialog>
  );
}
