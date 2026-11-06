"use client";

import React, { useState, useEffect, useTransition, useCallback } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Popover,
  Select,
  TextField,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import LockIcon from "@mui/icons-material/Lock";
import LockOpenIcon from "@mui/icons-material/LockOpen";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import CloseIcon from "@mui/icons-material/Close";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import { sv } from "date-fns/locale";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import { useMode } from "@/lib/mode-context";
import type { PaginatedIndividualItem } from "@/redux/api/apiSlice";
import { IndividualAutocomplete } from "@/components/herd/IndividualAutocomplete";
import {
  NumberConflictDialog,
  PAPER_NUMBER,
} from "@/components/herd/NumberConflictDialog";
import {
  checkIndividualNumber,
  registerIndividual,
  suggestIndividualNumber,
  type IndividualNumberSuggestion,
  type NumberCheck,
  type NumberResolution,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";

interface Breeding {
  id: number;
  mother?: string | null;
  mother_name?: string | null;
  father?: string | null;
  father_name?: string | null;
  birth_date?: string | null;
  breeding_herd?: string | null;
  litter_number?: number | null;
  litter_size?: number | null;
  litter_size6w?: number | null;
}

interface RegisterRabbitDialogProps {
  open: boolean;
  onClose: () => void;
  /** The litter the rabbit is born in. Without it ("Lägg till kanin") the form
   *  asks for the litter, and the API reuses or creates it. */
  breeding?: Breeding;
  herdId: string;
  /** Needed by the parent pickers when there is no `breeding`. */
  genebankId?: number | null;
}

interface SuccessData {
  number: string;
  name: string | null;
  certificate_type: string;
  digital_certificate: string | null;
  certificate_error: string | null;
}

function formatDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function RegisterRabbitDialog({
  open,
  onClose,
  breeding,
  herdId,
  genebankId,
}: RegisterRabbitDialogProps) {
  const { t } = useTranslation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [isPending, startTransition] = useTransition();
  const mode = useMode();
  // As BunnyPromoteDialog: demo reads certificates from /api-test when configured.
  const apiBase =
    mode === "demo" && process.env.NEXT_PUBLIC_API_TEST_URL
      ? process.env.NEXT_PUBLIC_API_TEST_URL
      : "/api";
  const shortcut = !breeding;
  const breedingId = breeding?.id;

  // Shortcut mode: the litter the rabbit is born in
  const [mother, setMother] = useState<PaginatedIndividualItem | null>(null);
  const [father, setFather] = useState<PaginatedIndividualItem | null>(null);
  const [birthDate, setBirthDate] = useState<Date | null>(null);
  const [litterSize, setLitterSize] = useState("");
  const motherNumber = mother?.number ?? null;
  const fatherNumber = father?.number ?? null;
  const birthDateIso =
    birthDate && !isNaN(birthDate.getTime()) ? formatDate(birthDate) : null;

  // Form state
  const [sex, setSex] = useState<string>("female");
  const [color, setColor] = useState("");
  const [name, setName] = useState("");
  const [colorNote, setColorNote] = useState("");
  const [eyeColor, setEyeColor] = useState("");
  const [clawColor, setClawColor] = useState("");
  const [bellyColor, setBellyColor] = useState("");
  const [hairNotes, setHairNotes] = useState("");
  // A rabbit is only registered with a certificate. From a litter row digital is issued
  // in the roster; the shortcut issues it at once, so it is the default there.
  const defaultCertificateType = shortcut ? "digital" : "paper";
  const [certificateType, setCertificateType] = useState<"paper" | "digital">(
    defaultCertificateType,
  );
  const [paperCertificate, setPaperCertificate] = useState("");
  // What the paper says, typed by the breeder before Stamboken's number is shown; never prefilled
  const [paperNumber, setPaperNumber] = useState("");
  const [numberCheck, setNumberCheck] = useState<NumberCheck | null>(null);
  const [conflict, setConflict] = useState<NumberCheck | null>(null);
  const [litterSize6w, setLitterSize6w] = useState("");
  const paper = certificateType === "paper";
  const paperNumberReady = PAPER_NUMBER.test(paperNumber.trim());

  // Number suggestion state
  const [suggestion, setSuggestion] =
    useState<IndividualNumberSuggestion | null>(null);
  // A new litter born before a numbered one gets no suggestion (409); on paper the
  // registration's number check still answers, with what the breeder must do
  const [litterOrder, setLitterOrder] = useState(false);
  const [isLoadingSuggestion, setIsLoadingSuggestion] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const [unlockDialogOpen, setUnlockDialogOpen] = useState(false);
  const [selectedPosition, setSelectedPosition] = useState<number | null>(null);

  // Touch-friendly info popover state: tracks which field's popover is open
  const [infoAnchor, setInfoAnchor] = useState<{
    el: HTMLElement;
    key: string;
  } | null>(null);

  // Result state
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<SuccessData | null>(null);

  const fetchSuggestion = useCallback(async () => {
    const litter =
      breedingId ??
      (motherNumber && fatherNumber && birthDateIso
        ? {
            mother: motherNumber,
            father: fatherNumber,
            birth_date: birthDateIso,
          }
        : null);
    if (litter === null) {
      setSuggestion(null);
      setLitterOrder(false);
      return;
    }
    setIsLoadingSuggestion(true);
    const result = await suggestIndividualNumber(litter);
    setIsLoadingSuggestion(false);
    if (result.success) {
      setSuggestion(result.data);
      setSelectedPosition(result.data.suggested_position);
      setLitterOrder(false);
      setError(null);
    } else {
      setSuggestion(null);
      setLitterOrder(result.errorTitle === "litter_order_conflict");
      setError(result.error);
    }
  }, [breedingId, motherNumber, fatherNumber, birthDateIso]);

  // Fetch suggestion when dialog opens
  useEffect(() => {
    if (open && !success) {
      fetchSuggestion();
    }
  }, [open, success, fetchSuggestion]);

  // Paper: Stamboken's number for what the paper says (the dry run), shown once it is typed
  useEffect(() => {
    const litter = breedingId
      ? { breeding_id: breedingId }
      : motherNumber && fatherNumber && birthDateIso
        ? {
            mother: motherNumber,
            father: fatherNumber,
            birth_date: birthDateIso,
          }
        : null;
    if (!open || !paper || !paperNumberReady || litter === null) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const result = await checkIndividualNumber({
        ...litter,
        paper_number: paperNumber.trim(),
      });
      if (!cancelled) setNumberCheck(result.success ? result.data : null);
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [
    open,
    paper,
    paperNumber,
    paperNumberReady,
    breedingId,
    motherNumber,
    fatherNumber,
    birthDateIso,
  ]);

  // The litter_size6w field lifts "litter_size6w_required": it is saved with the registration
  const canIssueCertificate =
    !!suggestion?.can_issue_certificate ||
    (suggestion?.certificate_blocked_reason === "litter_size6w_required" &&
      litterSize6w !== "");

  // The rabbit's fields; a shortcut litter stays for "Lägg till en till i kullen"
  const resetForm = () => {
    setSex("female");
    setColor("");
    setName("");
    setColorNote("");
    setEyeColor("");
    setClawColor("");
    setBellyColor("");
    setHairNotes("");
    setCertificateType(defaultCertificateType);
    setPaperCertificate("");
    setPaperNumber("");
    setNumberCheck(null);
    setConflict(null);
    if (!shortcut) setLitterSize6w("");
    setError(null);
    setSuccess(null);
    setUnlocked(false);
    setSuggestion(null);
    setSelectedPosition(null);
  };

  const translateBackendError = (raw: string): string => {
    // Map backend ValueError keys to localized messages
    const max = suggestion?.certified_max_count ?? 0;
    const used = suggestion?.certified_count ?? 0;
    switch (raw) {
      case "max_reached":
        return t("addRabbit.errorMaxReached");
      case "litter_size":
        return t("addRabbit.errorLitterSize");
      case "position_taken":
        return t("addRabbit.errorPositionTaken", {
          position: selectedPosition,
        });
      case "position_out_of_range":
        return t("addRabbit.errorPositionRange");
      case "litter_size6w_required":
        return t("addRabbit.errorLitterSize6wRequired");
      case "certificate_quota_exceeded":
        return t("addRabbit.errorCertificateQuotaExceeded", { max, used });
      case "roster_alive_exceeds_6w":
        return t("addRabbit.errorRosterOutOfSync");
      default:
        return raw;
    }
  };

  const handleSubmit = (resolution?: NumberResolution) => {
    setError(null);
    startTransition(async () => {
      const litter = breedingId
        ? { breeding_id: breedingId }
        : {
            mother: motherNumber!,
            father: fatherNumber!,
            birth_date: birthDateIso!,
            litter_size: parseInt(litterSize),
          };
      const result = await registerIndividual({
        ...litter,
        sex: sex === "unknown" ? null : sex,
        color,
        name: name || undefined,
        color_note: colorNote || undefined,
        eye_color: eyeColor || undefined,
        claw_color: clawColor || undefined,
        belly_color: bellyColor || undefined,
        hair_notes: hairNotes || undefined,
        certificate_type: certificateType,
        paper_certificate: paper ? paperCertificate : undefined,
        paper_number: paper ? paperNumber.trim() : undefined,
        resolution,
        litter_size6w: litterSize6w ? parseInt(litterSize6w) : undefined,
        // A paper certificate takes the paper's position (the API decides)
        position: unlocked && !paper ? selectedPosition : undefined,
      });
      if (result.success) {
        setConflict(null);
        const ind = result.data.individual;
        setSuccess({
          number: ind.number as string,
          name: (ind.name as string) || null,
          certificate_type: certificateType,
          digital_certificate:
            certificateType === "digital" ? result.data.certificate : null,
          certificate_error: result.data.certificate_error,
        });
      } else if (result.numberCheck) {
        setConflict(result.numberCheck);
      } else {
        setConflict(null);
        setError(translateBackendError(result.error));
      }
    });
  };

  const handleRegisterAnother = () => {
    resetForm();
    // useEffect will re-fetch suggestion since success becomes null
  };

  const handleUnlockClick = () => {
    setUnlockDialogOpen(true);
  };

  const handleUnlockConfirm = () => {
    setUnlocked(true);
    setUnlockDialogOpen(false);
  };

  const handleUnlockCancel = () => {
    setUnlockDialogOpen(false);
  };

  const handleRelock = () => {
    setUnlocked(false);
    setSelectedPosition(suggestion?.suggested_position ?? null);
  };

  const handleClose = () => {
    resetForm();
    setMother(null);
    setFather(null);
    setBirthDate(null);
    setLitterSize("");
    setLitterSize6w("");
    onClose();
  };

  const motherDisplay =
    breeding?.mother_name || breeding?.mother || t("pedigree.unknown");
  const fatherDisplay =
    breeding?.father_name || breeding?.father || t("pedigree.unknown");

  // The number that would be assigned right now (suggested or manually picked);
  // on paper Stamboken's number for what the paper says, never before it is typed
  const showUnlocked = unlocked && !paper;
  const previewNumber = (() => {
    if (!suggestion) return null;
    if (paper) return numberCheck?.stamboken_number ?? null;
    if (showUnlocked && selectedPosition != null) {
      // Compose locally from prefix knowledge: suggestion.suggested has format "{prefix}{pos}"
      // but if no suggested position exists we have no prefix. Strip last digit from any used position number.
      const sample = suggestion.suggested;
      if (sample) {
        return sample.slice(0, -1) + selectedPosition;
      }
      return null;
    }
    return suggestion.suggested;
  })();

  const dialogTitle = previewNumber
    ? t("addRabbit.titleWithNumber", { number: previewNumber })
    : shortcut
      ? t("addRabbit.shortcutTitle")
      : t("addRabbit.title");

  // Renders an info icon next to a field, opens touch-friendly Popover on click
  const FieldInfo = ({
    tooltipKey,
    label,
  }: {
    tooltipKey: string;
    label: string;
  }) => (
    <IconButton
      size="small"
      onClick={(e) => setInfoAnchor({ el: e.currentTarget, key: tooltipKey })}
      aria-label={label}
      sx={{ color: "text.secondary", p: 0.25, ml: 0.5 }}
    >
      <InfoOutlinedIcon fontSize="small" />
    </IconButton>
  );

  return (
    <Dialog
      open={open}
      onClose={(_event, reason) => {
        if (reason === "backdropClick" || reason === "escapeKeyDown") return;
        handleClose();
      }}
      maxWidth="sm"
      fullWidth
      fullScreen={isMobile}
      aria-labelledby="register-rabbit-title"
    >
      <DialogTitle id="register-rabbit-title" sx={{ pr: 6 }}>
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
      <DialogContent dividers={isMobile} sx={{ pt: isMobile ? 2 : undefined }}>
        {/* Litter context */}
        {breeding ? (
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              mb: 2.5,
            }}
          >
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
            <FieldInfo
              tooltipKey="addRabbit.litterNumberTooltip"
              label={t("addRabbit.litterNumber")}
            />
          </Box>
        ) : (
          <Typography variant="body2" sx={{ color: "text.secondary", mb: 2.5 }}>
            {t("addRabbit.shortcutHelp")}
          </Typography>
        )}

        <Divider sx={{ mb: 2.5 }} />

        {success ? (
          /* Success card */
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
                {t("addRabbit.registerAnother")}
              </Button>
              <Button
                component={Link}
                href={`/stamboken/individ/${encodeURIComponent(success.number)}`}
                variant="text"
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
          /* Registration form */
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

            {/* Shortcut: the litter, reused or created by the API */}
            {shortcut && (
              <LocalizationProvider
                dateAdapter={AdapterDateFns}
                adapterLocale={sv}
              >
                <IndividualAutocomplete
                  label={t("breeding.mother")}
                  sex="female"
                  genebankId={genebankId}
                  herdId={herdId}
                  value={mother}
                  onChange={setMother}
                  required
                />
                <IndividualAutocomplete
                  label={t("breeding.father")}
                  sex="male"
                  genebankId={genebankId}
                  herdId={herdId}
                  value={father}
                  onChange={setFather}
                  required
                />
                <DatePicker
                  label={t("breeding.birthDate")}
                  value={birthDate}
                  maxDate={new Date()}
                  onChange={setBirthDate}
                  slotProps={{
                    textField: {
                      size: "small",
                      fullWidth: true,
                      required: true,
                    },
                  }}
                />
                <Box sx={{ display: "flex", gap: 2 }}>
                  <TextField
                    label={t("breeding.totalBorn")}
                    value={litterSize}
                    onChange={(e) => setLitterSize(e.target.value)}
                    type="number"
                    size="small"
                    fullWidth
                    required
                    slotProps={{ htmlInput: { min: 1 } }}
                  />
                  <TextField
                    label={t("addRabbit.litterSize6w")}
                    value={litterSize6w}
                    onChange={(e) => setLitterSize6w(e.target.value)}
                    type="number"
                    size="small"
                    fullWidth
                    required
                    slotProps={{ htmlInput: { min: 1 } }}
                  />
                </Box>
                {suggestion?.breeding_id != null && (
                  <Typography variant="body2" sx={{ color: "text.secondary" }}>
                    {t("addRabbit.shortcutLitterFound", {
                      number: suggestion.litter_number,
                    })}
                  </Typography>
                )}
              </LocalizationProvider>
            )}

            {/* Individual number (locked or unlocked) */}
            {suggestion &&
              suggestion.can_register &&
              (!paper || previewNumber) && (
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
                    {t("addRabbit.individualNumber")}
                  </Typography>
                  <Typography
                    variant="body1"
                    sx={{
                      fontFamily: "monospace",
                      fontWeight: 600,
                      flexShrink: 0,
                    }}
                  >
                    {showUnlocked && previewNumber
                      ? previewNumber.slice(0, -1)
                      : previewNumber}
                  </Typography>
                  {showUnlocked && (
                    <FormControl size="small" sx={{ minWidth: 80 }}>
                      <Select
                        value={selectedPosition ?? ""}
                        onChange={(e) =>
                          setSelectedPosition(Number(e.target.value))
                        }
                        sx={{
                          fontFamily: "monospace",
                          fontWeight: 600,
                          "& .MuiSelect-select": { py: 0.5 },
                        }}
                        aria-label={t("addRabbit.positionLabel")}
                      >
                        {suggestion.available_positions.map((pos) => (
                          <MenuItem
                            key={pos}
                            value={pos}
                            sx={{ fontFamily: "monospace" }}
                          >
                            {pos}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  )}
                  <Box sx={{ flexGrow: 1 }} />
                  {!paper && (
                    <Tooltip
                      title={
                        unlocked
                          ? t("addRabbit.individualNumberLock")
                          : t("addRabbit.individualNumberUnlock")
                      }
                      arrow
                    >
                      <IconButton
                        onClick={unlocked ? handleRelock : handleUnlockClick}
                        size="small"
                        aria-label={
                          unlocked
                            ? t("addRabbit.individualNumberLock")
                            : t("addRabbit.individualNumberUnlock")
                        }
                      >
                        {unlocked ? (
                          <LockOpenIcon fontSize="small" />
                        ) : (
                          <LockIcon fontSize="small" />
                        )}
                      </IconButton>
                    </Tooltip>
                  )}
                </Box>
              )}

            {/* Capacity warning if litter is full */}
            {suggestion && !suggestion.can_register && !isLoadingSuggestion && (
              <Alert severity="warning">
                {suggestion.limited_by === "litter_size"
                  ? t("addRabbit.errorLitterSize")
                  : t("addRabbit.errorMaxReached")}
              </Alert>
            )}

            {/* Sex */}
            <FormControl size="small" fullWidth required>
              <InputLabel>{t("addRabbit.sex")}</InputLabel>
              <Select
                value={sex}
                onChange={(e) => setSex(e.target.value)}
                label={t("addRabbit.sex")}
              >
                <MenuItem value="female">{t("addRabbit.sexFemale")}</MenuItem>
                <MenuItem value="male">{t("addRabbit.sexMale")}</MenuItem>
                <MenuItem value="unknown">{t("addRabbit.sexUnknown")}</MenuItem>
              </Select>
            </FormControl>

            {/* Color */}
            <Box
              sx={{
                display: "flex",
                alignItems: "flex-start",
              }}
            >
              <TextField
                label={t("addRabbit.color")}
                value={color}
                onChange={(e) => setColor(e.target.value)}
                size="small"
                fullWidth
                required
              />
              <FieldInfo
                tooltipKey="addRabbit.colorTooltip"
                label={t("addRabbit.color")}
              />
            </Box>

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

            {/* Litter size 6w (conditional) */}
            {breeding && breeding.litter_size6w == null && (
              <Box
                sx={{
                  display: "flex",
                  alignItems: "flex-start",
                }}
              >
                <TextField
                  label={t("addRabbit.litterSize6w")}
                  value={litterSize6w}
                  onChange={(e) => setLitterSize6w(e.target.value)}
                  type="number"
                  size="small"
                  fullWidth
                  slotProps={{
                    htmlInput: { min: 0 },
                  }}
                />
                <FieldInfo
                  tooltipKey="addRabbit.litterSize6wTooltip"
                  label={t("addRabbit.litterSize6w")}
                />
              </Box>
            )}

            {/* Certificate type */}
            <Box>
              <Box
                sx={{
                  display: "flex",
                  alignItems: "flex-start",
                }}
              >
                <FormControl size="small" fullWidth required>
                  <InputLabel>{t("addRabbit.certificate")}</InputLabel>
                  <Select
                    value={certificateType}
                    onChange={(e) =>
                      setCertificateType(e.target.value as "paper" | "digital")
                    }
                    label={t("addRabbit.certificate")}
                  >
                    <MenuItem
                      value="paper"
                      disabled={!canIssueCertificate && !litterOrder}
                    >
                      {t("addRabbit.certificatePaper")}
                    </MenuItem>
                    <MenuItem
                      value="digital"
                      disabled={!shortcut || !canIssueCertificate}
                    >
                      <Box
                        sx={{
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "flex-start",
                        }}
                      >
                        <Typography variant="body2">
                          {t("addRabbit.certificateDigital")}
                        </Typography>
                        {!shortcut && (
                          <Typography
                            variant="caption"
                            sx={{
                              color: "text.secondary",
                            }}
                          >
                            {t("addRabbit.certificateDigitalDisabled")}
                          </Typography>
                        )}
                      </Box>
                    </MenuItem>
                  </Select>
                </FormControl>
                <FieldInfo
                  tooltipKey={
                    shortcut
                      ? "addRabbit.certificateTooltipShortcut"
                      : "addRabbit.certificateTooltip"
                  }
                  label={t("addRabbit.certificate")}
                />
              </Box>
              {suggestion && !canIssueCertificate && (
                <Typography
                  variant="caption"
                  sx={{
                    color: "text.secondary",
                    display: "block",
                    mt: 0.5,
                    ml: 1.5,
                  }}
                >
                  {suggestion.certificate_blocked_reason ===
                  "litter_size6w_required"
                    ? t("addRabbit.errorLitterSize6wRequired")
                    : t("addRabbit.errorCertificateQuotaExceeded", {
                        max: suggestion.certified_max_count ?? 0,
                        used: suggestion.certified_count,
                      })}
                </Typography>
              )}
            </Box>

            {/* Paper certificate number */}
            {certificateType === "paper" && (
              <Box
                sx={{
                  display: "flex",
                  alignItems: "flex-start",
                }}
              >
                <TextField
                  label={t("addRabbit.paperCertificateNumber")}
                  value={paperCertificate}
                  onChange={(e) => setPaperCertificate(e.target.value)}
                  size="small"
                  fullWidth
                  required
                />
                <FieldInfo
                  tooltipKey="addRabbit.paperCertificateNumberTooltip"
                  label={t("addRabbit.paperCertificateNumber")}
                />
              </Box>
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
            fullWidth={isMobile}
            size={isMobile ? "large" : "medium"}
          >
            {t("addRabbit.cancel")}
          </Button>
          <Button
            onClick={() => handleSubmit()}
            variant="contained"
            disabled={
              isPending ||
              !color ||
              (!(suggestion?.can_register && canIssueCertificate) &&
                !(litterOrder && paper)) ||
              (shortcut && (!litterSize || !litterSize6w)) ||
              (paper && (!paperCertificate || !paperNumberReady)) ||
              (showUnlocked && selectedPosition == null)
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
          <Button onClick={handleClose}>{t("common.cancel")}</Button>
        </DialogActions>
      )}

      {conflict && (
        <NumberConflictDialog
          check={conflict}
          isSaving={isPending}
          onUseStambokenNumber={() =>
            handleSubmit({
              expected_number: conflict.stamboken_number,
              choice: "use_stamboken_number",
            })
          }
          onClose={() => setConflict(null)}
        />
      )}

      {/* Unlock confirmation sub-dialog */}
      <Dialog
        open={unlockDialogOpen}
        onClose={handleUnlockCancel}
        aria-labelledby="unlock-individual-number-title"
      >
        <DialogTitle id="unlock-individual-number-title">
          {t("addRabbit.unlockTitle")}
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            {t("addRabbit.unlockBody", {
              number: suggestion?.suggested ?? "?",
            })}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleUnlockCancel} variant="contained">
            {t("addRabbit.unlockCancel", {
              number: suggestion?.suggested ?? "?",
            })}
          </Button>
          <Button onClick={handleUnlockConfirm} color="warning">
            {t("addRabbit.unlockConfirm")}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Global info-popover for per-field help texts */}
      <Popover
        open={Boolean(infoAnchor)}
        anchorEl={infoAnchor?.el}
        onClose={() => setInfoAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <Box sx={{ p: 2, maxWidth: 320 }}>
          <Typography variant="body2">
            {infoAnchor ? t(infoAnchor.key) : ""}
          </Typography>
        </Box>
      </Popover>
    </Dialog>
  );
}
