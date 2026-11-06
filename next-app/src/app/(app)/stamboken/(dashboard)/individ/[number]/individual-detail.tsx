"use client";

import React, { useEffect, useTransition } from "react";
import { useSearchParams } from "next/navigation";
import {
  Grid,
  Typography,
  Divider,
  Box,
  Button,
  IconButton,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
} from "@mui/material";
import NextLink from "next/link";
import {
  Edit as EditIcon,
  EditOff as EditOffIcon,
  MoreVert as MoreIcon,
  LocalShipping as SellIcon,
  EventNote as ReportIcon,
  HeartBroken as DeathIcon,
  Undo as UndoIcon,
  FavoriteBorder as TestMateIcon,
} from "@mui/icons-material";
import type { Individual, PedigreeNode } from "@/redux/api/apiSlice";
import { useUser } from "@/lib/user-context";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import { Masthead } from "@/components/shell/Masthead";
import { IndividualCard } from "@/components/herd/IndividualCard";
import { PhotoUpload } from "@/components/individual/PhotoUpload";
import { IdentitySection } from "@/components/individual/IdentitySection";
import { PedigreeSection } from "@/components/individual/PedigreeSection";
import { HealthSection } from "@/components/individual/HealthSection";
import { HerdHistorySection } from "@/components/individual/HerdHistorySection";
import { NotesSection } from "@/components/individual/NotesSection";
import { EditSaveBar } from "@/components/individual/EditSaveBar";
import { ReportDeathDialog } from "@/components/individual/ReportDeathDialog";
import { SellRabbitDialog } from "@/components/individual/SellRabbitDialog";
import { isOutsideGenebankHerd } from "@/utils/saleRules";
import {
  saveFormData,
  loadFormData,
  clearFormData,
} from "@/utils/editFormStorage";
import { serializeProvparningParams } from "@/lib/provparning";
import {
  VoidHerdTrackingDialog,
  type VoidMode,
} from "@/components/individual/VoidHerdTrackingDialog";
import {
  HerdTrackingCorrectionDialog,
  type CorrectionPayload,
} from "@/components/individual/HerdTrackingCorrectionDialog";
import {
  latestUndoableSale,
  undoTargetOperationId,
  type HerdTrackingRow,
} from "@/lib/herdTracking";
import {
  updateIndividual,
  getGenebankHerds,
  voidHerdTracking,
  correctHerdTracking,
  undoHerdTrackingOperation,
} from "./actions";
import { useTranslation } from "react-i18next";

