"use client";

import React, { useState, useEffect, useTransition, useCallback } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Snackbar,
  Tooltip,
} from "@mui/material";
import EditIcon from "@mui/icons-material/Edit";
import {
  DragDropContext,
  Droppable,
  Draggable,
  DropResult,
} from "@hello-pangea/dnd";
import { useTranslation } from "react-i18next";
import dynamic from "next/dynamic";
import {
  getLitterRoster,
  addBunnies,
  patchBunny,
  reorderRoster,
  type RosterBunny,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";
import { MbSex } from "@/app/(app)/stamboken/(dashboard)/min-besattning/min-besattning-ui";
import styles from "@/app/(app)/stamboken/(dashboard)/min-besattning/min-besattning.module.css";

const BunnyPromoteDialog = dynamic(
  () => import("./BunnyPromoteDialog").then((m) => m.BunnyPromoteDialog),
  { ssr: false },
);
const BunnyEditDialog = dynamic(
  () => import("./BunnyEditDialog").then((m) => m.BunnyEditDialog),
  { ssr: false },
);

interface LitterRosterProps {
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
    breeding_herd?: string | null;
  };
  herdId: string;
}

/* Fate options in the inline select — same order as the handoff prototype */
const FATE_OPTIONS = [
  "undecided",
  "kept_unregistered",
  "sold_unregistered",
  "culled",
  "died",
] as const;

