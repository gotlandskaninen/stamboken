"use client";

import NextLink from "next/link";
import { useTranslation } from "react-i18next";
import { PictureAsPdfOutlined } from "@mui/icons-material";
import type { Individual } from "@/redux/api/apiSlice";
import { useMode } from "@/lib/mode-context";
import styles from "./DigitalCertificate.module.css";

/**
 * The digital certificate on the rabbit's page. Whether the viewer may open
 * the PDF is the API's `can_view_certificate` (ADR-0016: owner, breeder,
 * genebank manager, admin), the same check GET /api/v2/certificates/<number>
 * makes. Everyone else learns who may, and gets the public verification page;
 * a v1 certificate has none, so for it the note stands alone. The test
 * environment opens no PDF for now.
 */
export function DigitalCertificate({ individual }: { individual: Individual }) {
  const { t } = useTranslation();
  const demo = useMode() === "demo";
  const current = individual.current_certificate;
  // A current PDF can outlive its number (ADR-0019, migrate_37_to_38): still show it.
  if (!individual.number || (!individual.digital_certificate && !current))
    return null;

  const verify = current && (
    <NextLink
      className={`sb-link sb-link-tap ${styles.link}`}
      href={`/stamboken/verifiera/${encodeURIComponent(current.verification_token)}`}
    >
      {t("individual.certificate.verify")}
    </NextLink>
  );

  return (
    <div className={styles.root}>
      {current && (
        <p className={`sb-meta ${styles.meta}`}>
          {/* The server's own date, so no time zone moves it a day. */}
          {t("individual.certificate.issued", {
            date: current.issued_at.slice(0, 10),
          })}
        </p>
      )}
      {individual.can_view_certificate && !demo ? (
        <div className={styles.actions}>
          <a
            className="sb-btn sb-btn-secondary sb-btn-sm"
            href={`/api/v2/certificates/${encodeURIComponent(individual.number)}`}
            target="_blank"
            rel="noopener"
          >
            <PictureAsPdfOutlined fontSize="small" aria-hidden />
            {t("individual.certificate.view")}
            <span className={styles.srOnly}>
              {" "}
              {t("individual.certificate.newTab")}
            </span>
          </a>
          {verify}
        </div>
      ) : (
        <>
          <p className={styles.note}>
            {t(
              demo && individual.can_view_certificate
                ? "individual.certificate.notInDemo"
                : "individual.certificate.onlyFor",
            )}
          </p>
          {verify}
        </>
      )}
    </div>
  );
}
