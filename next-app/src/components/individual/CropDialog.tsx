"use client";

import React, { useCallback, useEffect, useState } from "react";
import Cropper from "react-easy-crop";
import type { Area } from "react-easy-crop";
import {
  AppBar,
  Box,
  Button,
  Dialog,
  IconButton,
  Slider,
  Toolbar,
  Typography,
} from "@mui/material";
import { Close as CloseIcon } from "@mui/icons-material";
import { useTranslation } from "react-i18next";
import { cropImage } from "@/utils/cropImage";

interface CropDialogProps {
  open: boolean;
  imageUrl: string;
  onConfirm: (blob: Blob) => void;
  onCancel: () => void;
}

export function CropDialog({
  open,
  imageUrl,
  onConfirm,
  onCancel,
}: CropDialogProps) {
  const { t } = useTranslation();
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area | null>(null);

  // Reset crop state when a new image is opened
  useEffect(() => {
    if (open) {
      setCrop({ x: 0, y: 0 });
      setZoom(1);
      setCroppedAreaPixels(null);
    }
  }, [open, imageUrl]);

  const onCropComplete = useCallback((_: Area, croppedPixels: Area) => {
    setCroppedAreaPixels(croppedPixels);
  }, []);

  const handleConfirm = async () => {
    if (!croppedAreaPixels) return;
    const blob = await cropImage(imageUrl, croppedAreaPixels);
    onConfirm(blob);
  };

  return (
    <Dialog
      fullScreen
      open={open}
      onClose={onCancel}
      slotProps={{
        paper: { sx: { display: "flex", flexDirection: "column" } },
      }}
    >
      <AppBar sx={{ position: "relative" }} color="default">
        <Toolbar>
          <IconButton
            edge="start"
            onClick={onCancel}
            aria-label={t("upload.cropCancel")}
          >
            <CloseIcon />
          </IconButton>
          <Typography sx={{ flex: 1, ml: 2 }} variant="h6">
            {t("upload.cropTitle")}
          </Typography>
          <Button color="primary" variant="contained" onClick={handleConfirm}>
            {t("upload.cropConfirm")}
          </Button>
        </Toolbar>
      </AppBar>

      <Box
        sx={{
          position: "relative",
          flex: 1,
          bgcolor: "common.black",
        }}
      >
        <Cropper
          image={imageUrl}
          crop={crop}
          zoom={zoom}
          aspect={1}
          onCropChange={setCrop}
          onZoomChange={setZoom}
          onCropComplete={onCropComplete}
        />
      </Box>

      <Box sx={{ px: 3, py: 2, bgcolor: "background.paper" }}>
        <Typography
          variant="caption"
          gutterBottom
          sx={{
            color: "text.secondary",
          }}
        >
          {t("upload.zoom")}
        </Typography>
        <Slider
          value={zoom}
          min={1}
          max={3}
          step={0.1}
          onChange={(_, value) => typeof value === "number" && setZoom(value)}
          aria-label={t("upload.zoom")}
        />
      </Box>
    </Dialog>
  );
}
