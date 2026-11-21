"use client";

import React, { useId } from "react";
import {
  FormControl,
  FormControlLabel,
  FormLabel,
  Radio,
  RadioGroup,
} from "@mui/material";
import { useTranslation } from "react-i18next";

interface CoatChoiceProps {
  rex: boolean;
  onChange: (rex: boolean) => void;
}

/** Päls: two options, Normal (false) or Rex (true). */
export function CoatChoice({ rex, onChange }: CoatChoiceProps) {
  const { t } = useTranslation();
  const labelId = useId();
  return (
    <FormControl>
      <FormLabel id={labelId}>{t("coat.label")}</FormLabel>
      <RadioGroup
        row
        aria-labelledby={labelId}
        value={rex ? "rex" : "normal"}
        onChange={(e) => onChange(e.target.value === "rex")}
      >
        <FormControlLabel
          value="normal"
          control={<Radio size="small" />}
          label={t("coat.normal")}
        />
        <FormControlLabel
          value="rex"
          control={<Radio size="small" />}
          label={t("coat.rex")}
        />
      </RadioGroup>
    </FormControl>
  );
}
