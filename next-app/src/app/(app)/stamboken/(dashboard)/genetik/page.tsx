"use client";

import React, { Suspense, useEffect } from "react";
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

const TABS = ["oversikt", "prioriteringar", "parningsforslag"] as const;
type TabValue = (typeof TABS)[number];

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

  // Genebanks the user can access
  const availableGenebanks: number[] = user?.is_admin
    ? [1, 2]
    : user?.is_manager || [];

  // The URL holds the tab and the genebank: Back and Forward switch them, and a
  // link opens the same view. Next feeds pushState and popstate into useSearchParams.
  const tabParam = searchParams.get("tab");
  const activeTab: TabValue = TABS.find((t) => t === tabParam) ?? "oversikt";
  const genebankParam = searchParams.get("genebank");
  // A genebank in the URL that the user cannot open falls back to the first one they can.
  const genebankId: number | "" = genebankParam
    ? availableGenebanks.includes(Number(genebankParam))
      ? Number(genebankParam)
      : (availableGenebanks[0] ?? "")
    : user?.is_manager?.[0] || "";

  // The URL then says so too, replaced so that Back does not return to it.
  useEffect(() => {
    if (!user || !genebankParam || Number(genebankParam) === genebankId) return;
    const url = new URL(window.location.href);
    if (genebankId) url.searchParams.set("genebank", String(genebankId));
    else url.searchParams.delete("genebank");
    window.history.replaceState(null, "", url.toString());
  }, [user, genebankParam, genebankId]);

  const pushParam = (key: string, value: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set(key, value);
    window.history.pushState(null, "", url.toString());
  };

  const handleTabChange = (_: React.SyntheticEvent, newValue: TabValue) =>
    pushParam("tab", newValue);

  return (
    <React.Fragment>
      <Masthead
        eyebrow="Stamboken"
        title="Genetik"
        meta="Genbankens genetiska läge och vilka kaniner som är viktigast att avla på"
        actions={
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Genbank</InputLabel>
            <Select
              value={genebankId}
              label="Genbank"
              onChange={(e) => pushParam("genebank", String(e.target.value))}
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
        // Until the user has loaded, the page cannot tell which genebanks are theirs.
        user && (
          <Alert severity="info">
            Välj en genbank för att visa genetikdata.
          </Alert>
        )
      ) : (
        <>
          <Tabs value={activeTab} onChange={handleTabChange}>
            <Tab label="Översikt" value="oversikt" />
            <Tab label="Avelsprioritet" value="prioriteringar" />
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
