"use client";

import React from "react";
import {
  Alert,
  Card,
  CardContent,
  CardActionArea,
  Typography,
  Box,
  Tooltip,
  Collapse,
} from "@mui/material";
import {
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
} from "@mui/icons-material";
import { useTranslation } from "react-i18next";
import type { Individual, PedigreeNode } from "@/redux/api/apiSlice";
import { PedigreeTree } from "@/components/individual/PedigreeTree";

interface PedigreeSectionProps {
  individual: Individual;
  pedigree: PedigreeNode | null;
}

export function PedigreeSection({
  individual,
  pedigree,
}: PedigreeSectionProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(true);

  return (
    <Card>
      <CardActionArea
        onClick={() => setExpanded((prev) => !prev)}
        sx={{ minHeight: 44 }}
      >
        <CardContent
          sx={{
            pb: expanded ? 0 : undefined,
            "&:last-child": expanded ? { pb: 0 } : undefined,
          }}
        >
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Typography variant="h6">{t("pedigree.title")}</Typography>
            {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </Box>
        </CardContent>
      </CardActionArea>

      <Collapse in={expanded}>
        <CardContent sx={{ pt: 1 }}>
          {pedigree ? (
            <PedigreeTree tree={pedigree} />
          ) : (
            <Alert severity="warning" sx={{ mb: 1 }}>
              {t("pedigree.loadError")}
            </Alert>
          )}

          {(individual.litter_size != null ||
            individual.litter_size6w != null) && (
            <Tooltip
              title="Antal födda i kullen och antal levande efter 6 veckor"
              arrow
            >
              <Typography
                variant="body2"
                sx={{
                  color: "text.secondary",
                  mt: 2,
                }}
              >
                {`Kullstorlek: ${individual.litter_size ?? "–"}`}
                {individual.litter_size6w != null &&
                  ` (vid 6v: ${individual.litter_size6w})`}
              </Typography>
            </Tooltip>
          )}
        </CardContent>
      </Collapse>
    </Card>
  );
}
