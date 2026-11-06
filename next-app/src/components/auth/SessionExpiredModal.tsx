"use client";

import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Typography,
  Button,
} from "@mui/material";
import { useSelector, useDispatch } from "react-redux";
import { useTranslation } from "react-i18next";
import { RootState, AppDispatch } from "@/redux/store";
import { signOut } from "@/redux/slices/authSlice";

export default function SessionExpiredModal() {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const isSessionExpired = useSelector(
    (state: RootState) => state.auth.isSessionExpired,
  );

  const handleLogin = () => {
    if (typeof window !== "undefined") {
      sessionStorage.setItem(
        "redirectAfterLogin",
        window.location.pathname + window.location.search,
      );
    }
    dispatch(signOut());
    const returnTo = encodeURIComponent(
      window.location.pathname + window.location.search,
    );
    window.location.href = `/api/login/google?return_to=${returnTo}`;
  };

  return (
    <Dialog open={isSessionExpired}>
      <DialogTitle>{t("auth.sessionExpired")}</DialogTitle>
      <DialogContent>
        <Typography>{t("auth.sessionExpiredMessage")}</Typography>
      </DialogContent>
      <DialogActions>
        <Button variant="contained" onClick={handleLogin} autoFocus>
          {t("auth.loginAgain")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
