"use client";

import React from "react";
import {
  Card,
  CardContent,
  CardMedia,
  Typography,
  Box,
  Chip,
  Tooltip,
} from "@mui/material";
import {
  Male as MaleIcon,
  Female as FemaleIcon,
  Cake as CakeIcon,
  VerifiedUser as DigitalCertIcon,
  Description as PaperCertIcon,
} from "@mui/icons-material";
import { Individual } from "@/redux/api/apiSlice";

interface IndividualCardProps {
  individual: Individual;
  onClick?: () => void;
  /** Optional actions rendered top-right (edit button, menu, etc.) */
  actions?: React.ReactNode;
  /** Genetics summary (band + F), a Server Component element under Suspense */
  geneticsSlot?: React.ReactNode;
  /** Optional photo upload overlay rendered over CardMedia (owners only) */
  onPhotoUpload?: React.ReactNode;
}

/**
 * Calculate age from birth date to death date (or today if alive)
 * Returns age string and tooltip text
 * Estimation strategy:
 * 1. Use death_date if available (most accurate)
 * 2. Extract year from death_note if present (e.g. "2018 ...")
 * 3. Use last herd_tracking date + 1 year (realistic estimate)
 * 4. Fallback to today (least accurate)
 */
function getAge(
  birthDate: string | null,
  deathDate: string | null,
  deathNote: string | null,
  alive: boolean,
  herdTracking: Array<{ date: string | null; [key: string]: any }> | null,
): { age: string; tooltip: string } {
  if (!birthDate) return { age: "Okänd ålder", tooltip: "" };

  const birth = new Date(birthDate);
  let endDate: Date;
  let useEstimate = false;
  let estimateSource = "";

  // Try to determine end date
  if (deathDate) {
    endDate = new Date(deathDate);
  } else if (deathNote && alive === false) {
    // Try to extract year from death_note
    // Patterns: "YYYY ...", "YYYY, ..." (both space and comma after year)
    const yearMatch = deathNote.match(/^(19\d{2}|20\d{2})[\s,]/);
    if (yearMatch) {
      // Estimate mid-year for approximate age
      endDate = new Date(`${yearMatch[1]}-07-01`);
      useEstimate = true;
      estimateSource = "från anteckning";
    } else {
      // No year in death_note - use last herd_tracking date + 1 year
      if (herdTracking && herdTracking.length > 0) {
        // Find most recent tracking date
        const sortedTracking = [...herdTracking]
          .filter((t) => t.date != null)
          .sort(
            (a, b) => new Date(b.date!).getTime() - new Date(a.date!).getTime(),
          );
        if (sortedTracking.length === 0)
          return { age: "Okänd ålder", tooltip: "Ingen datuminformation" };
        const lastTrackingDate = new Date(sortedTracking[0].date!);

        // Add 1 year to last tracking (likely died sometime after last report)
        endDate = new Date(lastTrackingDate);
        endDate.setFullYear(endDate.getFullYear() + 1);
        useEstimate = true;
        estimateSource = "från senaste rapportering + 1 år";
      } else {
        // Fallback to today if no tracking data
        endDate = new Date();
        useEstimate = true;
        estimateSource = "uppskattning";
      }
    }
  } else {
    endDate = new Date(); // Use today for living rabbits
  }

  const diffTime = Math.abs(endDate.getTime() - birth.getTime());
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

  let age: string;
  if (diffDays < 30) {
    age = `${diffDays} dagar`;
  } else if (diffDays < 365) {
    const months = Math.floor(diffDays / 30);
    age = `${months} mån`;
  } else {
    const years = Math.floor(diffDays / 365);
    const months = Math.floor((diffDays % 365) / 30);
    age = months > 0 ? `${years} år ${months} mån` : `${years} år`;
  }

  // Add circa indicator if estimated from death_note year or tracking
  if (useEstimate) {
    age = `~${age}`;
  }

  // Build tooltip
  let tooltip = `Född: ${birthDate}`;
  if (deathDate) {
    tooltip += `\nDöd: ${deathDate}`;
  } else if (useEstimate) {
    tooltip += `\nDöd cirka: ${endDate.toISOString().split("T")[0]} (${estimateSource})`;
  }

  return { age, tooltip };
}

