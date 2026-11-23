"use client";

import Link from "next/link";
import { Typography } from "@mui/material";
import { useTranslation } from "react-i18next";
import { useOptionalUser } from "@/lib/user-context";

/* Shown where a digital certificate is issued while the person has not chosen
   whether the check page names her (stamboken #6). */
export function CheckPageNameHint() {
  const { t } = useTranslation();
  const user = useOptionalUser();
  if (user?.name_on_check_page !== null) return null;
  return (
    <Typography
      variant="caption"
      sx={{ color: "text.secondary", display: "block", mt: 0.5, ml: 1.5 }}
    >
      {t("addRabbit.checkPageNameHint")}{" "}
      <Link className="sb-link" href="/stamboken/profil">
        {t("addRabbit.checkPageNameHintLink")}
      </Link>
    </Typography>
  );
}
