"use client";

import React, { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Grid,
  Link as MuiLink,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import { sv as svLocale } from "date-fns/locale";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useTranslation } from "react-i18next";
import {
  checkLitterOrder,
  renumberLitters,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";
import styles from "@/app/(app)/stamboken/(dashboard)/min-besattning/min-besattning.module.css";
import { LitterRoster } from "./LitterRoster";

const RegisterRabbitDialog = dynamic(
  () => import("./RegisterRabbitDialog").then((m) => m.RegisterRabbitDialog),
  { ssr: false },
);
const LitterNumberConflictDialog = dynamic(
  () =>
    import("./LitterNumberConflictDialog").then(
      (m) => m.LitterNumberConflictDialog,
    ),
  { ssr: false },
);

interface BreedingListProps {
  breedings: any[];
  isLoading: boolean;
  onDelete?: (breedingId: number) => void;
  isDeletingId?: number | null;
  onRegisterFirst?: () => void;
  onRegisterBirth?: (data: {
    breedingId: number;
    date: string;
    litter_size: number;
    litter_size6w?: number | null;
    notes?: string;
  }) => Promise<boolean>;
  onUpdate?: (data: {
    id: number;
    breeding_herd: string;
    breed_date?: string;
    breed_notes?: string;
    birth_date?: string;
    birth_notes?: string;
    litter_size?: number | null;
    litter_size6w?: number | null;
  }) => Promise<boolean>;
  canEdit?: boolean;
  herdId?: string;
}

/** Pending matings first, then litters grouped by birth year, as expandable cards */
export function BreedingList({
  breedings,
  isLoading,
  onDelete,
  isDeletingId,
  onRegisterFirst,
  onRegisterBirth,
  onUpdate,
  canEdit,
  herdId,
}: BreedingListProps) {
  const { t } = useTranslation();
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [birthFormId, setBirthFormId] = useState<number | null>(null);
  const [birthDate, setBirthDate] = useState<Date | null>(new Date());
  const [litterSize, setLitterSize] = useState("");
  const [litterSize6w, setLitterSize6w] = useState("");
  const [birthNotes, setBirthNotes] = useState("");
  const [isSubmittingBirth, setIsSubmittingBirth] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [editBreedDate, setEditBreedDate] = useState<Date | null>(null);
  const [editBirthDate, setEditBirthDate] = useState<Date | null>(null);
  const [editLitterSize, setEditLitterSize] = useState("");
  const [editLitterSize6w, setEditLitterSize6w] = useState("");
  const [editBreedNotes, setEditBreedNotes] = useState("");
  const [editBirthNotes, setEditBirthNotes] = useState("");
  const [isSubmittingEdit, setIsSubmittingEdit] = useState(false);
  const [registerBreedingId, setRegisterBreedingId] = useState<number | null>(
    null,
  );
  const [conflictData, setConflictData] = useState<{
    conflicts: any[];
    // null when the conflict was detected right after a birth registration —
    // there is no pending rabbit registration to resume after renumbering.
    pendingBreedingId: number | null;
  } | null>(null);
  const [isRenumbering, setIsRenumbering] = useState(false);
  const [renumberError, setRenumberError] = useState<string | null>(null);
  // Captured once at mount — stable age-gate reference (avoids hydration mismatch)
  const [nowMs] = useState(() => Date.now());
  const [guideDismissed, setGuideDismissed] = useState(true);

  React.useEffect(() => {
    setGuideDismissed(localStorage.getItem("litterGuideDismissed") === "1");
  }, []);

  const dismissGuide = () => {
    localStorage.setItem("litterGuideDismissed", "1");
    setGuideDismissed(true);
  };

  const handleRegisterClick = async (b: any) => {
    if (!herdId || !b.birth_date) return;
    const year = new Date(b.birth_date).getFullYear();
    const result = await checkLitterOrder(herdId, year);
    if (result.success && !result.data.consistent) {
      setConflictData({
        conflicts: result.data.conflicts as any[],
        pendingBreedingId: b.id,
      });
    } else {
      setRegisterBreedingId(b.id);
    }
  };

  const handleRenumberConfirm = async () => {
    if (!conflictData || !herdId) return;
    const year = parseInt(
      conflictData.conflicts[0]?.birth_date?.substring(0, 4) || "0",
    );
    setIsRenumbering(true);
    setRenumberError(null);
    const result = await renumberLitters(herdId, year, true);
    setIsRenumbering(false);
    if (result.success) {
      if (conflictData.pendingBreedingId != null) {
        setRegisterBreedingId(conflictData.pendingBreedingId);
      }
      setConflictData(null);
    } else {
      setRenumberError(
        result.errorStatus === 403
          ? t("addRabbit.conflict.renumberManagerRequired")
          : t("addRabbit.conflict.renumberFailed"),
      );
    }
  };

  const startEdit = (b: any) => {
    setEditId(b.id);
    setExpandedId(b.id);
    setBirthFormId(null);
    setEditBreedDate(b.breed_date ? new Date(b.breed_date) : null);
    setEditBirthDate(b.birth_date ? new Date(b.birth_date) : null);
    setEditLitterSize(b.litter_size != null ? String(b.litter_size) : "");
    setEditLitterSize6w(b.litter_size6w != null ? String(b.litter_size6w) : "");
    setEditBreedNotes(b.breed_notes || "");
    setEditBirthNotes(b.birth_notes || "");
  };

  const resetEdit = () => {
    setEditId(null);
  };

  const handleEditSubmit = async (b: any) => {
    if (!onUpdate) return;
    const fmt = (d: Date | null) => {
      if (!d) return undefined;
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      return `${yyyy}-${mm}-${dd}`;
    };
    setIsSubmittingEdit(true);
    const success = await onUpdate({
      id: b.id,
      breeding_herd: b.breeding_herd,
      breed_date: fmt(editBreedDate),
      breed_notes: editBreedNotes,
      birth_date: fmt(editBirthDate),
      birth_notes: editBirthNotes,
      litter_size: editLitterSize ? parseInt(editLitterSize) : null,
      litter_size6w: editLitterSize6w ? parseInt(editLitterSize6w) : null,
    });
    setIsSubmittingEdit(false);
    if (success) resetEdit();
  };

  const resetBirthForm = () => {
    setBirthFormId(null);
    setBirthDate(new Date());
    setLitterSize("");
    setLitterSize6w("");
    setBirthNotes("");
  };

  const handleBirthSubmit = async (breedingId: number) => {
    if (!onRegisterBirth || !birthDate || !litterSize) return;
    const yyyy = birthDate.getFullYear();
    const mm = String(birthDate.getMonth() + 1).padStart(2, "0");
    const dd = String(birthDate.getDate()).padStart(2, "0");
    setIsSubmittingBirth(true);
    const success = await onRegisterBirth({
      breedingId,
      date: `${yyyy}-${mm}-${dd}`,
      litter_size: parseInt(litterSize),
      litter_size6w: litterSize6w ? parseInt(litterSize6w) : null,
      notes: birthNotes || undefined,
    });
    setIsSubmittingBirth(false);
    if (success) {
      resetBirthForm();
      // An out-of-order birth is appended at the end of the number series;
      // surface the renumber dialog right away instead of at register time.
      if (herdId) {
        const check = await checkLitterOrder(herdId, yyyy);
        if (check.success && !check.data.consistent) {
          setConflictData({
            conflicts: check.data.conflicts as any[],
            pendingBreedingId: null,
          });
        }
      }
    }
  };

  // Matings (no birth yet) get their own leading section per the handoff;
  // litters group by birth year, newest year first, newest first within year.
  const { matings, litterYears } = useMemo(() => {
    const pendingMatings = breedings
      .filter((b: any) => !b.birth_date)
      .sort((a: any, b: any) =>
        (a.breed_date || "").localeCompare(b.breed_date || ""),
      );
    const groups: Record<string, any[]> = {};
    for (const b of breedings) {
      if (!b.birth_date) continue;
      const year = b.birth_date.substring(0, 4);
      if (!groups[year]) groups[year] = [];
      groups[year].push(b);
    }
    for (const items of Object.values(groups)) {
      items.sort((a: any, b: any) =>
        (b.birth_date || "").localeCompare(a.birth_date || ""),
      );
    }
    return {
      matings: pendingMatings,
      litterYears: Object.entries(groups).sort(([a], [b]) =>
        b.localeCompare(a),
      ),
    };
  }, [breedings]);

  const handleToggle = (id: number) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  if (isLoading) {
    return (
      <Box
        sx={{
          display: "flex",
          justifyContent: "center",
          p: 4,
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  if (breedings.length === 0) {
    return (
      <div className={styles["mb-empty"]}>
        <p style={{ margin: 0 }}>{t("breeding.noBreedings")}</p>
        {onRegisterFirst && (
          <button
            type="button"
            className="sb-btn sb-btn-secondary"
            style={{ marginTop: 16 }}
            onClick={onRegisterFirst}
          >
            {t("breeding.registerFirst")}
          </button>
        )}
      </div>
    );
  }

  /** Render a clickable individual link */
  const IndividualLink = ({
    number,
    name,
  }: {
    number: string | null;
    name?: string | null;
  }) =>
    !number ? (
      <span>Okänd</span>
    ) : (
      <MuiLink
        component={Link}
        href={`/stamboken/individ/${encodeURIComponent(number)}`}
        underline="hover"
        color="inherit"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
        sx={{ fontWeight: "inherit", "&:hover": { color: "primary.main" } }}
      >
        {name || number}
      </MuiLink>
    );

  const renderBreedingCard = (b: any) => {
    const isExpanded = expandedId === b.id;
    const isMatingOnly = !b.birth_date;
    const hasNotes = b.breed_notes || b.birth_notes;
    const hasBothDates = b.breed_date && b.birth_date;
    const offspring = b.individuals || [];
    const canDelete = offspring.length === 0;
    const isDeleting = isDeletingId === b.id;
    const gestation =
      isMatingOnly && b.breed_date
        ? (() => {
            const day = Math.floor(
              (nowMs - new Date(b.breed_date).getTime()) / 86400000,
            );
            return {
              day,
              pct: Math.min(100, Math.round((day / 31) * 100)),
              due: new Date(new Date(b.breed_date).getTime() + 31 * 86400000)
                .toISOString()
                .slice(0, 10),
            };
          })()
        : null;

    return (
      <article
        key={b.id}
        data-testid="breeding-card"
        className={`sb-card ${styles["mb-breeding-card"]}${
          isMatingOnly ? ` ${styles["is-mating"]}` : ""
        }`}
        onClick={() => handleToggle(b.id)}
      >
        {/* Summary row — the whole card stays clickable as before; the chevron
            stays a real button so getByRole("button", { name: "Detaljer" })
            keeps working */}
        <div className={styles["mb-breeding-summary"]}>
          <span className={styles["mb-breeding-title"]}>
            <span className={styles["mb-row-name"]}>
              <IndividualLink number={b.mother} name={b.mother_name} /> ×{" "}
              <IndividualLink number={b.father} name={b.father_name} />
            </span>
            <span className="sb-meta">
              {b.mother && b.mother_name ? `${b.mother} × ${b.father} · ` : ""}
              {b.birth_date
                ? `${t("breeding.born")} ${b.birth_date}`
                : b.breed_date
                  ? `${t("breeding.mating")} ${b.breed_date}`
                  : ""}
            </span>
          </span>
          <span className={styles["mb-breeding-chips"]}>
            {isMatingOnly ? (
              <span className="sb-badge sb-badge-lera">
                {t("breeding.matingStatus")}
              </span>
            ) : (
              <>
                {b.litter_number != null && (
                  <Tooltip title={t("breeding.litterChipTooltip")} arrow>
                    <span className="sb-badge sb-badge-skog">
                      {t("breeding.litterChip", { number: b.litter_number })}
                    </span>
                  </Tooltip>
                )}
                {b.litter_size != null && (
                  <span className="sb-badge">
                    {b.litter_size} {t("breeding.litterSize")}
                    {b.litter_size6w != null
                      ? `, ${b.litter_size6w} ${t("breeding.aliveAt6wShort")}`
                      : ""}
                  </span>
                )}
                {b.breed_date &&
                  b.birth_date &&
                  (() => {
                    const days = Math.round(
                      (new Date(b.birth_date).getTime() -
                        new Date(b.breed_date).getTime()) /
                        86400000,
                    );
                    return days > 0 ? (
                      <span className={`sb-badge ${styles["mb-hide-sm"]}`}>
                        {days} {t("breeding.gestationDays")}
                      </span>
                    ) : null;
                  })()}
              </>
            )}
          </span>
          <button
            type="button"
            className={`${styles["mb-caret"]}${
              isExpanded ? ` ${styles["is-open"]}` : ""
            }`}
            aria-label={t("breeding.details")}
            aria-expanded={isExpanded}
            onClick={(e) => {
              e.stopPropagation();
              handleToggle(b.id);
            }}
          >
            ›
          </button>
        </div>

        {/* Gestation strip on current matings (prototype isCurrent: day <= 35) */}
        {isMatingOnly && gestation && gestation.day <= 35 && (
          <div className={styles["mb-breeding-gestation"]}>
            <div className={styles["mb-progress"]}>
              <div
                className={styles["mb-progress-fill"]}
                style={{ width: `${gestation.pct}%` }}
              />
            </div>
            <span className="sb-meta">
              dag {gestation.day} av 31 · beräknad kull {gestation.due}
            </span>
          </div>
        )}

        {isExpanded && (
          <div className={styles["mb-breeding-detail"]}>
            {/* Inline edit form */}
            {editId === b.id && onUpdate ? (
              <LocalizationProvider
                dateAdapter={AdapterDateFns}
                adapterLocale={svLocale}
              >
                <Box
                  onClick={(e) => e.stopPropagation()}
                  sx={{
                    p: 2,
                    border: 1,
                    borderColor: "primary.main",
                    borderRadius: 1,
                    backgroundColor: "background.paper",
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{
                      fontWeight: "bold",
                      display: "block",
                      mb: 1,
                    }}
                  >
                    {t("breeding.editTitle")}
                  </Typography>
                  <Grid container spacing={1}>
                    <Grid size={{ xs: 12, sm: 4 }}>
                      <DatePicker
                        label={t("breeding.matingDate")}
                        value={editBreedDate}
                        maxDate={new Date()}
                        onChange={setEditBreedDate}
                        slotProps={{
                          textField: {
                            size: "small",
                            fullWidth: true,
                          },
                        }}
                      />
                    </Grid>
                    <Grid size={{ xs: 12, sm: 4 }}>
                      <DatePicker
                        label={t("breeding.birthDate")}
                        value={editBirthDate}
                        maxDate={new Date()}
                        onChange={setEditBirthDate}
                        slotProps={{
                          textField: {
                            size: "small",
                            fullWidth: true,
                          },
                        }}
                      />
                    </Grid>
                    <Grid size={{ xs: 6, sm: 2 }}>
                      <TextField
                        label={t("breeding.totalBorn")}
                        type="number"
                        size="small"
                        fullWidth
                        value={editLitterSize}
                        onChange={(e) => setEditLitterSize(e.target.value)}
                        slotProps={{
                          htmlInput: { min: 0 },
                        }}
                      />
                    </Grid>
                    <Grid size={{ xs: 6, sm: 2 }}>
                      <TextField
                        label={t("breeding.aliveAt6w")}
                        type="number"
                        size="small"
                        fullWidth
                        value={editLitterSize6w}
                        onChange={(e) => setEditLitterSize6w(e.target.value)}
                        slotProps={{
                          htmlInput: { min: 0 },
                        }}
                      />
                    </Grid>
                    <Grid size={{ xs: 12, sm: 6 }}>
                      <TextField
                        label={t("breeding.breedNotes")}
                        size="small"
                        fullWidth
                        value={editBreedNotes}
                        onChange={(e) => setEditBreedNotes(e.target.value)}
                      />
                    </Grid>
                    <Grid size={{ xs: 12, sm: 6 }}>
                      <TextField
                        label={t("breeding.birthNotes")}
                        size="small"
                        fullWidth
                        value={editBirthNotes}
                        onChange={(e) => setEditBirthNotes(e.target.value)}
                      />
                    </Grid>
                  </Grid>
                  <Box
                    sx={{
                      display: "flex",
                      gap: 1,
                      justifyContent: "flex-end",
                      mt: 1,
                    }}
                  >
                    <Button
                      size="small"
                      onClick={resetEdit}
                      disabled={isSubmittingEdit}
                      sx={{ minHeight: 44 }}
                    >
                      {t("common.cancel")}
                    </Button>
                    <Button
                      size="small"
                      variant="contained"
                      sx={{ minHeight: 44 }}
                      disabled={isSubmittingEdit}
                      onClick={() => handleEditSubmit(b)}
                    >
                      {isSubmittingEdit ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : (
                        t("common.save")
                      )}
                    </Button>
                  </Box>
                </Box>
              </LocalizationProvider>
            ) : (
              <>
                {/* Read-only detail view */}
                {hasBothDates && (
                  <p className="sb-meta" style={{ margin: 0 }}>
                    {t("breeding.mating")}: {b.breed_date} &rarr;{" "}
                    {t("breeding.born")}: {b.birth_date}
                  </p>
                )}
                {b.breed_notes && (
                  <p
                    style={{
                      margin: "4px 0 0",
                      fontSize: 14,
                      color: "var(--sb-ink-2)",
                    }}
                  >
                    {b.breed_notes}
                  </p>
                )}
                {b.birth_notes && (
                  <p
                    style={{
                      margin: "4px 0 0",
                      fontSize: 14,
                      color: "var(--sb-ink-2)",
                    }}
                  >
                    {b.birth_notes}
                  </p>
                )}
              </>
            )}

            {/* Offspring list with clickable links */}
            {offspring.length > 0 && (
              <Box sx={{ mt: 1 }}>
                <span className="sb-eyebrow" style={{ letterSpacing: "0.1em" }}>
                  {t("breeding.offspring")} ({offspring.length})
                </span>
                <div className={styles["mb-offspring"]}>
                  {offspring.map((ind: any) => (
                    <Link
                      key={ind.number || ind.id}
                      className="sb-link"
                      href={`/stamboken/individ/${encodeURIComponent(ind.number)}`}
                      onClick={(e: React.MouseEvent) => e.stopPropagation()}
                    >
                      {ind.number}
                      {ind.name ? ` – ${ind.name}` : ""}
                      {ind.sex
                        ? ` (${ind.sex === "female" ? "♀" : "♂"})`
                        : ""}
                    </Link>
                  ))}
                </div>
              </Box>
            )}

            {!hasNotes &&
              !hasBothDates &&
              offspring.length === 0 &&
              !isMatingOnly && (
                <p className="sb-meta" style={{ margin: 0 }}>
                  —
                </p>
              )}

            {/* Litter roster — Phase 15: per-bunny roster + promote flow.
                The existing "Lägg till kanin" button below is kept for the
                legacy registerIndividual flow which registers without
                a roster slot. Both flows coexist until the old button is
                explicitly removed in a follow-up. */}
            {canEdit && !isMatingOnly && herdId && isExpanded && (
              <Box onClick={(e) => e.stopPropagation()}>
                <LitterRoster breeding={b} herdId={herdId} />
              </Box>
            )}

            {/* Register birth — inline form for mating-only entries (hidden during edit) */}
            {isMatingOnly && onRegisterBirth && editId !== b.id && (
              <Box
                sx={{ mt: hasNotes ? 1 : 0 }}
                onClick={(e) => e.stopPropagation()}
              >
                {birthFormId === b.id ? (
                  <LocalizationProvider
                    dateAdapter={AdapterDateFns}
                    adapterLocale={svLocale}
                  >
                    <Box
                      sx={{
                        p: 2,
                        border: 1,
                        borderColor: "primary.main",
                        borderRadius: 1,
                        backgroundColor: "background.paper",
                      }}
                    >
                      <Typography
                        variant="caption"
                        sx={{
                          fontWeight: "bold",
                          display: "block",
                          mb: 1,
                        }}
                      >
                        {t("breeding.registerBirthAction")}
                      </Typography>
                      <Grid container spacing={1}>
                        <Grid size={{ xs: 12, sm: 4 }}>
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
                        </Grid>
                        <Grid size={{ xs: 6, sm: 2 }}>
                          <TextField
                            label={t("breeding.totalBorn")}
                            type="number"
                            size="small"
                            fullWidth
                            required
                            value={litterSize}
                            onChange={(e) => setLitterSize(e.target.value)}
                            slotProps={{
                              htmlInput: { min: 1 },
                            }}
                          />
                        </Grid>
                        <Grid size={{ xs: 6, sm: 2 }}>
                          <TextField
                            label={t("breeding.aliveAt6w")}
                            type="number"
                            size="small"
                            fullWidth
                            value={litterSize6w}
                            onChange={(e) => setLitterSize6w(e.target.value)}
                            slotProps={{
                              htmlInput: { min: 0 },
                            }}
                          />
                        </Grid>
                        <Grid size={{ xs: 12, sm: 4 }}>
                          <TextField
                            label={t("breeding.birthNotes")}
                            size="small"
                            fullWidth
                            value={birthNotes}
                            onChange={(e) => setBirthNotes(e.target.value)}
                          />
                        </Grid>
                      </Grid>
                      <Box
                        sx={{
                          display: "flex",
                          gap: 1,
                          justifyContent: "flex-end",
                          mt: 1,
                        }}
                      >
                        <Button
                          size="small"
                          onClick={resetBirthForm}
                          disabled={isSubmittingBirth}
                          sx={{ minHeight: 44 }}
                        >
                          {t("common.cancel")}
                        </Button>
                        <Button
                          size="small"
                          variant="contained"
                          sx={{ minHeight: 44 }}
                          disabled={
                            !birthDate ||
                            !litterSize ||
                            parseInt(litterSize) <= 0 ||
                            isSubmittingBirth
                          }
                          onClick={() => handleBirthSubmit(b.id)}
                        >
                          {isSubmittingBirth ? (
                            <CircularProgress size={16} color="inherit" />
                          ) : (
                            t("common.save")
                          )}
                        </Button>
                      </Box>
                    </Box>
                  </LocalizationProvider>
                ) : (
                  <button
                    type="button"
                    className="sb-btn sb-btn-sm"
                    onClick={() => {
                      setBirthFormId(b.id);
                      setExpandedId(b.id);
                    }}
                  >
                    {t("breeding.registerBirthAction")}
                  </button>
                )}
              </Box>
            )}

            {/* Register rabbit button — same 42-day gate as the roster */}
            {canEdit &&
              !isMatingOnly &&
              herdId &&
              (() => {
                const birthMs = b.birth_date
                  ? new Date(b.birth_date).getTime()
                  : NaN;
                const ageDays = Number.isNaN(birthMs)
                  ? null
                  : Math.floor((nowMs - birthMs) / 86400000);
                const tooYoung = ageDays != null && ageDays < 42;
                return (
                  <Box sx={{ mt: 1 }} onClick={(e) => e.stopPropagation()}>
                    <Tooltip
                      title={
                        tooYoung
                          ? t("litterRoster.registerDisabledAge", {
                              days: 42 - (ageDays ?? 0),
                            })
                          : ""
                      }
                      arrow
                      disableHoverListener={!tooYoung}
                    >
                      <span>
                        <button
                          type="button"
                          className="sb-btn sb-btn-secondary sb-btn-sm"
                          disabled={tooYoung}
                          onClick={() => handleRegisterClick(b)}
                        >
                          {t("addRabbit.title")}
                        </button>
                      </span>
                    </Tooltip>
                  </Box>
                );
              })()}

            {/* Action buttons: Edit + Delete */}
            {editId !== b.id && (onUpdate || (onDelete && canDelete)) && (
              <div className={styles["mb-breeding-actions"]}>
                {onUpdate && (
                  <button
                    type="button"
                    className="sb-btn sb-btn-ghost sb-btn-sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      startEdit(b);
                    }}
                  >
                    {t("breeding.edit")}
                  </button>
                )}
                {onDelete && canDelete && (
                  <Tooltip title={t("breeding.deleteTooltip")} arrow>
                    <button
                      type="button"
                      className="sb-btn sb-btn-ghost sb-btn-sm"
                      style={{ color: "var(--sb-danger)" }}
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(b.id);
                      }}
                      disabled={isDeleting}
                    >
                      {isDeleting ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : (
                        t("common.delete")
                      )}
                    </button>
                  </Tooltip>
                )}
              </div>
            )}

            {/* Show why delete is disabled */}
            {onDelete && !canDelete && (
              <Box
                sx={{
                  mt: 1,
                  pt: 1,
                  borderTop: 1,
                  borderColor: "divider",
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    color: "text.disabled",
                  }}
                >
                  {t("breeding.cannotDelete", {
                    count: offspring.length,
                  })}
                </Typography>
              </Box>
            )}
          </div>
        )}
      </article>
    );
  };

  return (
    <Box>
      {/* In-page guide: how the litter flow works (dismissible, Story 9.2 pattern) */}
      {!guideDismissed && (
        <Alert
          severity="info"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={dismissGuide}>
              {t("litterGuide.dismiss")}
            </Button>
          }
        >
          <Typography variant="subtitle2" sx={{ mb: 0.75 }}>
            {t("litterGuide.title")}
          </Typography>
          <Box
            sx={{
              display: "flex",
              flexDirection: "column",
              gap: 0.75,
            }}
          >
            {([1, 2, 3] as const).map((n) => (
              <Box
                key={n}
                sx={{
                  display: "flex",
                  gap: 1,
                  alignItems: "flex-start",
                }}
              >
                <Box
                  sx={{
                    width: 20,
                    height: 20,
                    borderRadius: "50%",
                    bgcolor: "info.main",
                    color: "info.contrastText",
                    fontSize: 12,
                    fontWeight: 700,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                    mt: 0.25,
                  }}
                >
                  {n}
                </Box>
                <Typography variant="body2">
                  {t(`litterGuide.step${n}`)}
                </Typography>
              </Box>
            ))}
          </Box>
        </Alert>
      )}

      {matings.length > 0 && (
        <section className={styles["mb-year-group"]}>
          <div className={styles["mb-year-head"]}>
            <span
              className={`${styles["mb-year"]} ${styles["mb-year-sm"]}`}
              data-testid="year-heading"
            >
              Pågående parningar
            </span>
            <hr className="sb-rule" style={{ flex: 1, margin: 0 }} />
            <span className="sb-meta">{matings.length} väntar på kull</span>
          </div>
          <p className="sb-meta" style={{ margin: "0 0 10px" }}>
            Blir kullar först när födsel registrerats.
          </p>
          <div className={styles["mb-stack"]} style={{ gap: 10 }}>
            {matings.map(renderBreedingCard)}
          </div>
        </section>
      )}

      {litterYears.map(([year, items]) => (
        <section key={year} className={styles["mb-year-group"]}>
          <div className={styles["mb-year-head"]}>
            <span className={styles["mb-year"]} data-testid="year-heading">
              {year}
            </span>
            <hr className="sb-rule" style={{ flex: 1, margin: 0 }} />
            <span className="sb-meta">
              {items.length} {items.length === 1 ? "kull" : "kullar"}
            </span>
          </div>
          <div className={styles["mb-stack"]} style={{ gap: 10 }}>
            {items.map(renderBreedingCard)}
          </div>
        </section>
      ))}

      {/* Registration dialog */}
      {registerBreedingId != null && herdId && (
        <RegisterRabbitDialog
          breeding={
            breedings.find((b) => b.id === registerBreedingId) || {
              id: registerBreedingId,
            }
          }
          herdId={herdId}
          open
          onClose={() => setRegisterBreedingId(null)}
        />
      )}

      {/* Conflict resolution dialog */}
      {conflictData && (
        <LitterNumberConflictDialog
          conflicts={conflictData.conflicts}
          open
          onConfirm={handleRenumberConfirm}
          onClose={() => {
            setConflictData(null);
            setRenumberError(null);
          }}
          isRenumbering={isRenumbering}
          error={renumberError}
        />
      )}
    </Box>
  );
}
