"use client";

import React from "react";
import { IndividualAutocomplete } from "@/components/herd/IndividualAutocomplete";
import { SbIcon } from "@/components/shell/SbIcon";
import type { AnimalInput } from "@/lib/provparning";
import styles from "./provparning.module.css";

interface AnimalPickerProps {
  /** Which sex this slot holds; the parents of an unregistered animal are the opposite pair. */
  sex: "female" | "male";
  /** "Hona", "Hane", "Hane 2" … */
  title: string;
  genebankId: number;
  ownHerd?: string;
  value: AnimalInput;
  onChange: (patch: Partial<AnimalInput>) => void;
  onRemove?: () => void;
  testId: string;
}

/**
 * One side of the mating: pick a registered animal, or — for an animal that
 * is not in the studbook yet — pick its mother and father instead.
 * Searches the whole genebank including dead animals (`includeHistorical`
 * false: with `herdId` it would otherwise restrict to the herd's own history).
 */
export function AnimalPicker({
  sex,
  title,
  genebankId,
  ownHerd,
  value,
  onChange,
  onRemove,
  testId,
}: AnimalPickerProps) {
  const shared = {
    genebankId,
    herdId: ownHerd,
    includeHistorical: false,
  } as const;
  const the = sex === "female" ? "Honan" : "Hanen";

  return (
    <div className={styles.picker} data-testid={testId}>
      <div className={styles.pickerRow}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {value.unregistered ? (
            <>
              <IndividualAutocomplete
                {...shared}
                label={`${title} – mor`}
                sex="female"
                value={value.mother}
                onChange={(mother) => onChange({ mother })}
              />
              <IndividualAutocomplete
                {...shared}
                label={`${title} – far`}
                sex="male"
                value={value.father}
                onChange={(father) => onChange({ father })}
              />
            </>
          ) : (
            <IndividualAutocomplete
              {...shared}
              label={title}
              sex={sex}
              value={value.picked}
              onChange={(picked) => onChange({ picked })}
            />
          )}
        </div>
        {onRemove && (
          <button
            type="button"
            className={styles.iconBtn}
            onClick={onRemove}
            aria-label={`Ta bort ${title.toLowerCase()}`}
          >
            <SbIcon name="cross" size={18} />
          </button>
        )}
      </div>
      <button
        type="button"
        className={styles.toggleLink}
        onClick={() => onChange({ unregistered: !value.unregistered })}
      >
        {value.unregistered
          ? "Välj ur stamboken i stället"
          : `${the} är inte registrerad än`}
      </button>
    </div>
  );
}