export function LitterRoster({ breeding, herdId }: LitterRosterProps) {
  const { t } = useTranslation();
  const [roster, setRoster] = useState<RosterBunny[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [reorderError, setReorderError] = useState<string | null>(null);
  // number while typing, or "" transiently so the field can be cleared and
  // retyped (see the addCount TextField); falls back to 1 on blur/submit.
  const [addCount, setAddCount] = useState<number | "">(1);
  const [isPending, startTransition] = useTransition();
  const [promoteBunnyId, setPromoteBunnyId] = useState<number | null>(null);
  const [editBunnyId, setEditBunnyId] = useState<number | null>(null);
  // A just-deleted bunny, kept around so "Ångra" can recreate it in place
  const [pendingUndo, setPendingUndo] = useState<{
    bunny: RosterBunny;
    index: number;
  } | null>(null);
  // Kits picked to be marked Död (null: not choosing)
  const [markDeadIds, setMarkDeadIds] = useState<number[] | null>(null);
  // Captured once at mount — stable for age-gate checks (no re-render on clock tick needed)
  const [nowMs] = useState(Date.now);

  const fetchRoster = useCallback(async () => {
    setIsLoading(true);
    setFetchError(null);
    try {
      const result = await getLitterRoster(breeding.id);
      if (result.success) {
        setRoster(result.data);
      } else {
        setFetchError(result.error);
      }
    } catch {
      setFetchError(t("litterRoster.errorFetch"));
    } finally {
      setIsLoading(false);
    }
  }, [breeding.id, t]);

  useEffect(() => {
    fetchRoster();
  }, [fetchRoster]);

  // Age check: disable Registrera if < 42 days (6 weeks) from birth_date
  const birthDateMs = breeding.birth_date
    ? new Date(breeding.birth_date).getTime()
    : null;
  const ageInDays =
    birthDateMs != null ? Math.floor((nowMs - birthDateMs) / 86400000) : null;
  const isTooYoung = ageInDays != null && ageInDays < 42;
  const daysUntilRegister =
    isTooYoung && ageInDays != null ? 42 - ageInDays : 0;

  // The roster can't grow past the reported litter size ("born"); litters
  // without a recorded size (legacy data) stay capped only by the per-request
  // limit of 20.
  const litterSize = breeding.litter_size ?? null;
  const remaining =
    litterSize != null ? Math.max(0, litterSize - roster.length) : null;
  const maxAdd = remaining != null ? Math.min(20, Math.max(1, remaining)) : 20;

  const handleAddBunnies = () => {
    setAddError(null);
    startTransition(async () => {
      const result = await addBunnies(
        breeding.id,
        Math.min(Number(addCount) || 1, maxAdd),
      );
      if (result.success) {
        await fetchRoster();
      } else {
        setAddError(
          result.errorTitle === "litter_full"
            ? t("litterRoster.errorLitterFull")
            : t("litterRoster.errorAdd"),
        );
      }
    });
  };

  const handleDragEnd = (result: DropResult) => {
    if (!result.destination) return;
    const prevRoster = Array.from(roster);
    const newRoster = Array.from(roster);
    const [moved] = newRoster.splice(result.source.index, 1);
    newRoster.splice(result.destination.index, 0, moved);
    setRoster(newRoster);
    startTransition(async () => {
      const res = await reorderRoster(
        breeding.id,
        newRoster.map((b) => b.id),
      );
      if (res.success) {
        if (res.data) {
          setRoster(res.data);
        } else {
          await fetchRoster();
        }
      } else {
        setRoster(prevRoster);
        setReorderError(t("litterRoster.errorReorder"));
      }
    });
  };

  const handleUndoDelete = () => {
    if (!pendingUndo) return;
    const { bunny, index } = pendingUndo;
    setPendingUndo(null);
    startTransition(async () => {
      const fields: {
        label?: string;
        observed_sex?: string;
        observed_color?: string;
        notes?: string;
      } = {};
      if (bunny.label) fields.label = bunny.label;
      if (bunny.observed_sex) fields.observed_sex = bunny.observed_sex;
      if (bunny.observed_color) fields.observed_color = bunny.observed_color;
      if (bunny.notes) fields.notes = bunny.notes;

      const res = await addBunnies(breeding.id, 1, fields);
      const created = res.success ? (res.data?.[0] ?? null) : null;
      if (!created) {
        setAddError(t("litterRoster.errorUndo"));
        return;
      }
      if (bunny.fate !== "undecided") {
        await patchBunny(created.id, { fate: bunny.fate });
      }
      // Put the recreated kit back at its original position
      const fresh = await getLitterRoster(breeding.id);
      if (fresh.success) {
        const ids = fresh.data
          .map((b) => b.id)
          .filter((id) => id !== created.id);
        ids.splice(Math.min(index, ids.length), 0, created.id);
        await reorderRoster(breeding.id, ids);
      }
      await fetchRoster();
    });
  };

  // Inline fate change — optimistic, reuses the PATCH endpoint the edit
  // dialog already calls.
  const handleFateChange = (bunnyId: number, fate: RosterBunny["fate"]) => {
    const prev = roster;
    setRoster((r) => r.map((b) => (b.id === bunnyId ? { ...b, fate } : b)));
    startTransition(async () => {
      const res = await patchBunny(bunnyId, { fate });
      if (!res.success) {
        setRoster(prev);
        setAddError(t("litterRoster.errorFate"));
      }
    });
  };

  // A certificate needs the roster in sync with "alive at 6 weeks": the API
  // refuses while more kits are alive here, and never marks one dead itself.
  // Alive as the API counts it: not Död or Slaktad (registered kits count).
  const alive = roster.filter((b) => b.fate !== "died" && b.fate !== "culled");
  const alive6w = breeding.litter_size6w ?? null;
  const mustMarkDead = alive6w != null ? alive.length - alive6w : 0;
  const choosingDead = mustMarkDead > 0 && markDeadIds != null;
  // Only kits still alive and unregistered can be marked: one whose fate
  // changed while choosing drops out of the choice
  const markable = alive.filter((b) => !b.individual).map((b) => b.id);
  const deadChoice = choosingDead
    ? markable.filter((id) => (markDeadIds ?? []).includes(id))
    : [];

  const handleMarkDead = () => {
    startTransition(async () => {
      for (const id of deadChoice) {
        const res = await patchBunny(id, { fate: "died" });
        if (!res.success) {
          setAddError(t("litterRoster.errorFate"));
          break;
        }
      }
      setMarkDeadIds(null);
      await fetchRoster();
    });
  };

  const activeBunny = roster.find((b) => b.id === promoteBunnyId) ?? null;
  const activeEditBunny = roster.find((b) => b.id === editBunnyId) ?? null;

  return (
    <div className={styles["mb-roster"]} data-testid="litter-roster">
      <div className={styles["mb-roster-head"]}>
        <span className="sb-eyebrow" style={{ letterSpacing: "0.1em" }}>
          {t("litterRoster.title")}
          {roster.length > 0 &&
            ` (${
              litterSize != null
                ? t("litterRoster.countOf", {
                    added: roster.length,
                    born: litterSize,
                  })
                : roster.length
            })`}
        </span>
        {/* 6-week registration gate */}
        {ageInDays != null &&
          (isTooYoung ? (
            <span className="sb-badge sb-badge-lera">
              {t("litterRoster.gateClosed", { days: daysUntilRegister })}
            </span>
          ) : (
            <span className="sb-badge sb-badge-mossa">
              {t("litterRoster.gateOpen")}
            </span>
          ))}
      </div>

      {addError && (
        <Alert
          severity="error"
          sx={{ mb: 1 }}
          onClose={() => setAddError(null)}
        >
          {addError}
        </Alert>
      )}

      {reorderError && (
        <Alert
          severity="error"
          sx={{ mb: 1 }}
          onClose={() => setReorderError(null)}
        >
          {reorderError}
        </Alert>
      )}

      {mustMarkDead > 0 && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {t("litterRoster.syncWarning", {
            alive: alive.length,
            alive6w,
            count: mustMarkDead,
          })}
          <div
            style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}
          >
            {markDeadIds == null ? (
              <button
                type="button"
                className="sb-btn sb-btn-secondary sb-btn-sm"
                disabled={isPending}
                onClick={() =>
                  // Suggest the last undecided kits; only the breeder knows which died
                  setMarkDeadIds(
                    roster
                      .filter((b) => b.fate === "undecided" && !b.individual)
                      .slice(-mustMarkDead)
                      .map((b) => b.id),
                  )
                }
              >
                {t("litterRoster.markDeadChoose")}
              </button>
            ) : (
              <>
                <span className="sb-meta" style={{ flexBasis: "100%" }}>
                  {t("litterRoster.markDeadHint")}
                </span>
                <button
                  type="button"
                  className="sb-btn sb-btn-sm"
                  disabled={isPending || deadChoice.length === 0}
                  onClick={handleMarkDead}
                >
                  {t("litterRoster.markDeadConfirm", {
                    count: deadChoice.length,
                  })}
                </button>
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                  disabled={isPending}
                  onClick={() => setMarkDeadIds(null)}
                >
                  {t("litterRoster.markDeadCancel")}
                </button>
              </>
            )}
          </div>
        </Alert>
      )}

      {isLoading && (
        <Box
          sx={{
            display: "flex",
            justifyContent: "center",
            py: 1,
          }}
        >
          <CircularProgress size={20} />
        </Box>
      )}

      {fetchError && !isLoading && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {t("litterRoster.errorFetch")}
        </Alert>
      )}

      {!isLoading && !fetchError && roster.length === 0 && (
        <p className="sb-meta" style={{ margin: "4px 0 10px" }}>
          {t("litterRoster.emptyState")}
        </p>
      )}

      {roster.length > 0 && (
        <DragDropContext onDragEnd={handleDragEnd}>
          <Droppable droppableId={`litter-roster-${breeding.id}`}>
            {(droppableProvided) => (
              <div
                ref={droppableProvided.innerRef}
                {...droppableProvided.droppableProps}
                className={styles["mb-kit-list"]}
              >
                {roster.map((bunny, index) => {
                  const isLinked = bunny.individual != null;
                  const atCap = bunny.provisional_number === null && !isLinked;
                  // Disabled until 6 weeks, without a reserved
                  // number, or when the kit is marked Slaktad/Död.
                  const registerDisabled =
                    isTooYoung ||
                    atCap ||
                    bunny.fate === "culled" ||
                    bunny.fate === "died";

                  return (
                    <Draggable
                      key={bunny.id}
                      draggableId={String(bunny.id)}
                      index={index}
                    >
                      {(draggableProvided) => (
                        <div
                          ref={draggableProvided.innerRef}
                          {...draggableProvided.draggableProps}
                          className={styles["mb-kit-row"]}
                          data-testid="kit-row"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {/* Drag handle */}
                          <span
                            {...draggableProvided.dragHandleProps}
                            className={styles["mb-kit-drag"]}
                            title={t("litterRoster.dragTooltip")}
                          >
                            ⋮⋮
                          </span>

                          {/* Position in the litter — the kit's identity
                              until it gets a real number */}
                          <span className={styles["mb-kit-pos"]}>
                            {index + 1}
                          </span>

                          <div className={styles["mb-kit-id"]}>
                            {/* Real number (registered) or suggested number */}
                            {isLinked ? (
                              <span
                                className={`sb-meta ${styles["mb-kit-number"]} ${styles["is-registered"]}`}
                              >
                                ✓ {bunny.individual?.number as string}
                              </span>
                            ) : bunny.provisional_number ? (
                              <Tooltip
                                title={t("litterRoster.provisionalTooltip")}
                                arrow
                              >
                                <span
                                  className={`sb-meta ${styles["mb-kit-number"]} ${styles["is-provisional"]}`}
                                >
                                  {bunny.provisional_number}{" "}
                                  <em>{t("litterRoster.suggestionSuffix")}</em>
                                </span>
                              </Tooltip>
                            ) : (
                              <Tooltip
                                title={t("litterRoster.atCapTooltip")}
                                arrow
                              >
                                <span className="sb-badge sb-badge-lera">
                                  {t("litterRoster.atCap")}
                                </span>
                              </Tooltip>
                            )}

                            {/* Name/marking from the edit dialog */}
                            {bunny.label && (
                              <span className={styles["mb-kit-label"]}>
                                {bunny.label}
                              </span>
                            )}

                            {/* Observed sex + colour + notes */}
                            {bunny.observed_sex && (
                              <MbSex sex={bunny.observed_sex} />
                            )}
                            {bunny.observed_color && (
                              <span className="sb-meta">
                                {bunny.observed_color}
                              </span>
                            )}
                            {bunny.notes && (
                              <span className="sb-meta">{bunny.notes}</span>
                            )}
                          </div>

                          <div className={styles["mb-kit-actions"]}>
                            {/* Choosing kits to mark Död (roster sync) */}
                            {choosingDead && markable.includes(bunny.id) && (
                              <input
                                type="checkbox"
                                checked={deadChoice.includes(bunny.id)}
                                aria-label={t("litterRoster.markDeadCheckbox", {
                                  position: index + 1,
                                })}
                                onChange={(e) =>
                                  setMarkDeadIds((ids) =>
                                    e.target.checked
                                      ? [...(ids ?? []), bunny.id]
                                      : (ids ?? []).filter(
                                          (id) => id !== bunny.id,
                                        ),
                                  )
                                }
                                style={{
                                  width: 22,
                                  height: 22,
                                  accentColor: "var(--sb-lera)",
                                }}
                              />
                            )}
                            {/* Inline fate — same PATCH endpoint as the edit
                                dialog, locked once the kit is registered */}
                            <select
                              className={styles["mb-fate-select"]}
                              value={bunny.fate}
                              aria-label={t("litterRoster.fateLabel")}
                              disabled={isLinked || isPending}
                              onChange={(e) =>
                                handleFateChange(
                                  bunny.id,
                                  e.target.value as RosterBunny["fate"],
                                )
                              }
                            >
                              {FATE_OPTIONS.map((f) => (
                                <option key={f} value={f}>
                                  {t(`bunny.fate.${f}`)}
                                </option>
                              ))}
                            </select>

                            {!isLinked && (
                              <Tooltip
                                title={t("litterRoster.editTooltip")}
                                arrow
                              >
                                <IconButton
                                  size="small"
                                  aria-label={t("litterRoster.editTooltip")}
                                  onClick={() => setEditBunnyId(bunny.id)}
                                >
                                  <EditIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}

                            {isLinked ? (
                              <span className="sb-badge sb-badge-skog">
                                {t("bunny.fate.registered")}
                              </span>
                            ) : (
                              <Tooltip
                                title={
                                  isTooYoung
                                    ? t("litterRoster.registerDisabledAge", {
                                        days: daysUntilRegister,
                                      })
                                    : atCap
                                      ? t("litterRoster.registerDisabledCap")
                                      : bunny.fate === "culled" ||
                                          bunny.fate === "died"
                                        ? t("litterRoster.registerDisabledFate")
                                        : t("litterRoster.registerTooltip")
                                }
                                arrow
                              >
                                <span>
                                  <button
                                    type="button"
                                    className="sb-btn sb-btn-sm"
                                    disabled={registerDisabled}
                                    onClick={() => setPromoteBunnyId(bunny.id)}
                                  >
                                    {t("litterRoster.registerButton")}
                                  </button>
                                </span>
                              </Tooltip>
                            )}
                          </div>
                        </div>
                      )}
                    </Draggable>
                  );
                })}
                {droppableProvided.placeholder}
              </div>
            )}
          </Droppable>
        </DragDropContext>
      )}

      {/* Bulk-add control — hidden when the roster already matches "born" */}
      {remaining === 0 ? (
        <p className="sb-meta" style={{ marginTop: 8 }}>
          {t("litterRoster.allAdded", { count: litterSize ?? 0 })}
        </p>
      ) : (
        <div
          className={styles["mb-roster-add"]}
          onClick={(e) => e.stopPropagation()}
        >
          <input
            className="sb-input"
            type="number"
            min={1}
            max={maxAdd}
            value={addCount === "" ? "" : Math.min(addCount, maxAdd)}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === "") {
                setAddCount(""); // allow clearing so the user can retype
                return;
              }
              const parsed = parseInt(raw, 10);
              if (Number.isNaN(parsed)) return;
              setAddCount(Math.min(maxAdd, Math.max(1, parsed)));
            }}
            onBlur={() => {
              if (addCount === "") setAddCount(1);
            }}
            style={{ width: 72, minHeight: 36, padding: "6px 10px" }}
            aria-label={t("litterRoster.addCount")}
          />
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            disabled={isPending}
            onClick={handleAddBunnies}
          >
            {isPending
              ? t("litterRoster.adding")
              : `+ ${t("litterRoster.add")}`}
          </button>
          {litterSize != null && remaining != null && (
            <span className="sb-meta">
              {t("litterRoster.remaining", {
                count: remaining,
                born: litterSize,
              })}
            </span>
          )}
        </div>
      )}

      {/* Promote dialog */}
      {activeBunny && (
        <BunnyPromoteDialog
          open
          bunny={activeBunny}
          breeding={breeding}
          herdId={herdId}
          onClose={() => setPromoteBunnyId(null)}
          onPromoted={() => {
            setPromoteBunnyId(null);
            fetchRoster();
          }}
        />
      )}

      {/* Edit dialog */}
      {activeEditBunny && (
        <BunnyEditDialog
          open
          bunny={activeEditBunny}
          onClose={() => {
            setEditBunnyId(null);
            // A manager may have reverted changes from the history section
            fetchRoster();
          }}
          onSaved={() => {
            setEditBunnyId(null);
            fetchRoster();
          }}
          onDeleted={(deleted) => {
            const index = roster.findIndex((r) => r.id === deleted.id);
            setEditBunnyId(null);
            setPendingUndo({
              bunny: deleted,
              index: index === -1 ? roster.length : index,
            });
            fetchRoster();
          }}
        />
      )}

      {/* Undo-delete toast */}
      <Snackbar
        open={!!pendingUndo}
        autoHideDuration={6000}
        onClose={(_, reason) => {
          if (reason !== "clickaway") setPendingUndo(null);
        }}
        message={t("litterRoster.deletedUndo")}
        action={
          <Button color="secondary" size="small" onClick={handleUndoDelete}>
            {t("litterRoster.undo")}
          </Button>
        }
      />
    </div>
  );
}