export function CardActions({
  canEdit,
  isEditing,
  onToggleEdit,
  isAlive,
  onReportDeath,
  onUndoDeath,
  canSell,
  onSell,
  testMateHref,
  onUndoSale,
}: {
  canEdit: boolean;
  isEditing: boolean;
  onToggleEdit: () => void;
  isAlive: boolean;
  onReportDeath: () => void;
  onUndoDeath: () => void;
  canSell: boolean;
  onSell: () => void;
  testMateHref: string | null;
  onUndoSale: (() => void) | null;
}) {
  const [menuAnchor, setMenuAnchor] = React.useState<null | HTMLElement>(null);
  const { t } = useTranslation();

  // Test mating is read-only: available to every viewer, not just editors.
  const testMateItem = testMateHref ? (
    <MenuItem
      component={NextLink}
      href={testMateHref}
      onClick={() => setMenuAnchor(null)}
    >
      <ListItemIcon>
        <TestMateIcon fontSize="small" />
      </ListItemIcon>
      <ListItemText>{t("individual.edit.testMate")}</ListItemText>
    </MenuItem>
  ) : null;

  // The seller keeps this after the sale even though they can no longer edit (Review Focus 1).
  const undoSaleItem = onUndoSale ? (
    <MenuItem
      onClick={() => {
        setMenuAnchor(null);
        onUndoSale();
      }}
    >
      <ListItemIcon>
        <UndoIcon fontSize="small" />
      </ListItemIcon>
      <ListItemText>{t("individual.history.undoSale")}</ListItemText>
    </MenuItem>
  ) : null;

  if (!canEdit) {
    return (
      <>
        <IconButton
          size="small"
          onClick={(e) => setMenuAnchor(e.currentTarget)}
          aria-label={t("individual.edit.moreActions")}
        >
          <MoreIcon />
        </IconButton>
        <Menu
          anchorEl={menuAnchor}
          open={Boolean(menuAnchor)}
          onClose={() => setMenuAnchor(null)}
        >
          {testMateItem}
          {undoSaleItem}
        </Menu>
      </>
    );
  }

  return (
    <>
      <Button
        variant={isEditing ? "contained" : "outlined"}
        size="small"
        startIcon={isEditing ? <EditOffIcon /> : <EditIcon />}
        onClick={onToggleEdit}
        aria-pressed={isEditing}
      >
        {isEditing
          ? t("individual.edit.exitButton")
          : t("individual.edit.editButton")}
      </Button>
      <IconButton
        size="small"
        onClick={(e) => setMenuAnchor(e.currentTarget)}
        aria-label={t("individual.edit.moreActions")}
      >
        <MoreIcon />
      </IconButton>
      <Menu
        anchorEl={menuAnchor}
        open={Boolean(menuAnchor)}
        onClose={() => setMenuAnchor(null)}
      >
        {!isEditing && (
          <MenuItem
            onClick={() => {
              setMenuAnchor(null);
              onToggleEdit();
            }}
          >
            <ListItemIcon>
              <EditIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t("individual.edit.editButton")}</ListItemText>
          </MenuItem>
        )}
        {testMateItem}
        {undoSaleItem}
        {isAlive ? (
          <MenuItem
            onClick={() => {
              setMenuAnchor(null);
              onReportDeath();
            }}
          >
            <ListItemIcon>
              <DeathIcon fontSize="small" color="error" />
            </ListItemIcon>
            <ListItemText sx={{ color: "error.main" }}>
              {t("individual.death.reportAction")}
            </ListItemText>
          </MenuItem>
        ) : (
          <MenuItem
            onClick={() => {
              setMenuAnchor(null);
              onUndoDeath();
            }}
          >
            <ListItemIcon>
              <UndoIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t("individual.death.undoAction")}</ListItemText>
          </MenuItem>
        )}
        <MenuItem
          disabled={!canSell}
          onClick={() => {
            setMenuAnchor(null);
            onSell();
          }}
        >
          <ListItemIcon>
            <SellIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t("individual.edit.sellIndividual")}</ListItemText>
        </MenuItem>
        <MenuItem disabled>
          <ListItemIcon>
            <ReportIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t("individual.edit.annualReport")}</ListItemText>
          <Typography variant="caption" color="text.disabled" sx={{ ml: 1 }}>
            {t("individual.edit.comingSoon")}
          </Typography>
        </MenuItem>
      </Menu>
    </>
  );
}

import type { AuditLogEntry } from "./audit-types";
import type { HerdTrackingHistory } from "@/lib/herdTracking";
import AuditTimeline from "@/components/audit/AuditTimeline";

interface Props {
  individual: Individual;
  pedigree?: PedigreeNode | null;
  history: HerdTrackingHistory | null;
  auditEntries?: AuditLogEntry[];
  geneticsSlot?: React.ReactNode;
}

