"use client";

import React, { createContext, useContext, useState, ReactNode } from "react";
import { Snackbar, Alert, Slide, SlideProps } from "@mui/material";

interface SnackbarState {
  open: boolean;
  message: string;
  severity: "success" | "error" | "info" | "warning";
  duration?: number;
}

interface SnackbarContextType {
  showSnackbar: (
    message: string,
    severity?: "success" | "error" | "info" | "warning",
    duration?: number,
  ) => void;
}

const SnackbarContext = createContext<SnackbarContextType | undefined>(
  undefined,
);

function SlideTransition(props: SlideProps) {
  return <Slide {...props} direction="left" />;
}

export function SnackbarProvider({ children }: { children: ReactNode }) {
  const [snackbar, setSnackbar] = useState<SnackbarState>({
    open: false,
    message: "",
    severity: "success",
    duration: 4000,
  });

  const showSnackbar = (
    message: string,
    severity: "success" | "error" | "info" | "warning" = "success",
    duration: number = 4000,
  ) => {
    setSnackbar({
      open: true,
      message,
      severity,
      duration,
    });
  };

  const handleClose = (
    event?: React.SyntheticEvent | Event,
    reason?: string,
  ) => {
    if (reason === "clickaway") {
      return;
    }
    setSnackbar((prev) => ({ ...prev, open: false }));
  };

  return (
    <SnackbarContext.Provider value={{ showSnackbar }}>
      {children}
      <Snackbar
        anchorOrigin={{
          vertical: "top",
          horizontal: "right",
        }}
        open={snackbar.open}
        autoHideDuration={snackbar.duration}
        onClose={handleClose}
        // Push down below the navbar
        sx={{ mt: 8 }}
        slots={{
          transition: SlideTransition,
        }}
      >
        <Alert
          onClose={handleClose}
          severity={snackbar.severity}
          variant="filled"
          sx={{ minWidth: "200px" }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </SnackbarContext.Provider>
  );
}

export function useSnackbar() {
  const context = useContext(SnackbarContext);
  if (context === undefined) {
    throw new Error("useSnackbar must be used within a SnackbarProvider");
  }
  return context;
}
