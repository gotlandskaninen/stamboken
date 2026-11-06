"use client";

import React from "react";
import { Box, Typography, Link, Tooltip } from "@mui/material";
import { Female as FemaleIcon, Male as MaleIcon } from "@mui/icons-material";
import NextLink from "next/link";
import { useTranslation } from "react-i18next";
import type { PedigreeNode } from "@/redux/api/apiSlice";

interface PedigreeTreeProps {
  tree: PedigreeNode;
  /** Numbers to mark as common ancestors (frame + "gemensam" text, not colour alone). */
  highlight?: ReadonlySet<string>;
  /**
   * "grid" (default): generations as columns, needs ~400 px.
   * "stacked": generations as indented groups, fits a 375 px screen without
   * horizontal scroll.
   */
  layout?: "grid" | "stacked";
}

function AncestorNode({
  node,
  highlight,
}: {
  node: PedigreeNode | null;
  highlight?: ReadonlySet<string>;
}) {
  const { t } = useTranslation();

  if (node?.unregistered) {
    return (
      <Box
        sx={{
          p: 1,
          border: 1,
          borderStyle: "dashed",
          borderColor: "divider",
          borderRadius: 1,
          minWidth: 120,
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          Ej registrerad
        </Typography>
      </Box>
    );
  }

  if (!node || !node.number) {
    return (
      <Box
        sx={{
          p: 1,
          border: 1,
          borderColor: "divider",
          borderRadius: 1,
          bgcolor: "action.hover",
          minWidth: 120,
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Typography
          variant="caption"
          sx={{
            color: "text.disabled",
          }}
        >
          {t("pedigree.unknown")}
        </Typography>
      </Box>
    );
  }

  const isCommon = !!highlight?.has(node.number);
  const isFemale = node.sex === "female";
  const sexIcon = isFemale ? (
    <FemaleIcon sx={{ fontSize: 14 }} color="secondary" />
  ) : (
    <MaleIcon sx={{ fontSize: 14 }} color="primary" />
  );

  return (
    <Tooltip title={node.name || node.number} arrow>
      <Box
        component={NextLink}
        href={`/stamboken/individ/${encodeURIComponent(node.number)}`}
        sx={{
          p: 1,
          border: isCommon ? 2 : 1,
          borderColor: isCommon
            ? "warning.dark"
            : isFemale
              ? "secondary.light"
              : "primary.light",
          borderRadius: 1,
          textDecoration: "none",
          color: "inherit",
          minWidth: 120,
          // Touch target (ADR-0010): stacked nodes would otherwise be ~33 px.
          minHeight: 44,
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          "&:hover": {
            bgcolor: "action.hover",
            borderColor: isFemale ? "secondary.main" : "primary.main",
          },
        }}
      >
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.5,
          }}
        >
          {sexIcon}
          <Typography
            variant="caption"
            noWrap
            sx={{
              fontWeight: "medium",
            }}
          >
            {node.number}
          </Typography>
        </Box>
        {node.name && (
          <Typography
            variant="caption"
            noWrap
            sx={{
              color: "text.secondary",
            }}
          >
            {node.name}
          </Typography>
        )}
        {isCommon && (
          <Typography
            variant="caption"
            data-testid="pedigree-common-ancestor"
            sx={{ color: "warning.dark", fontWeight: "bold" }}
          >
            gemensam
          </Typography>
        )}
      </Box>
    </Tooltip>
  );
}

const STACKED_MAX_DEPTH = 3;

function StackedBranch({
  node,
  role,
  depth,
  highlight,
}: {
  node: PedigreeNode | null;
  role: "Mor" | "Far";
  depth: number;
  highlight?: ReadonlySet<string>;
}) {
  // Only a known (or stated, unregistered) animal has parents worth listing.
  const hasParents = !!node && (!!node.number || !!node.unregistered);
  return (
    <Box component="li" sx={{ minWidth: 0 }}>
      <Box sx={{ display: "flex", alignItems: "stretch", gap: 1, mb: 0.5 }}>
        <Typography
          variant="caption"
          sx={{ color: "text.secondary", width: 28, flexShrink: 0, pt: 1 }}
        >
          {role}
        </Typography>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <AncestorNode highlight={highlight} node={node} />
        </Box>
      </Box>
      {hasParents && depth < STACKED_MAX_DEPTH && (
        <StackedList node={node} depth={depth + 1} highlight={highlight} />
      )}
    </Box>
  );
}

function StackedList({
  node,
  depth,
  highlight,
}: {
  node: PedigreeNode | null;
  depth: number;
  highlight?: ReadonlySet<string>;
}) {
  return (
    <Box
      component="ul"
      // list-style: none drops the list semantics in Safari/VoiceOver unless explicit.
      role="list"
      sx={{
        listStyle: "none",
        m: 0,
        mb: 0.5,
        p: 0,
        pl: 2,
        ml: 1,
        borderLeft: 1,
        borderColor: "divider",
      }}
    >
      <StackedBranch
        node={node?.mother ?? null}
        role="Mor"
        depth={depth}
        highlight={highlight}
      />
      <StackedBranch
        node={node?.father ?? null}
        role="Far"
        depth={depth}
        highlight={highlight}
      />
    </Box>
  );
}

/**
 * Renders a 3-generation pedigree tree using CSS grid.
 *
 * Layout: subject (left) → parents → grandparents → great-grandparents (right)
 * Grid has 8 rows (for 8 great-grandparents) and 4 columns.
 */
export function PedigreeTree({
  tree,
  highlight,
  layout = "grid",
}: PedigreeTreeProps) {
  const { t } = useTranslation();

  if (layout === "stacked") {
    return (
      <Box data-testid="pedigree-tree" data-layout="stacked">
        <Typography variant="caption" sx={{ color: "text.disabled" }}>
          Avkomma
        </Typography>
        <StackedList node={tree} depth={1} highlight={highlight} />
      </Box>
    );
  }

  // Flatten the tree into the 4 column levels:
  // Col 0: subject (1 node, spans 8 rows)
  // Col 1: parents (2 nodes, each spans 4 rows)
  // Col 2: grandparents (4 nodes, each spans 2 rows)
  // Col 3: great-grandparents (8 nodes, each spans 1 row)

  const mother = tree.mother;
  const father = tree.father;

  const mm = mother?.mother ?? null; // maternal grandmother
  const mf = mother?.father ?? null; // maternal grandfather
  const fm = father?.mother ?? null; // paternal grandmother
  const ff = father?.father ?? null; // paternal grandfather

  // Great-grandparents (row order: mmm, mmf, mfm, mff, fmm, fmf, ffm, fff)
  const mmm = mm?.mother;
  const mmf = mm?.father;
  const mfm = mf?.mother;
  const mff = mf?.father;
  const fmm = fm?.mother;
  const fmf = fm?.father;
  const ffm = ff?.mother;
  const fff = ff?.father;

  return (
    <Box
      sx={{
        overflowX: "auto",
        WebkitOverflowScrolling: "touch",
        touchAction: "pan-x pan-y pinch-zoom",
        pb: 1,
      }}
    >
      <Box
        data-testid="pedigree-tree"
        sx={{
          display: "grid",
          gridTemplateColumns:
            "minmax(120px, 1fr) minmax(120px, 1fr) minmax(120px, 1fr)",
          gridTemplateRows: "repeat(8, minmax(42px, auto))",
          gap: 0.5,
          minWidth: 400,
          alignItems: "stretch",
        }}
      >
        {/* Column 1: Parents — each spans 4 rows */}
        <Box sx={{ gridColumn: 1, gridRow: "1 / 5" }}>
          <AncestorNode highlight={highlight} node={mother} />
        </Box>
        <Box sx={{ gridColumn: 1, gridRow: "5 / 9" }}>
          <AncestorNode highlight={highlight} node={father} />
        </Box>

        {/* Column 2: Grandparents — each spans 2 rows */}
        <Box sx={{ gridColumn: 2, gridRow: "1 / 3" }}>
          <AncestorNode highlight={highlight} node={mm} />
        </Box>
        <Box sx={{ gridColumn: 2, gridRow: "3 / 5" }}>
          <AncestorNode highlight={highlight} node={mf} />
        </Box>
        <Box sx={{ gridColumn: 2, gridRow: "5 / 7" }}>
          <AncestorNode highlight={highlight} node={fm} />
        </Box>
        <Box sx={{ gridColumn: 2, gridRow: "7 / 9" }}>
          <AncestorNode highlight={highlight} node={ff} />
        </Box>

        {/* Column 3: Great-grandparents — 1 row each */}
        <Box sx={{ gridColumn: 3, gridRow: 1 }}>
          <AncestorNode highlight={highlight} node={mmm ?? null} />
        </Box>
        <Box sx={{ gridColumn: 3, gridRow: 2 }}>
          <AncestorNode highlight={highlight} node={mmf ?? null} />
        </Box>
        <Box sx={{ gridColumn: 3, gridRow: 3 }}>
          <AncestorNode highlight={highlight} node={mfm ?? null} />
        </Box>
        <Box sx={{ gridColumn: 3, gridRow: 4 }}>
          <AncestorNode highlight={highlight} node={mff ?? null} />
        </Box>
        <Box sx={{ gridColumn: 3, gridRow: 5 }}>
          <AncestorNode highlight={highlight} node={fmm ?? null} />
        </Box>
        <Box sx={{ gridColumn: 3, gridRow: 6 }}>
          <AncestorNode highlight={highlight} node={fmf ?? null} />
        </Box>
        <Box sx={{ gridColumn: 3, gridRow: 7 }}>
          <AncestorNode highlight={highlight} node={ffm ?? null} />
        </Box>
        <Box sx={{ gridColumn: 3, gridRow: 8 }}>
          <AncestorNode highlight={highlight} node={fff ?? null} />
        </Box>
      </Box>

      {/* Generation labels */}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns:
            "minmax(120px, 1fr) minmax(120px, 1fr) minmax(120px, 1fr)",
          gap: 0.5,
          minWidth: 400,
          mt: 0.5,
        }}
      >
        {[
          t("pedigree.parents"),
          t("pedigree.grandparents"),
          t("pedigree.greatGrandparents"),
        ].map((label) => (
          <Typography
            key={label}
            variant="caption"
            sx={{
              color: "text.disabled",
              textAlign: "center",
            }}
          >
            {label}
          </Typography>
        ))}
      </Box>
    </Box>
  );
}
