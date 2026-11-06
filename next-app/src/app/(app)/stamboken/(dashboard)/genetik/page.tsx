"use client";

import React, { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Tabs,
  Tab,
  Box,
  Alert,
} from "@mui/material";

import useAuth from "@/hooks/useAuth";
import { Masthead } from "@/components/shell/Masthead";
import OverviewTab from "@/components/genetics/OverviewTab";
import PrioritiesTab from "@/components/genetics/PrioritiesTab";
import BreedingSuggestionsTab from "@/components/genetics/BreedingSuggestionsTab";

type TabValue = "oversikt" | "prioriteringar" | "parningsforslag";

const genebankNames: Record<number, string> = {
  1: "Gotlandskanin",
  2: "Mellerudskanin",
};

interface TabPanelProps {
  children?: React.ReactNode;
  value: TabValue;
  index: TabValue;
}

function TabPanel({ children, value, index }: TabPanelProps) {
  return (
    <div role="tabpanel" hidden={value !== index}>
      {value === index && (
        <Box
          sx={{
            pt: 3,
          }}
        >
          {children}
        </Box>
      )}
    </div>
  );
}

function GenetikPage() {
  const { user } = useAuth();
  const searchParams = useSearchParams();

  const initialTab = (searchParams.get("tab") as TabValue) || "oversikt";
  const [activeTab, setActiveTab] = useState<TabValue>(initialTab);

  const genebankParam = searchParams.get("genebank");
  const [genebankId, setGenebankId] = useState<number | "">(
    genebankParam ? Number(genebankParam) : user?.is_manager?.[0] || "",
  );

  // Sync genebankId when navigating via sidebar links or when user data loads
  React.useEffect(() => {
    if (genebankParam) {
      setGenebankId(Number(genebankParam));
    } else if (genebankId === "" && user?.is_manager?.[0]) {
      setGenebankId(user.is_manager[0]);
    }
  }, [genebankParam, user?.is_manager, genebankId]);

  // Genebanks the user can access
  const availableGenebanks: number[] = user?.is_admin
    ? [1, 2]
    : user?.is_manager || [];

  const handleTabChange = (_: React.SyntheticEvent, newValue: TabValue) => {
    setActiveTab(newValue);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", newValue);
    window.history.pushState(null, "", url.toString());
  };

  return (
    <React.Fragment>
      <Masthead
        eyebrow="Stamboken"
        title="Genetik"
        meta="Populationsgenetisk analys och avelsrekommendationer"
        actions={
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Genbank</InputLabel>
            <Select
              value={genebankId}
              label="Genbank"
              onChange={(e) => setGenebankId(e.target.value as number)}
            >
              {availableGenebanks.map((id) => (
                <MenuItem key={id} value={id}>
                  {genebankNames[id] || `Genbank ${id}`}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        }
      />

      {!genebankId ? (
        <Alert severity="info">Välj en genbank för att visa genetikdata.</Alert>
      ) : (
        <>
          <Tabs value={activeTab} onChange={handleTabChange}>
            <Tab label="Översikt" value="oversikt" />
            <Tab label="Prioriteringar" value="prioriteringar" />
            <Tab label="Parningsförslag" value="parningsforslag" />
          </Tabs>

          <TabPanel value={activeTab} index="oversikt">
            <OverviewTab genebankId={genebankId} />
          </TabPanel>

          <TabPanel value={activeTab} index="prioriteringar">
            <PrioritiesTab genebankId={genebankId} />
          </TabPanel>

          <TabPanel value={activeTab} index="parningsforslag">
            {/* keyed so the form resets when the genebank changes */}
            <BreedingSuggestionsTab key={genebankId} genebankId={genebankId} />
          </TabPanel>
        </>
      )}
    </React.Fragment>
  );
}

export default function GenetikPageWithSuspense() {
  return (
    <Suspense>
      <GenetikPage />
    </Suspense>
  );
}