function getStatusInfo(individual: Individual) {
  const note = individual.death_note?.toLowerCase() || "";

  const isEscaped =
    note.includes("rymt") ||
    note.includes("rymde") ||
    note.includes("försvann") ||
    note.includes("stulen");

  const isSlaughtered =
    individual.butchered || note.includes("slakt") || note.includes("kött");

  const isEuthanized = note.includes("avliv");

  const yearMatch = individual.death_note?.match(/^(19\d{2}|20\d{2})[\s,]/);
  const deathYear = yearMatch ? yearMatch[1] : null;

  if (individual.death_date) {
    let label = "Död";
    let tooltip = `Död ${individual.death_date}`;

    if (isSlaughtered) {
      label = "Slaktad";
      tooltip = `Slaktad ${individual.death_date}`;
    } else if (isEuthanized) {
      label = "Avlivad";
      tooltip = `Avlivad ${individual.death_date}`;
    }

    if (individual.death_note) {
      tooltip += `\nOrsak: ${individual.death_note}`;
    }

    return { label, color: "error" as const, tooltip };
  }

  if (isEscaped && individual.alive === false) {
    const yearInfo = deathYear ? ` ${deathYear}` : "";
    return {
      label: "Försvunnen",
      color: "warning" as const,
      tooltip: `Försvann${yearInfo}\nAnteckning: ${individual.death_note}`,
    };
  }

  if (isSlaughtered && individual.alive === false) {
    const yearInfo = deathYear ? ` cirka ${deathYear}` : "";
    const tooltip = individual.death_note
      ? `Slaktad${yearInfo}\nOrsak: ${individual.death_note}`
      : `Slaktad${yearInfo}`;
    return { label: "Slaktad", color: "error" as const, tooltip };
  }

  if (isEuthanized && individual.alive === false) {
    const yearInfo = deathYear ? ` cirka ${deathYear}` : "";
    const tooltip = individual.death_note
      ? `Avlivad${yearInfo}\nOrsak: ${individual.death_note}`
      : `Avlivad${yearInfo}`;
    return { label: "Avlivad", color: "error" as const, tooltip };
  }

  if (individual.death_note && individual.alive === false) {
    const deathInfo = deathYear
      ? `Död cirka ${deathYear}\nOrsak: ${individual.death_note}`
      : `Död (datum okänt)\nOrsak: ${individual.death_note}`;
    return { label: "Död", color: "error" as const, tooltip: deathInfo };
  }

  if (!individual.is_active) {
    let tooltip = "Inte årsrapporterad inom 13 månader";

    if (
      individual.alive === false &&
      !individual.death_date &&
      !individual.death_note
    ) {
      tooltip += "\nMarkerad som ej levande";
    }

    return { label: "Inaktiv", color: "default" as const, tooltip };
  }

  return { label: "Aktiv", color: "success" as const, tooltip: "" };
}

/**
 * Individual card component — used in both grid lists and as detail page header.
 * Pass `actions` to render edit button / action menu (detail page).
 * Pass `geneticsSlot` to display the genetics summary (detail page).
 */