export function IndividualDetail({
  individual,
  pedigree,
  history,
  auditEntries = [],
  geneticsSlot,
}: Props) {
  const searchParams = useSearchParams();
  const user = useUser();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();
  const { t } = useTranslation();
  const [isPending, startTransition] = useTransition();
  const undoableSale = latestUndoableSale(history);
  const [justSold, setJustSold] = React.useState(false);
  const [voidTarget, setVoidTarget] = React.useState<{
    row: HerdTrackingRow;
    mode: VoidMode;
  } | null>(null);
  const [voidError, setVoidError] = React.useState<string | null>(null);

  const [correctionOpen, setCorrectionOpen] = React.useState(false);
  const [correctionError, setCorrectionError] = React.useState<string | null>(
    null,
  );
  const [correctionConflict, setCorrectionConflict] = React.useState<
    number[] | undefined
  >(undefined);

  const openVoid = (row: HerdTrackingRow, mode: VoidMode) => {
    setVoidError(null);
    setVoidTarget({ row, mode });
  };

  const handleVoidConfirm = (reason: string, operationId: string) => {
    if (!voidTarget) return;
    const { row, mode } = voidTarget;
    startTransition(async () => {
      const result =
        mode === "undoOperation"
          ? await undoHerdTrackingOperation(
              individual.number || "",
              undoTargetOperationId(row),
              reason,
              operationId,
            )
          : await voidHerdTracking(
              individual.number || "",
              row.id,
              reason,
              operationId,
            );
      if (result.success) {
        setVoidTarget(null);
        setJustSold(false);
        const msg =
          mode === "undoOperation"
            ? "Åtgärden är ångrad."
            : t(
                mode === "undoSale"
                  ? "individual.history.undone"
                  : "individual.history.voided",
              );
        showSnackbar(msg, "success");
        addNotification({ title: msg, message: row.date, type: "success" });
      } else {
        const msg =
          result.error === "unexpected_error"
            ? t("individual.history.voidError")
            : result.error;
        setVoidError(msg); // inline: the snackbar sits behind the modal
        addNotification({
          title: t("individual.history.voidError"),
          message: msg,
          type: "error",
        });
      }
    });
  };

  const handleCorrection = (payload: CorrectionPayload) => {
    setCorrectionError(null); // a repeated error re-scrolls and re-focuses the alert
    startTransition(async () => {
      const result = await correctHerdTracking(
        individual.number || "",
        payload,
      );
      if (result.success) {
        setCorrectionOpen(false);
        setJustSold(false);
        const msg = "Historiken är korrigerad.";
        showSnackbar(msg, "success");
        addNotification({
          title: msg,
          message: individual.number || "",
          type: "success",
        });
      } else {
        const msg =
          result.error === "unexpected_error"
            ? t("individual.history.voidError")
            : result.error;
        setCorrectionError(msg); // inline: the snackbar sits behind the modal
        setCorrectionConflict(result.rows);
        addNotification({
          title: t("individual.history.voidError"),
          message: msg,
          type: "error",
        });
      }
    });
  };

  const herdId =
    typeof individual.herd === "object"
      ? individual.herd.herd
      : (individual.herd as string);

  // "Provpara" prefills the test-mating page with this animal on its side.
  const testMateHref =
    individual.number &&
    (individual.sex === "female" || individual.sex === "male")
      ? `/stamboken/provparning?${serializeProvparningParams({
          genebank: individual.genebank_id,
          hona: individual.sex === "female" ? individual.number : null,
          hane: individual.sex === "male" ? [individual.number] : [],
        })}`
      : null;

  // Permission: current herd owner, genebank manager, or admin
  const canEdit =
    user.is_admin ||
    user.is_manager?.includes(individual.genebank_id) ||
    user.is_owner?.includes(herdId);

  const [isEditing, setIsEditing] = React.useState(
    searchParams.get("edit") === "true",
  );
  const [formData, setFormData] = React.useState<Partial<Individual>>({});
  const [discardDialogOpen, setDiscardDialogOpen] = React.useState(false);
  const [deathDialogOpen, setDeathDialogOpen] = React.useState(false);
  const [sellDialogOpen, setSellDialogOpen] = React.useState(false);
  const [sellError, setSellError] = React.useState<string | null>(null);

  const displayName = individual.name || individual.number || "";
  const herdName =
    typeof individual.herd === "object" ? individual.herd.herd_name : null;
  // Sell/move needs the server's transfer permission (not caretakers). Outside the
  // genebank (GX1/MX1) only a genebank manager/admin can move a rabbit back.
  const canSell =
    individual.alive &&
    !!individual.can_transfer &&
    (!isOutsideGenebankHerd(herdId) ||
      !!user.is_admin ||
      !!user.is_manager?.includes(individual.genebank_id));

  const loadHerds = React.useCallback(
    () => getGenebankHerds(individual.genebank_id),
    [individual.genebank_id],
  );

  // Restore form state from localStorage on mount
  useEffect(() => {
    if (isEditing) return;
    const saved = loadFormData(individual.number || "");
    if (saved && Object.keys(saved).length > 0) {
      setFormData(saved);
      setIsEditing(true);
    }
  }, [individual.number, isEditing]);

  const handleFieldChange = (field: string, value: string | null) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  // Dirty = formData has at least one field that differs from the original
  const isDirty = Object.entries(formData).some(
    ([key, val]) =>
      val !== (individual as unknown as Record<string, unknown>)?.[key],
  );

  // Auto-save to localStorage when formData changes
  useEffect(() => {
    if (isDirty) {
      saveFormData(individual.number || "", formData);
    } else if (isEditing) {
      clearFormData(individual.number || "");
    }
  }, [formData, isDirty, isEditing, individual.number]);

  const handleSave = () => {
    startTransition(async () => {
      const payload = {
        ...formData,
        herd: individual.herd,
      };
      const result = await updateIndividual(individual.number || "", payload);
      if (result.success) {
        clearFormData(individual.number || "");
        showSnackbar(
          t("individual.edit.saveSuccess", { number: individual.number }),
          "success",
        );
        setFormData({});
        setIsEditing(false);
      } else {
        const errorMsg =
          result.error === "unexpected_error"
            ? t("individual.edit.unexpectedError")
            : result.error || t("individual.edit.saveError");
        showSnackbar(errorMsg, "error");
      }
    });
  };

  const handleCancel = () => {
    clearFormData(individual.number || "");
    setFormData({});
    setIsEditing(false);
  };

  const handleToggleEdit = () => {
    if (isEditing) {
      if (isDirty) {
        setDiscardDialogOpen(true);
        return;
      }
      handleCancel();
    } else {
      setIsEditing(true);
    }
  };

  const handleConfirmDiscard = () => {
    setDiscardDialogOpen(false);
    handleCancel();
  };

  const handleReportDeath = (
    deathDate: string | null,
    deathNote: string | null,
    butchered: boolean,
  ) => {
    startTransition(async () => {
      const payload = {
        death_date: deathDate,
        death_note: deathNote,
        butchered,
        herd:
          typeof individual.herd === "object"
            ? individual.herd
            : individual.herd,
      };
      const result = await updateIndividual(individual.number || "", payload);
      if (result.success) {
        setDeathDialogOpen(false);
        const msg = t("individual.death.reported", { name: displayName });
        showSnackbar(msg, "success");
        addNotification({
          title: msg,
          message: deathNote || "",
          type: "success",
        });
      } else {
        const msg = result.error || t("individual.death.error");
        showSnackbar(msg, "error");
        addNotification({
          title: t("individual.death.error"),
          message: msg,
          type: "error",
        });
      }
    });
  };

  const handleSell = (herd: string, sellingDate: string) => {
    setSellError(null);
    startTransition(async () => {
      const result = await updateIndividual(individual.number || "", {
        herd,
        selling_date: sellingDate,
      });
      if (result.success) {
        setSellDialogOpen(false);
        setJustSold(true);
        const msg = t("individual.sell.moved", { name: displayName, herd });
        showSnackbar(msg, "success");
        addNotification({ title: msg, message: sellingDate, type: "success" });
      } else {
        const detail =
          result.error === "unexpected_error"
            ? t("individual.edit.unexpectedError")
            : result.error;
        const msg = detail || t("individual.sell.error");
        // Inline in the dialog: the global snackbar sits behind the modal.
        setSellError(msg);
        addNotification({
          title: t("individual.sell.error"),
          message: msg,
          type: "error",
        });
      }
    });
  };

  const handleUndoDeath = () => {
    startTransition(async () => {
      const payload = {
        death_date: null,
        death_note: null,
        butchered: false,
        herd:
          typeof individual.herd === "object"
            ? individual.herd
            : individual.herd,
      };
      const result = await updateIndividual(individual.number || "", payload);
      if (result.success) {
        const msg = t("individual.death.undone");
        showSnackbar(msg, "success");
        addNotification({
          title: msg,
          message: displayName,
          type: "success",
        });
      } else {
        const msg = result.error || t("individual.death.error");
        showSnackbar(msg, "error");
      }
    });
  };

  return (
    <Box sx={{ pb: isEditing ? 10 : 0 }}>
      <Masthead
        eyebrow={individual.number || "Individ"}
        title={displayName}
        meta={
          <>
            <NextLink
              className="sb-link sb-link-tap"
              href={
                herdId
                  ? `/stamboken/min-besattning?herd=${encodeURIComponent(herdId)}`
                  : "/stamboken/min-besattning"
              }
            >
              {t("individual.breadcrumb.myHerd")}
            </NextLink>
            {" · "}
            <NextLink
              className="sb-link sb-link-tap"
              href={
                herdId
                  ? `/stamboken/min-besattning?herd=${encodeURIComponent(herdId)}&tab=individuals`
                  : "/stamboken/min-besattning?tab=individuals"
              }
            >
              {t("individual.breadcrumb.allRabbits")}
            </NextLink>
          </>
        }
      />

      {justSold && undoableSale && (
        <div
          role="status"
          className="sb-card"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            alignItems: "center",
            padding: "var(--sb-s-4)",
            marginBottom: "var(--sb-s-4)",
          }}
        >
          <span>
            {t("individual.sell.moved", {
              name: displayName,
              herd: undoableSale.herd.label,
            })}
          </span>
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            style={{ minHeight: 44 }}
            onClick={() => openVoid(undoableSale, "undoSale")}
          >
            {t("individual.history.undoSale")}
          </button>
        </div>
      )}

      <Grid container spacing={6}>
        {/* Sidebar / Header card */}
        <Grid size={{ xs: 12, lg: 4 }}>
          <IndividualCard
            individual={individual}
            geneticsSlot={geneticsSlot}
            actions={
              canEdit || testMateHref || undoableSale ? (
                <CardActions
                  canEdit={!!canEdit}
                  isEditing={isEditing}
                  onToggleEdit={handleToggleEdit}
                  isAlive={individual.alive}
                  onReportDeath={() => setDeathDialogOpen(true)}
                  onUndoDeath={handleUndoDeath}
                  canSell={canSell}
                  onSell={() => {
                    setSellError(null);
                    setSellDialogOpen(true);
                  }}
                  testMateHref={testMateHref}
                  onUndoSale={
                    undoableSale
                      ? () => openVoid(undoableSale, "undoSale")
                      : null
                  }
                />
              ) : undefined
            }
            onPhotoUpload={
              canEdit ? (
                <PhotoUpload individualNumber={individual.number || ""} />
              ) : undefined
            }
          />
        </Grid>
        {/* Main content */}
        <Grid size={{ xs: 12, lg: 8 }}>
          <Box
            sx={{
              display: "flex",
              flexDirection: "column",
              gap: 3,
            }}
          >
            <IdentitySection
              individual={individual}
              isEditing={isEditing}
              formData={formData}
              onFieldChange={handleFieldChange}
            />
            <PedigreeSection
              individual={individual}
              pedigree={pedigree ?? null}
            />
            <HealthSection individual={individual} />
            <HerdHistorySection
              history={history}
              onVoid={(row) =>
                openVoid(row, row.can_undo_sale ? "undoSale" : "void")
              }
              onUndoOperation={(row) => openVoid(row, "undoOperation")}
              onCorrect={() => {
                setCorrectionError(null);
                setCorrectionConflict(undefined);
                setCorrectionOpen(true);
              }}
            />
            <NotesSection
              individual={individual}
              isEditing={isEditing}
              formData={formData}
              onFieldChange={handleFieldChange}
            />
            {(user?.is_admin ||
              (user?.is_manager && user.is_manager.length > 0)) &&
              auditEntries.length > 0 && (
                <>
                  <Divider sx={{ my: 4 }} />
                  <Typography variant="h6" gutterBottom>
                    Ändringshistorik
                  </Typography>
                  <AuditTimeline
                    tableName="individual"
                    recordId={individual.id!}
                    entries={auditEntries}
                    revalidatePath={`/stamboken/individ/${individual.number}`}
                  />
                </>
              )}
          </Box>
        </Grid>
      </Grid>

      {isEditing && (
        <EditSaveBar
          isDirty={isDirty}
          isSaving={isPending}
          onSave={handleSave}
          onCancel={handleToggleEdit}
        />
      )}

      <Dialog
        open={discardDialogOpen}
        onClose={() => setDiscardDialogOpen(false)}
        aria-labelledby="discard-dialog-title"
        aria-describedby="discard-dialog-description"
      >
        <DialogTitle id="discard-dialog-title">
          {t("individual.edit.discardTitle")}
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="discard-dialog-description">
            {t("individual.edit.discardMessage")}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDiscardDialogOpen(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleConfirmDiscard} color="error" autoFocus>
            {t("individual.edit.discardConfirm")}
          </Button>
        </DialogActions>
      </Dialog>

      <ReportDeathDialog
        open={deathDialogOpen}
        onClose={() => setDeathDialogOpen(false)}
        onConfirm={handleReportDeath}
        individualName={individual.name || ""}
        individualNumber={individual.number || ""}
        isSaving={isPending}
      />

      <VoidHerdTrackingDialog
        open={voidTarget !== null}
        row={voidTarget?.row ?? null}
        mode={voidTarget?.mode ?? "void"}
        busy={isPending}
        error={voidError}
        onClose={() => setVoidTarget(null)}
        onConfirm={handleVoidConfirm}
      />

      {history?.viewer.can_manage && (
        <HerdTrackingCorrectionDialog
          open={correctionOpen}
          history={history}
          loadHerds={loadHerds}
          busy={isPending}
          error={correctionError}
          conflictRowIds={correctionConflict}
          onClose={() => setCorrectionOpen(false)}
          onConfirm={handleCorrection}
        />
      )}

      <SellRabbitDialog
        open={sellDialogOpen}
        onClose={() => setSellDialogOpen(false)}
        onConfirm={handleSell}
        loadHerds={loadHerds}
        individualName={individual.name || ""}
        individualNumber={individual.number || ""}
        currentHerd={{ herd: herdId, herd_name: herdName }}
        birthDate={individual.birth_date}
        herdTracking={individual.herd_tracking}
        isRegistered={individual.is_registered}
        isSaving={isPending}
        error={sellError}
      />
    </Box>
  );
}
