"use client";

import React from "react";
import {
  Card,
  CardContent,
  Typography,
  Box,
  Button,
  Collapse,
} from "@mui/material";
import { ExpandMore as ExpandMoreIcon } from "@mui/icons-material";
import type { Individual } from "@/redux/api/apiSlice";

interface HealthSectionProps {
  individual: Individual;
}

const bodyfatLabels: Record<string, string> = {
  low: "Låg",
  normal: "Normal",
  high: "Hög",
};

export function HealthSection({ individual }: HealthSectionProps) {
  const [expanded, setExpanded] = React.useState(false);

  const weights = [...(individual.weights || [])].sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
  );

  const bodyfats = [...(individual.bodyfat || [])].sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
  );

  const latestWeight = weights[0];
  const latestBodyfat = bodyfats[0];
  const hasHistory = weights.length > 1 || bodyfats.length > 1;
  const hasAnyData = weights.length > 0 || bodyfats.length > 0;

  if (!hasAnyData) {
    return (
      <Card>
        <CardContent sx={{ "&:last-child": { pb: 2 } }}>
          <Typography variant="h6" gutterBottom>
            Hälsa &amp; Mått
          </Typography>
          <Typography
            variant="body2"
            sx={{
              color: "text.secondary",
            }}
          >
            Inga mätvärden registrerade.
          </Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent sx={{ "&:last-child": { pb: 2 } }}>
        <Typography variant="h6" gutterBottom>
          Hälsa &amp; Mått
        </Typography>

        {/* Latest values — always visible */}
        <Box
          sx={{
            display: "flex",
            gap: 3,
            flexWrap: "wrap",
          }}
        >
          {latestWeight && (
            <Box>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                }}
              >
                Senaste vikt
              </Typography>
              <Typography variant="body2">
                {`${latestWeight.weight} kg`}
                <Typography
                  component="span"
                  variant="caption"
                  sx={{
                    color: "text.secondary",
                    ml: 0.5,
                  }}
                >
                  ({latestWeight.date})
                </Typography>
              </Typography>
            </Box>
          )}
          {latestBodyfat && (
            <Box>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                }}
              >
                Senaste hull
              </Typography>
              <Typography variant="body2">
                {bodyfatLabels[latestBodyfat.bodyfat] || latestBodyfat.bodyfat}
                <Typography
                  component="span"
                  variant="caption"
                  sx={{
                    color: "text.secondary",
                    ml: 0.5,
                  }}
                >
                  ({latestBodyfat.date})
                </Typography>
              </Typography>
            </Box>
          )}
        </Box>

        {/* Expandable full history */}
        {hasHistory && (
          <>
            <Collapse in={expanded}>
              <Box
                sx={{
                  mt: 2,
                }}
              >
                {weights.length > 1 && (
                  <>
                    <Typography variant="subtitle2" gutterBottom>
                      Alla vikter
                    </Typography>
                    <Box
                      component="ul"
                      sx={{ listStyle: "none", p: 0, m: 0, mb: 2 }}
                    >
                      {weights.map((w, i) => (
                        <Box
                          component="li"
                          key={i}
                          sx={{
                            display: "flex",
                            justifyContent: "space-between",
                            py: 0.25,
                          }}
                        >
                          <Typography
                            variant="body2"
                            sx={{
                              color: "text.secondary",
                            }}
                          >
                            {w.date}
                          </Typography>
                          <Typography variant="body2">{`${w.weight} kg`}</Typography>
                        </Box>
                      ))}
                    </Box>
                  </>
                )}
                {bodyfats.length > 1 && (
                  <>
                    <Typography variant="subtitle2" gutterBottom>
                      Alla hullbedömningar
                    </Typography>
                    <Box component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
                      {bodyfats.map((bf, i) => (
                        <Box
                          component="li"
                          key={i}
                          sx={{
                            display: "flex",
                            justifyContent: "space-between",
                            py: 0.25,
                          }}
                        >
                          <Typography
                            variant="body2"
                            sx={{
                              color: "text.secondary",
                            }}
                          >
                            {bf.date}
                          </Typography>
                          <Typography variant="body2">
                            {bodyfatLabels[bf.bodyfat] || bf.bodyfat}
                          </Typography>
                        </Box>
                      ))}
                    </Box>
                  </>
                )}
              </Box>
            </Collapse>
            <Button
              size="small"
              onClick={() => setExpanded(!expanded)}
              endIcon={
                <ExpandMoreIcon
                  sx={{
                    transform: expanded ? "rotate(180deg)" : "none",
                    transition: "transform 0.2s",
                  }}
                />
              }
              sx={{ mt: 1 }}
            >
              {expanded ? "Dölj historik" : "Visa alla mätvärden"}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
