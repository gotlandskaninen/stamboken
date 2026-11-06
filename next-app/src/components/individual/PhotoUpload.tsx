"use client";

import React, { useEffect, useRef, useState, useTransition } from "react";
import {
  Box,
  IconButton,
  LinearProgress,
  Tooltip,
  Typography,
} from "@mui/material";
import { CameraAlt as CameraIcon } from "@mui/icons-material";
import { useTranslation } from "react-i18next";
import { useSnackbar } from "@/components/SnackbarProvider";
import { uploadPhoto } from "@/app/(app)/stamboken/(dashboard)/individ/[number]/photo-upload-action";
import { CropDialog } from "./CropDialog";
import {
  savePendingUpload,
  retryPendingUploads,
  removePendingUpload,
} from "@/utils/uploadRetryQueue";

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];

async function compressImage(
  input: File | Blob,
  maxSizeKB = 500,
): Promise<Blob> {
  const img = await createImageBitmap(input);
  const canvas = document.createElement("canvas");
  let { width, height } = img;

  const maxDim = 1600;
  if (width > maxDim || height > maxDim) {
    const ratio = Math.min(maxDim / width, maxDim / height);
    width = Math.round(width * ratio);
    height = Math.round(height * ratio);
  }

  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(img, 0, 0, width, height);

  let quality = 0.8;
  let blob: Blob | null = await new Promise((r) =>
    canvas.toBlob(r, "image/jpeg", quality),
  );
  while (blob && blob.size > maxSizeKB * 1024 && quality > 0.3) {
    quality -= 0.1;
    blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", quality));
  }
  return blob!;
}

interface PhotoUploadProps {
  individualNumber: string;
}

export function PhotoUpload({ individualNumber }: PhotoUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [cropImageUrl, setCropImageUrl] = useState<string | null>(null);
  const { showSnackbar } = useSnackbar();
  const { t } = useTranslation();

  // Retry pending uploads on mount and when connectivity restores
  useEffect(() => {
    const drainQueue = () => {
      retryPendingUploads(async (number, blob) => {
        const formData = new FormData();
        formData.append("file", blob, `${number}.jpg`);
        const result = await uploadPhoto(number, formData);
        if (!result.success) {
          throw new Error(result.error);
        }
      }).catch(() => {
        // Silently ignore retry failures — items stay in queue
      });
    };

    // Drain on mount (covers app load / page navigation)
    drainQueue();

    window.addEventListener("online", drainQueue);
    return () => window.removeEventListener("online", drainQueue);
  }, []);

  // Revoke object URL on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      if (cropImageUrl) URL.revokeObjectURL(cropImageUrl);
    };
  }, [cropImageUrl]);

  const handleClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Reset input so the same file can be re-selected
    e.target.value = "";

    setError(null);

    // Validate type
    if (!ALLOWED_TYPES.includes(file.type)) {
      setError("Otillåten filtyp — bara JPEG, PNG och WebP");
      return;
    }

    // Validate size
    if (file.size > MAX_FILE_SIZE) {
      setError("Filen är för stor (max 10 MB)");
      return;
    }

    const objectUrl = URL.createObjectURL(file);
    setCropImageUrl(objectUrl);
  };

  const handleCropConfirm = (croppedBlob: Blob) => {
    if (cropImageUrl) URL.revokeObjectURL(cropImageUrl);
    setCropImageUrl(null);

    startTransition(async () => {
      try {
        const compressed = await compressImage(croppedBlob);
        const formData = new FormData();
        formData.append("file", compressed, `${individualNumber}.jpg`);
        const result = await uploadPhoto(individualNumber, formData);

        if (result.success) {
          showSnackbar(t("upload.success"), "success");
          // Clear any queued blob for this individual so an older offline copy
          // can't overwrite this newer photo when the queue drains later.
          await removePendingUpload(individualNumber);
        } else if (result.error === "network_error") {
          try {
            await savePendingUpload(individualNumber, compressed);
            setError(
              "Nätverksfel — fotot sparas och laddas upp automatiskt senare",
            );
          } catch {
            setError("Nätverksfel — kunde inte spara för senare uppladdning");
          }
        } else {
          setError(result.error ?? "Uppladdningen misslyckades");
        }
      } catch {
        setError("Uppladdningen misslyckades");
      }
    });
  };

  const handleCropCancel = () => {
    if (cropImageUrl) URL.revokeObjectURL(cropImageUrl);
    setCropImageUrl(null);
  };

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />

      <Tooltip title={t("upload.label")} arrow>
        <IconButton
          onClick={handleClick}
          disabled={isPending}
          sx={{
            position: "absolute",
            bottom: 8,
            right: 8,
            bgcolor: "rgba(255,255,255,0.85)",
            "&:hover": { bgcolor: "rgba(255,255,255,0.95)" },
            zIndex: 1,
          }}
          aria-label={t("upload.label")}
        >
          <CameraIcon />
        </IconButton>
      </Tooltip>

      {isPending && (
        <LinearProgress
          sx={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            zIndex: 1,
          }}
        />
      )}

      {error && (
        <Typography
          variant="caption"
          color="error"
          sx={{
            position: "absolute",
            bottom: isPending ? 4 : 0,
            left: 0,
            right: 0,
            bgcolor: "rgba(255,255,255,0.9)",
            px: 1,
            py: 0.5,
            zIndex: 1,
          }}
        >
          {error}
        </Typography>
      )}

      <CropDialog
        open={!!cropImageUrl}
        imageUrl={cropImageUrl ?? ""}
        onConfirm={handleCropConfirm}
        onCancel={handleCropCancel}
      />
    </>
  );
}
