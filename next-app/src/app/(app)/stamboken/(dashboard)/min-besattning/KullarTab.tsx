"use client";

import React from "react";
import { Box } from "@mui/material";
import { LitterRegistrationForm } from "@/components/herd/LitterRegistrationForm";
import { MatingRegistrationForm } from "@/components/herd/MatingRegistrationForm";
import { BreedingList } from "@/components/herd/BreedingList";
import styles from "./min-besattning.module.css";

export interface KullarTabProps {
  breedings: any[] | null;
  userHerdId: string;
  genebankId: number | null;
  showLitterForm: boolean;
  showMatingForm: boolean;
  isSubmittingLitter: boolean;
  isSubmittingMating: boolean;
  deletingBreedingId: number | null;
  onShowLitterForm: (v: boolean) => void;
  onShowMatingForm: (v: boolean) => void;
  onLitterSubmit: (data: {
    mother: string;
    father: string;
    birthDate: string;
    breedingDate: string;
    totalBorn: number;
    aliveAt6w: number | null;
    birthNotes: string;
    breedingHerd: string;
  }) => Promise<boolean>;
  onMatingSubmit: (data: {
    mother: string;
    father: string;
    matingDate: string;
    breedNotes: string;
    breedingHerd: string;
  }) => Promise<boolean>;
  onDeleteBreeding: (id: number) => void;
  onRegisterBirth: (data: {
    breedingId: number;
    date: string;
    litter_size: number;
    litter_size6w?: number | null;
    notes?: string;
  }) => Promise<boolean>;
  onUpdateBreeding: (data: {
    id: number;
    [key: string]: unknown;
  }) => Promise<boolean>;
}

export default function KullarTab({
  breedings,
  userHerdId,
  genebankId,
  showLitterForm,
  showMatingForm,
  isSubmittingLitter,
  isSubmittingMating,
  deletingBreedingId,
  onShowLitterForm,
  onShowMatingForm,
  onLitterSubmit,
  onMatingSubmit,
  onDeleteBreeding,
  onRegisterBirth,
  onUpdateBreeding,
}: KullarTabProps) {
  const breedingList = breedings;

  return (
    <div>
      <div
        className={styles["mb-toolbar"]}
        style={{ justifyContent: "space-between" }}
      >
        <h2 className="sb-h5" style={{ margin: 0 }}>
          Kullar &amp; parningar
        </h2>
        {!showLitterForm && !showMatingForm && (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="sb-btn sb-btn-secondary sb-btn-sm"
              onClick={() => onShowMatingForm(true)}
            >
              Ny parning
            </button>
            <button
              type="button"
              className="sb-btn sb-btn-sm"
              onClick={() => onShowLitterForm(true)}
            >
              + Ny kull
            </button>
          </div>
        )}
      </div>

      {showLitterForm && (
        <Box sx={{ mb: 3 }}>
          <LitterRegistrationForm
            herdId={userHerdId || ""}
            genebankId={genebankId}
            onSubmit={onLitterSubmit}
            onCancel={() => onShowLitterForm(false)}
            isSubmitting={isSubmittingLitter}
          />
        </Box>
      )}

      {showMatingForm && (
        <Box sx={{ mb: 3 }}>
          <MatingRegistrationForm
            herdId={userHerdId || ""}
            genebankId={genebankId}
            onSubmit={onMatingSubmit}
            onCancel={() => onShowMatingForm(false)}
            isSubmitting={isSubmittingMating}
          />
        </Box>
      )}

      <BreedingList
        breedings={breedingList || []}
        isLoading={false}
        canEdit={!!userHerdId}
        herdId={userHerdId || undefined}
        onDelete={onDeleteBreeding}
        isDeletingId={deletingBreedingId}
        onRegisterFirst={() => onShowMatingForm(true)}
        onRegisterBirth={onRegisterBirth}
        onUpdate={onUpdateBreeding}
      />
    </div>
  );
}
