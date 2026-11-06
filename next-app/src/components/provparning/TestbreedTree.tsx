"use client";

import React, { useMemo } from "react";
import { useMediaQuery } from "@mui/material";
import { PedigreeTree } from "@/components/individual/PedigreeTree";
import type { PedigreeNode } from "@/redux/api/apiSlice";
import styles from "./provparning.module.css";

/**
 * Pedigree of the planned offspring: female on top, male below. Both partner
 * trees come from the `POST /api/v2/testbreed` response, which has already
 * removed voided and other-genebank ancestors (shown as "okänd") — nothing is
 * fetched here, so nothing the calculation hid can leak into the tree.
 */
export function TestbreedTree({
  female,
  male,
  highlight,
}: {
  female: PedigreeNode;
  male: PedigreeNode;
  highlight: ReadonlySet<string>;
}) {
  // Grid needs ~400 px; below 640 px generations stack as indented groups.
  const wide = useMediaQuery("(min-width:640px)", { noSsr: true });

  const tree = useMemo<PedigreeNode>(
    () => ({
      id: null,
      name: null,
      number: null,
      sex: null,
      mother: female,
      father: male,
    }),
    [female, male],
  );

  return (
    <>
      <PedigreeTree
        tree={tree}
        highlight={highlight}
        layout={wide ? "grid" : "stacked"}
      />
      <p className={styles.treeNote}>
        Tänkt avkomma – honan överst, hanen underst. Ram och texten ”gemensam”
        markerar förfäder som finns på båda sidor.
      </p>
    </>
  );
}
