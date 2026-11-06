"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  TextField,
} from "@mui/material";
import { approveApplication, rejectApplication } from "../actions";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useNotifications } from "@/contexts/NotificationContext";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../medlem.module.css";

export function ApplicationDetailClient({
  applicationId,
  status,
}: {
  applicationId: number;
  status: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const { showSnackbar } = useSnackbar();
  const { addNotification } = useNotifications();
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState("");
  // Approval succeeded but the contact email already belongs to an active
  // person — the reviewer stays here and sees the warning instead of being
  // redirected past it.
  const [approvedWithDuplicate, setApprovedWithDuplicate] = useState(false);

  if (approvedWithDuplicate) {
    return (
      <>
        <div className={ds["ad-banner"]} role="status">
          Ansökan godkänd — medlemskap skapat.
        </div>
        <div
          className={`${ds["ad-banner"]} ${ds["ad-banner-warning"]}`}
          role="alert"
        >
          E-postadressen används redan av en annan aktiv person i matrikeln.
          Kontrollera att ansökan inte avser en person som redan är medlem.
        </div>
        <div className={ds["ad-form-actions"]}>
          <button
            type="button"
            className="sb-btn sb-btn-secondary"
            onClick={() => router.push("/medlem/ansokningar")}
          >
            Till ansökningarna
          </button>
        </div>
      </>
    );
  }

  if (status !== "pending") {
    return (
      <div className={ds["ad-banner"]}>
        Ansökan är redan {status === "approved" ? "godkänd" : "avslagen"}.
      </div>
    );
  }

  const notifyError = (message: string, title: string) => {
    showSnackbar(message, "error");
    addNotification({ title, message, type: "error" });
  };

  const handleApprove = () => {
    startTransition(async () => {
      const result = await approveApplication(applicationId);
      if (result.ok) {
        if (result.duplicateContactEmail) {
          setApproveOpen(false);
          setApprovedWithDuplicate(true);
        } else {
          showSnackbar("Ansökan godkänd", "success");
          router.push("/medlem/ansokningar");
        }
      } else {
        notifyError(result.error, "Kunde inte godkänna ansökan");
        setApproveOpen(false);
      }
    });
  };

  const handleReject = () => {
    if (reason.trim().length < 3) {
      showSnackbar("Motivering måste vara minst 3 tecken.", "warning");
      return;
    }
    startTransition(async () => {
      const result = await rejectApplication(applicationId, reason);
      if (result.ok) {
        showSnackbar("Ansökan avslagen", "success");
        router.push("/medlem/ansokningar");
      } else {
        notifyError(result.error, "Kunde inte avslå ansökan");
      }
    });
  };

  return (
    <>
      <div className={ds["ad-form-actions"]}>
        <button
          type="button"
          className="sb-btn"
          onClick={() => setApproveOpen(true)}
          disabled={pending}
        >
          Godkänn
        </button>
        <button
          type="button"
          className={`sb-btn ${ds["ad-btn-danger"]}`}
          onClick={() => setRejectOpen(true)}
          disabled={pending}
        >
          Avslå
        </button>
      </div>

      <Dialog open={approveOpen} onClose={() => setApproveOpen(false)}>
        <DialogTitle>Godkänna ansökan?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Detta skapar medlemskapet med nästa lediga medlemsnummer och kan
            inte ångras.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <button
            type="button"
            className="sb-btn sb-btn-ghost"
            onClick={() => setApproveOpen(false)}
          >
            Avbryt
          </button>
          <button
            type="button"
            className="sb-btn"
            onClick={handleApprove}
            disabled={pending}
          >
            Godkänn
          </button>
        </DialogActions>
      </Dialog>

      <Dialog open={rejectOpen} onClose={() => setRejectOpen(false)}>
        <DialogTitle>Avslå ansökan</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={3}
            label="Motivering för avslag"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={styles.dialogField}
          />
        </DialogContent>
        <DialogActions>
          <button
            type="button"
            className="sb-btn sb-btn-ghost"
            onClick={() => setRejectOpen(false)}
          >
            Avbryt
          </button>
          <button
            type="button"
            className="sb-btn"
            onClick={handleReject}
            disabled={pending || reason.trim().length < 3}
          >
            Avslå
          </button>
        </DialogActions>
      </Dialog>
    </>
  );
}