export function IndividualCard({
  individual,
  onClick,
  actions,
  geneticsSlot,
  onPhotoUpload,
}: IndividualCardProps) {
  const cacheBuster = individual.updated_at
    ? `?v=${new Date(individual.updated_at).getTime()}`
    : "";
  const photoUrl = individual.has_photo
    ? `/uppladdningar/kaniner/${individual.number}.jpg${cacheBuster}`
    : "/static/img/placeholder-rabbit.png";

  const statusInfo = getStatusInfo(individual);
  const ageInfo = getAge(
    individual.birth_date,
    individual.death_date,
    individual.death_note,
    individual.alive,
    individual.herd_tracking,
  );

  return (
    <Card
      sx={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        cursor: onClick ? "pointer" : "default",
        transition: "box-shadow 0.2s, transform 0.2s",
        "&:hover": onClick
          ? {
              boxShadow: 2,
              transform: "translateY(-1px)",
            }
          : {},
      }}
      onClick={onClick}
    >
      <Box sx={{ position: "relative" }}>
        <CardMedia
          component="img"
          height="200"
          image={photoUrl}
          alt={individual.name || individual.number || "Kanin"}
          sx={{
            objectFit: "cover",
            backgroundColor: "grey.200",
          }}
          onError={(e: React.SyntheticEvent<HTMLImageElement>) => {
            // Prevent infinite loop: only set fallback once
            if (!e.currentTarget.dataset.fallback) {
              e.currentTarget.dataset.fallback = "true";
              e.currentTarget.src = "/static/img/placeholder-rabbit.png";
            }
          }}
        />
        {onPhotoUpload}
      </Box>

      <CardContent sx={{ flexGrow: 1, pb: 2 }}>
        {/* Top row: name/number + optional actions */}
        <Box
          sx={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Typography
              component="div"
              className="sb-meta"
              gutterBottom
              noWrap
              sx={{ fontSize: "13px" }}
            >
              {individual.number || "Inget nummer"}
            </Typography>
            <Typography
              component="div"
              className="sb-display"
              noWrap
              sx={{ fontSize: "22px", lineHeight: 1.15, minHeight: "1.2em" }}
            >
              {individual.name || "Namnlös"}
            </Typography>
          </Box>
          {actions && (
            <Box
              onClick={(e) => e.stopPropagation()}
              sx={{
                display: "flex",
                gap: 2,
                flexShrink: 0,
              }}
            >
              {actions}
            </Box>
          )}
        </Box>

        {/* Sex and Age chips */}
        <Box
          sx={{
            display: "flex",
            gap: 1,
            mt: 1,
            mb: 1,
            flexWrap: "wrap",
          }}
        >
          {individual.sex && (
            <Tooltip
              title={
                individual.sex === "female"
                  ? "Honkanin"
                  : individual.sex === "male"
                    ? "Hankanin"
                    : ""
              }
              arrow
            >
              <Chip
                size="small"
                icon={
                  individual.sex === "female" ? (
                    <FemaleIcon />
                  ) : individual.sex === "male" ? (
                    <MaleIcon />
                  ) : undefined
                }
                label={
                  individual.sex === "female"
                    ? "Hona"
                    : individual.sex === "male"
                      ? "Hane"
                      : "Okänt"
                }
                color={individual.sex === "female" ? "secondary" : "info"}
                variant="outlined"
              />
            </Tooltip>
          )}

          {individual.birth_date && (
            <Tooltip title={ageInfo.tooltip} arrow>
              <Chip
                size="small"
                icon={<CakeIcon />}
                label={ageInfo.age}
                variant="outlined"
              />
            </Tooltip>
          )}
        </Box>

        {/* Status and badges */}
        <Box
          sx={{
            display: "flex",
            gap: 1,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          {statusInfo.tooltip ? (
            <Tooltip title={statusInfo.tooltip} arrow>
              <Chip
                size="small"
                label={statusInfo.label}
                color={statusInfo.color}
              />
            </Tooltip>
          ) : (
            <Chip
              size="small"
              label={statusInfo.label}
              color={statusInfo.color}
            />
          )}

          {/* Certificate with icon */}
          {individual.digital_certificate ? (
            <Tooltip
              title={`Digitalt stamtavleintyg nr ${individual.digital_certificate} — utfärdat och verifierbart i systemet`}
              arrow
            >
              <Chip
                size="small"
                icon={<DigitalCertIcon />}
                label={individual.digital_certificate}
                color="info"
                variant="outlined"
              />
            </Tooltip>
          ) : individual.certificate ? (
            <Tooltip
              title={`Pappersintyg nr ${individual.certificate} — fysiskt dokument, ej digitalt utfärdat`}
              arrow
            >
              <Chip
                size="small"
                icon={<PaperCertIcon />}
                label={individual.certificate}
                color="info"
                variant="outlined"
              />
            </Tooltip>
          ) : null}

          {individual.castration_date && (
            <Tooltip title={`Kastrerad: ${individual.castration_date}`} arrow>
              <Chip size="small" label="Kastrerad" variant="outlined" />
            </Tooltip>
          )}

          {/* "Köpt" badge if from another herd */}
          {(() => {
            const originHerdId =
              typeof individual.origin_herd === "object"
                ? individual.origin_herd?.herd
                : individual.origin_herd;
            const currentHerdId =
              typeof individual.herd === "object"
                ? individual.herd?.herd
                : individual.herd;

            if (originHerdId && originHerdId !== currentHerdId) {
              const purchaseDate = individual.herd_tracking?.find(
                (t) => t.kind === "TRANSFER",
              )?.date;
              const originHerdName =
                typeof individual.origin_herd === "object"
                  ? individual.origin_herd?.herd
                  : individual.origin_herd;

              return (
                <Tooltip
                  title={
                    purchaseDate
                      ? `Köpt ${new Date(purchaseDate).toLocaleDateString("sv-SE")} från ${originHerdName}`
                      : `Köpt från ${originHerdName}`
                  }
                  arrow
                >
                  <Chip
                    size="small"
                    label="Köpt"
                    color="info"
                    variant="outlined"
                  />
                </Tooltip>
              );
            }
            return null;
          })()}

          {/* Genetics summary (detail page only). A streamed slot arrives as an
              unresolved lazy node that the static-children key check cannot
              mark validated, so give it an explicit key. */}
          {geneticsSlot != null && (
            <React.Fragment key="genetics">{geneticsSlot}</React.Fragment>
          )}
        </Box>

        {/* Parent info (compact) */}
        {(individual.mother || individual.father) && (
          <Box
            sx={{
              mt: 2,
            }}
          >
            <Typography
              variant="caption"
              sx={{
                color: "text.secondary",
                display: "block",
              }}
            >
              {individual.mother?.number && `M: ${individual.mother.number}`}
              {individual.mother?.number && individual.father?.number && " • "}
              {individual.father?.number && `F: ${individual.father.number}`}
            </Typography>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
