"use client";

import React, { useState, useEffect, useTransition } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useMode } from "@/lib/mode-context";
import {
  promoteBunny,
  checkIndividualNumber,
  checkLitterOrder,
  renumberLitters,
  getColors,
  updateBreeding,
  type ColorOption,
  type NumberCheck,
  type NumberResolution,
  type RosterBunny,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";
import {
  NumberConflictDialog,
  PAPER_NUMBER,
} from "@/components/herd/NumberConflictDialog";

const LitterNumberConflictDialog = dynamic(
  () =>
    import("./LitterNumberConflictDialog").then(
      (m) => m.LitterNumberConflictDialog,
    ),
  { ssr: false },
);

interface BunnyPromoteDialogProps {
  open: boolean;
  onClose: () => void;
  onPromoted: () => void;
  bunny: RosterBunny;
  breeding: {
    id: number;
    birth_date?: string | null;
    mother?: string | null;
    mother_name?: string | null;
    father?: string | null;
    father_name?: string | null;
    litter_number?: number | null;
    litter_size?: number | null;
    litter_size6w?: number | null;
  };
  herdId: string;
}

interface SuccessState {
  number: string;
  name: string | null;
  digital_certificate: string | null;
  certificate_error: string | null;
}

interface ConflictState {
  conflicts: Array<{
    breeding_id: number;
    current_litter_number: number;
    suggested_litter_number: number;
    birth_date: string;
    mother?: string | null;
    affected_individuals?: string[];
  }>;
  year: number;
}

export function BunnyPromoteDialog({
  open,
  onClose,
  onPromoted,
  bunny,
  breeding,
  herdId,
}: BunnyPromoteDialogProps) {
  const { t } = useTranslation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [isPending, startTransition] = useTransition();
  const mode = useMode();
  // Mirror modeAwareBaseQuery: demo routes to /api-test only when the client
  // test URL is configured; base dev and prod stay on /api.
  const apiBase =
    mode === "demo" && process.env.NEXT_PUBLIC_API_TEST_URL
      ? process.env.NEXT_PUBLIC_API_TEST_URL
      : "/api";

  // Form state — pre-fill from observed fields on the bunny
  const [sex, setSex] = useState(
    bunny.observed_sex === "male" || bunny.observed_sex === "female"
      ? bunny.observed_sex
      : "",
  );
  const [color, setColor] = useState(bunny.observed_color || "");
  // null until loaded; [] when the fetch failed (falls back to free text —
  // the backend validates against the genebank color list either way).
  const [colorOptions, setColorOptions] = useState<ColorOption[] | null>(null);
  const [name, setName] = useState(bunny.label || "");
  const [colorNote, setColorNote] = useState("");
  const [eyeColor, setEyeColor] = useState("");
  const [clawColor, setClawColor] = useState("");
  const [bellyColor, setBellyColor] = useState("");
  const [hairNotes, setHairNotes] = useState("");
  // A rabbit is only registered with a certificate; the roster issues the PDF
  const [certificateType, setCertificateType] = useState<"paper" | "digital">(
    "digital",
  );
  const [paperCertificate, setPaperCertificate] = useState("");
  // What the paper says, typed before Stamboken's number is shown; never prefilled
  const [paperNumber, setPaperNumber] = useState("");
  const [numberCheck, setNumberCheck] = useState<NumberCheck | null>(null);
  const [numberConflict, setNumberConflict] = useState<NumberCheck | null>(
    null,
  );
  const paper = certificateType === "paper";
  const paperNumberReady = PAPER_NUMBER.test(paperNumber.trim());
  // A certificate needs "alive at 6 weeks" on the litter: asked for here when missing
  const [litterSize6w, setLitterSize6w] = useState("");
  const needsLitterSize6w = breeding.litter_size6w == null;

  // Outcome state
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<SuccessState | null>(null);
  const [conflictData, setConflictData] = useState<ConflictState | null>(null);
  const [isRenumbering, setIsRenumbering] = useState(false);
  const [renumberError, setRenumberError] = useState<string | null>(null);

  // Re-init prefills if bunny changes (e.g. dialog reused for another bunny)
  useEffect(() => {
    setSex(
      bunny.observed_sex === "male" || bunny.observed_sex === "female"
        ? bunny.observed_sex
        : "",
    );
    setColor(bunny.observed_color || "");
    setName(bunny.label || "");
  }, [bunny.id, bunny.observed_sex, bunny.observed_color, bunny.label]);

  // Load the genebank's official color list when the dialog opens. The
  // observed_color prefill is free text — keep it only if it is official.
  useEffect(() => {
    if (!open || colorOptions !== null) return;
    getColors().then((all) => {
      if (!all) {
        setColorOptions([]);
        return;
      }
      const wantMellerud = herdId.startsWith("M");
      const key =
        Object.keys(all).find((k) =>
          wantMellerud ? k.includes("Mellerud") : k.includes("Gotland"),
        ) ?? Object.keys(all)[0];
      const options = all[key] ?? [];
      setColorOptions(options);
      setColor((prev) =>
        prev && !options.some((o) => o.name === prev) ? "" : prev,
      );
    });
  }, [open, colorOptions, herdId]);

  // Paper: Stamboken's number for what the paper says (the dry run), once it is typed
  useEffect(() => {
    if (!open || !paper || !paperNumberReady) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const result = await checkIndividualNumber({
        breeding_id: breeding.id,
        paper_number: paperNumber.trim(),
      });
      if (!cancelled) setNumberCheck(result.success ? result.data : null);
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, paper, paperNumber, paperNumberReady, breeding.id]);

  const translateError = (raw: string, title?: string): string => {
    const key = title || raw;
    switch (key) {
      case "litter_size_required":
        return t("addRabbit.errorLitterSize");
      case "too_young": {
        const birthMs = breeding.birth_date
          ? new Date(breeding.birth_date).getTime()
          : NaN;
        if (!Number.isNaN(birthMs)) {
          const days = Math.max(
            0,
            42 - Math.floor((Date.now() - birthMs) / 86400000),
          );
          return t("litterRoster.registerDisabledAge", { days });
        }
        return t("litterRoster.registerTooYoung");
      }
      case "out_of_order":
        return t("litterRoster.registerOutOfOrder");
      case "litter_full":
        return t("addRabbit.errorMaxReached");
      case "sex_required":
        return t("addRabbit.errorSexRequired");
      case "color_required":
        return t("addRabbit.errorColorRequired");
      case "unknown_color":
        return t("addRabbit.errorUnknownColor");
      case "litter_size6w_required":
        return t("addRabbit.errorLitterSize6wRequired");
      case "roster_alive_exceeds_6w":
      case "litter_size6w_above_born":
        return raw; // the API's sentence (with the counts; the roster offers the fix)
      default:
        return t("litterRoster.promoteError");
    }
  };

  const doPromote = async (resolution?: NumberResolution): Promise<boolean> => {
    setError(null);
    const result = await promoteBunny(bunny.id, {
      certificate_type: certificateType,
      paper_certificate: paper ? paperCertificate : undefined,
      paper_number: paper ? paperNumber.trim() : undefined,
      resolution,
      // Saved on the litter by the registration itself: a refusal leaves it unset
      litter_size6w: needsLitterSize6w ? parseInt(litterSize6w, 10) : undefined,
      sex: sex || undefined,
      name: name || undefined,
      color: color || undefined,
      color_note: colorNote || undefined,
      eye_color: eyeColor || undefined,
      claw_color: clawColor || undefined,
      belly_color: bellyColor || undefined,
      hair_notes: hairNotes || undefined,
    });

    setNumberConflict(result.success ? null : (result.numberCheck ?? null));
    if (!result.success && result.numberCheck) return false;
    if (result.success) {
      const ind = result.data.individual;
      setSuccess({
        number: ind.number as string,
        name: (ind.name as string) || null,
        digital_certificate:
          certificateType === "digital" ? result.data.certificate : null,
        certificate_error: result.data.certificate_error,
      });
      return true;
    }
    if (result.errorTitle === "roster_alive_exceeds_6w" && needsLitterSize6w) {
      // Kept on the litter after all, so the roster offers the kits to mark dead
      await updateBreeding(breeding.id, {
        litter_size6w: parseInt(litterSize6w, 10),
      });
    }

    if (result.errorTitle === "litter_order_conflict" && breeding.birth_date) {
      const year = new Date(breeding.birth_date).getFullYear();
      const orderResult = await checkLitterOrder(herdId, year);
      if (orderResult.success && !orderResult.data.consistent) {
        setConflictData({
          conflicts: orderResult.data.conflicts as ConflictState["conflicts"],
          year,
        });
        return false;
      }
    }

    setError(translateError(result.error, result.errorTitle));
    return false;
  };

  const handleSubmit = () => {
    startTransition(async () => {
      await doPromote();
    });
  };

  const handleRenumberConfirm = async () => {
    if (!conflictData) return;
    setIsRenumbering(true);
    setRenumberError(null);
    const result = await renumberLitters(herdId, conflictData.year, true);
    setIsRenumbering(false);
    if (result.success) {
      setConflictData(null);
      startTransition(async () => {
        await doPromote();
      });
    } else {
      setRenumberError(
        result.errorStatus === 403
          ? t("addRabbit.conflict.renumberManagerRequired")
          : t("addRabbit.conflict.renumberFailed"),
      );
    }
  };

  const resetForm = () => {
    setSex(
      bunny.observed_sex === "male" || bunny.observed_sex === "female"
        ? bunny.observed_sex
        : "",
    );
    setColor(bunny.observed_color || "");
    setName("");
    setColorNote("");
    setEyeColor("");
    setClawColor("");
    setBellyColor("");
    setHairNotes("");
    setCertificateType("digital");
    setPaperCertificate("");
    setPaperNumber("");
    setNumberCheck(null);
    setNumberConflict(null);
    setLitterSize6w("");
    setError(null);
    setSuccess(null);
    setConflictData(null);
    setRenumberError(null);
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  const handleRegisterAnother = () => {
    onPromoted();
  };

  const motherDisplay =
    breeding.mother_name || breeding.mother || t("pedigree.unknown");
  const fatherDisplay =
    breeding.father_name || breeding.father || t("pedigree.unknown");

  // On paper Stamboken's number for what the paper says, never before it is typed
  const titleNumber = paper
    ? (numberCheck?.stamboken_number ?? null)
    : bunny.provisional_number;
  const dialogTitle = titleNumber
    ? t("litterRoster.promoteTitleWithNumber", { number: titleNumber })
    : t("litterRoster.promoteTitle");

  return (
    <>
      <Dialog
        open={open}
        onClose={(_event, reason) => {
          if (reason === "backdropClick" || reason === "escapeKeyDown") return;
          handleClose();
        }}
        maxWidth="sm"
        fullWidth
        fullScreen={isMobile}
        aria-labelledby="bunny-promote-dialog-title"
      >
        <DialogTitle id="bunny-promote-dialog-title" sx={{ pr: 6 }}>
          {dialogTitle}
          {isMobile && (
            <IconButton
              onClick={handleClose}
              disabled={isPending}
              aria-label={t("addRabbit.cancel")}
              sx={{
                position: "absolute",
                right: 8,
                top: 8,
                color: "text.secondary",
              }}
            >
              <CloseIcon />
            </IconButton>
          )}
        </DialogTitle>

        <DialogContent
          dividers={isMobile}
          sx={{ pt: isMobile ? 2 : undefined }}
        >
          {/* Litter context */}
          <Box sx={{ mb: 2.5 }}>
            <Typography
              variant="body2"
              sx={{
                color: "text.secondary",
              }}
            >
              {t("addRabbit.litterContext", {
                mother: motherDisplay,
                father: fatherDisplay,
                date: breeding.birth_date || "?",
              })}
              {breeding.litter_number != null &&
                ` | ${t("addRabbit.litterNumber")}: ${breeding.litter_number}`}
            </Typography>
          </Box>

          <Divider sx={{ mb: 2.5 }} />

          {success ? (
            /* ── Success card ── */
            <Box>
              <Alert severity="success" sx={{ mb: 2 }}>
                {success.name
                  ? t("addRabbit.success", {
                      name: success.name,
                      number: success.number,
                    })
                  : t("addRabbit.successNoName", { number: success.number })}
              </Alert>
              {success.certificate_error && (
                <Alert severity="warning" sx={{ mb: 2 }}>
                  {t("litterRoster.certificateError", {
                    error: success.certificate_error,
                  })}
                </Alert>
              )}
              <Box
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 1,
                }}
              >
                <Button variant="outlined" onClick={handleRegisterAnother}>
                  {t("litterRoster.registerAnother")}
                </Button>
                <Button
                  component={Link}
                  href={`/stamboken/individ/${encodeURIComponent(success.number)}`}
                  variant="text"
                  onClick={handleClose}
                >
                  {t("addRabbit.viewRabbit")}
                </Button>
                {success.digital_certificate && (
                  <Button
                    component="a"
                    href={`${apiBase}/v2/certificates/${encodeURIComponent(success.number)}`}
                    target="_blank"
                    rel="noopener"
                    variant="text"
                  >
                    {t("addRabbit.viewCertificate")}
                  </Button>
                )}
              </Box>
            </Box>
          ) : (
            /* ── Registration form ── */
            <Box
              sx={{
                display: "flex",
                flexDirection: "column",
                gap: isMobile ? 2.5 : 2,
                pb: isMobile ? 3 : 0,
              }}
            >
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}

              {/* Provisional number preview */}
              {bunny.provisional_number && (
                <Box
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    gap: 1.5,
                    px: 1.5,
                    py: 1,
                    borderRadius: 1,
                    bgcolor: "action.hover",
                    border: 1,
                    borderColor: "divider",
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{
                      color: "text.secondary",
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                    }}
                  >
                    {t("litterRoster.provisionalNumber")}
                  </Typography>
                  <Typography
                    variant="body1"
                    sx={{ fontFamily: "monospace", fontWeight: 600 }}
                  >
                    {bunny.provisional_number}
                  </Typography>
                </Box>
              )}

              {/* Sex — required at registration (pre-filled from observed sex) */}
              <FormControl size="small" fullWidth required>
                <InputLabel id="bunny-promote-sex-label">
                  {t("addRabbit.sex")}
                </InputLabel>
                <Select
                  labelId="bunny-promote-sex-label"
                  value={sex}
                  onChange={(e) => setSex(e.target.value)}
                  label={t("addRabbit.sex")}
                >
                  <MenuItem value="female">{t("addRabbit.sexFemale")}</MenuItem>
                  <MenuItem value="male">{t("addRabbit.sexMale")}</MenuItem>
                </Select>
              </FormControl>

              {/* Color — official genebank color list */}
              <Autocomplete
                options={(colorOptions ?? []).map((c) => c.name)}
                value={color || null}
                onChange={(_, v) => setColor(v ?? "")}
                freeSolo={!colorOptions || colorOptions.length === 0}
                onInputChange={
                  !colorOptions || colorOptions.length === 0
                    ? (_, v) => setColor(v)
                    : undefined
                }
                size="small"
                fullWidth
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label={t("addRabbit.color")}
                    required
                  />
                )}
              />

              {/* Name */}
              <TextField
                label={t("addRabbit.name")}
                value={name}
                onChange={(e) => setName(e.target.value)}
                size="small"
                fullWidth
              />

              {/* Color note */}
              <TextField
                label={t("addRabbit.colorNote")}
                value={colorNote}
                onChange={(e) => setColorNote(e.target.value)}
                size="small"
                fullWidth
              />

              {/* Eye color */}
              <TextField
                label={t("addRabbit.eyeColor")}
                value={eyeColor}
                onChange={(e) => setEyeColor(e.target.value)}
                size="small"
                fullWidth
              />

              {/* Claw color */}
              <TextField
                label={t("addRabbit.clawColor")}
                value={clawColor}
                onChange={(e) => setClawColor(e.target.value)}
                size="small"
                fullWidth
              />

              {/* Belly color */}
              <TextField
                label={t("addRabbit.bellyColor")}
                value={bellyColor}
                onChange={(e) => setBellyColor(e.target.value)}
                size="small"
                fullWidth
              />

              {/* Hair notes */}
              <TextField
                label={t("addRabbit.hairNotes")}
                value={hairNotes}
                onChange={(e) => setHairNotes(e.target.value)}
                size="small"
                fullWidth
              />

              {/* Certificate type */}
              <FormControl size="small" fullWidth required>
                <InputLabel id="bunny-promote-certificate-label">
                  {t("addRabbit.certificate")}
                </InputLabel>
                <Select
                  labelId="bunny-promote-certificate-label"
                  value={certificateType}
                  onChange={(e) =>
                    setCertificateType(e.target.value as "paper" | "digital")
                  }
                  label={t("addRabbit.certificate")}
                >
                  <MenuItem value="paper">
                    {t("addRabbit.certificatePaper")}
                  </MenuItem>
                  <MenuItem value="digital">
                    {t("addRabbit.certificateDigital")}
                  </MenuItem>
                </Select>
              </FormControl>

              {/* Paper certificate number */}
              {certificateType === "paper" && (
                <TextField
                  label={t("addRabbit.paperCertificateNumber")}
                  value={paperCertificate}
                  onChange={(e) => setPaperCertificate(e.target.value)}
                  size="small"
                  fullWidth
                  required
                />
              )}
              {certificateType === "paper" && (
                <TextField
                  label={t("numberConflict.paperNumber")}
                  value={paperNumber}
                  onChange={(e) => {
                    setPaperNumber(e.target.value);
                    setNumberCheck(null); // the check of the previous text
                  }}
                  helperText={t("numberConflict.paperNumberHelp")}
                  placeholder="G1274-2512"
                  size="small"
                  fullWidth
                  required
                />
              )}

              {/* Alive at 6 weeks — required before a certificate */}
              {needsLitterSize6w && (
                <TextField
                  label={t("addRabbit.litterSize6w")}
                  helperText={t("addRabbit.errorLitterSize6wRequired")}
                  value={litterSize6w}
                  onChange={(e) => setLitterSize6w(e.target.value)}
                  type="number"
                  slotProps={{
                    htmlInput: {
                      min: 0,
                      max: breeding.litter_size ?? undefined,
                    },
                  }}
                  size="small"
                  fullWidth
                  required
                />
              )}
            </Box>
          )}
        </DialogContent>

        {!success && (
          <DialogActions
            sx={
              isMobile
                ? {
                    position: "sticky",
                    bottom: 0,
                    bgcolor: "background.paper",
                    borderTop: 1,
                    borderColor: "divider",
                    boxShadow: "0 -2px 8px rgba(0,0,0,0.06)",
                    py: 1.5,
                    px: 2,
                    gap: 1,
                  }
                : undefined
            }
          >
            <Button
              onClick={handleClose}
              disabled={isPending}
              variant="outlined"
              fullWidth={isMobile}
              size={isMobile ? "large" : "medium"}
            >
              {t("addRabbit.cancel")}
            </Button>
            <Button
              onClick={handleSubmit}
              variant="contained"
              disabled={
                isPending ||
                !sex ||
                !color ||
                (paper && (!paperCertificate || !paperNumberReady)) ||
                (needsLitterSize6w && litterSize6w === "")
              }
              fullWidth={isMobile}
              size={isMobile ? "large" : "medium"}
            >
              {isPending ? t("addRabbit.saving") : t("addRabbit.save")}
            </Button>
          </DialogActions>
        )}
        {success && (
          <DialogActions>
            <Button
              onClick={() => {
                onPromoted();
                handleClose();
              }}
            >
              {t("common.close")}
            </Button>
          </DialogActions>
        )}
      </Dialog>

      {numberConflict && (
        <NumberConflictDialog
          check={numberConflict}
          isSaving={isPending}
          onUseStambokenNumber={() =>
            startTransition(async () => {
              await doPromote({
                expected_number: numberConflict.stamboken_number,
                choice: "use_stamboken_number",
              });
            })
          }
          onClose={() => setNumberConflict(null)}
        />
      )}
      {/* Conflict resolution dialog */}
      {conflictData && (
        <LitterNumberConflictDialog
          open
          conflicts={conflictData.conflicts}
          onConfirm={handleRenumberConfirm}
          onClose={() => {
            setConflictData(null);
            setRenumberError(null);
          }}
          isRenumbering={isRenumbering}
          error={renumberError}
        />
      )}
    </>
  );
}
