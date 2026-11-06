"use client";

import React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useUser } from "@/lib/user-context";
import {
  registerBreeding as registerBreedingAction,
  registerBirth as registerBirthAction,
  updateBreeding as updateBreedingAction,
  deleteBreeding as deleteBreedingAction,
} from "./actions";
import { useNotifications } from "@/contexts/NotificationContext";
import { useSnackbar } from "@/components/SnackbarProvider";
import { useTranslation } from "react-i18next";

import { Masthead } from "@/components/shell/Masthead";
import { HerdSwitcher } from "@/components/shell/HerdSwitcher";
import { TabBar } from "@/components/shell/TabBar";
import { MB_TABS, TabPanel, type TabValue } from "./min-besattning-ui";
import OversiktTab from "./OversiktTab";
import KaninerTab from "./KaninerTab";
import KullarTab from "./KullarTab";
import SlakttradTab from "./SlakttradTab";
import styles from "./min-besattning.module.css";

interface MinBesattningContentProps {
  herd: any | null;
  breedings: any[] | null;
  herdNumber: string | null;
  initialTab: string | null;
}

export default function MinBesattningContent({
  herd,
  breedings,
  herdNumber,
  initialTab,
}: MinBesattningContentProps) {
  const router = useRouter();
  const user = useUser();
  const { t } = useTranslation();

  // Suppress interactive content until hydration completes — SSR HTML includes
  // buttons that aren't wired to React event handlers yet. Without this guard,
  // Playwright clicks the SSR button before hydration and the click is lost.
  const [isHydrated, setIsHydrated] = React.useState(false);
  React.useEffect(() => setIsHydrated(true), []);

  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  // Use server-provided initialTab for first render (available before Suspense resolves)
  const effectiveInitialTab = initialTab || tabParam;
  const [activeTab, setActiveTab] = React.useState<TabValue>(
    effectiveInitialTab === "individuals" ||
      effectiveInitialTab === "breeding" ||
      effectiveInitialTab === "pedigree"
      ? effectiveInitialTab
      : "overview",
  );

  React.useEffect(() => {
    if (
      tabParam === "overview" ||
      tabParam === "individuals" ||
      tabParam === "breeding" ||
      tabParam === "pedigree"
    ) {
      setActiveTab(tabParam);
    }
  }, [tabParam]);

  const { addNotification } = useNotifications();
  const { showSnackbar } = useSnackbar();

  // Translate common backend error messages to current language
  const translateBackendError = (msg: string): string => {
    const map: Record<string, string> = {
      "Breeding already registered": t("breeding.alreadyRegistered"),
      Forbidden: t("breeding.forbidden"),
      "Not logged in": t("breeding.notLoggedIn"),
      "Birth already registered.": t("breeding.birthAlreadyRegistered"),
    };
    return map[msg] || msg;
  };

  // Helper: show error snackbar + persistent notification with admin info
  const showBreedingError = (message: string, context: string) => {
    const translated = translateBackendError(message);
    showSnackbar(translated, "error");
    addNotification({
      title: context,
      message: translated,
      type: "error",
      action: {
        label: "Kopiera felinfo",
        onClick: () => {
          navigator.clipboard.writeText(
            `${context}: ${message} (${new Date().toISOString()})`,
          );
          showSnackbar("Felinfo kopierad till clipboard", "info");
        },
      },
    });
  };

  // Herd ID comes from server (page.tsx reads searchParams.herd)
  const userHerdId = herdNumber || user?.is_owner?.[0];

  // Data always comes from server props (SSR via page.tsx)
  const herdData = herd;
  const breedingList = breedings;

  const [showLitterForm, setShowLitterForm] = React.useState(false);
  const [isSubmittingLitter, setIsSubmittingLitter] = React.useState(false);
  const [showMatingForm, setShowMatingForm] = React.useState(false);
  const [isSubmittingMating, setIsSubmittingMating] = React.useState(false);
  const [deletingBreedingId, setDeletingBreedingId] = React.useState<
    number | null
  >(null);

  // Derive genebank ID from herd prefix
  const genebankId = userHerdId?.startsWith("G")
    ? 1
    : userHerdId?.startsWith("M")
      ? 2
      : null;

  const handleLitterSubmit = async (data: {
    mother: string;
    father: string;
    birthDate: string;
    breedingDate: string;
    totalBorn: number;
    aliveAt6w: number | null;
    birthNotes: string;
    breedingHerd: string;
  }): Promise<boolean> => {
    setIsSubmittingLitter(true);
    try {
      // Check if a matching breeding already exists (same parents, no birth yet)
      // This handles: (a) mating registered earlier via "Ny parning"
      //               (b) retry after a failed birth call left an orphan breeding
      // Pick the most recent open mating within gestation window (26-38 days before birth)
      const birthDate = new Date(data.birthDate);
      const openMatings = (breedingList || [])
        .filter(
          (b: any) =>
            b.mother === data.mother &&
            b.father === data.father &&
            !b.birth_date &&
            b.breed_date,
        )
        .map((b: any) => ({
          ...b,
          _daysBeforeBirth: Math.round(
            (birthDate.getTime() - new Date(b.breed_date).getTime()) / 86400000,
          ),
        }))
        .filter(
          (b: any) => b._daysBeforeBirth >= 20 && b._daysBeforeBirth <= 45,
        )
        .sort(
          (a: any, b: any) =>
            Math.abs(a._daysBeforeBirth - 31) -
            Math.abs(b._daysBeforeBirth - 31),
        );
      const existingBreeding = openMatings[0] || null;

      let breedingId: number;

      if (existingBreeding) {
        // Reuse existing breeding record
        breedingId = existingBreeding.id;
      } else {
        // Create new breeding event (date = estimated breeding date)
        const breedingResult = await registerBreedingAction({
          father: data.father,
          mother: data.mother,
          date: data.breedingDate,
          notes: "",
          breeding_herd: data.breedingHerd,
        });

        if (!breedingResult.success) {
          showBreedingError(
            breedingResult.error || t("breeding.couldNotRegisterMating"),
            t("breeding.couldNotRegisterMating"),
          );
          return false;
        }
        breedingId = breedingResult.data.id;
      }

      // Register birth info on the breeding record
      const birthResult = await registerBirthAction(breedingId, {
        date: data.birthDate,
        litter_size: data.totalBorn,
        litter_size6w: data.aliveAt6w,
        notes: data.birthNotes || undefined,
      });

      if (!birthResult.success) {
        showBreedingError(
          birthResult.error || t("breeding.couldNotRegisterLitter"),
          t("breeding.couldNotRegisterLitter"),
        );
        return false;
      }

      showSnackbar(t("breeding.litterRegistered"), "success");

      setShowLitterForm(false);
      return true;
    } catch {
      showBreedingError(
        t("breeding.errorRegistering"),
        t("breeding.errorRegistering"),
      );
      return false;
    } finally {
      setIsSubmittingLitter(false);
    }
  };

  const handleMatingSubmit = async (data: {
    mother: string;
    father: string;
    matingDate: string;
    breedNotes: string;
    breedingHerd: string;
  }): Promise<boolean> => {
    setIsSubmittingMating(true);
    try {
      const result = await registerBreedingAction({
        father: data.father,
        mother: data.mother,
        date: data.matingDate,
        notes: data.breedNotes || "",
        breeding_herd: data.breedingHerd,
      });

      if (!result.success) {
        showBreedingError(
          result.error || t("breeding.couldNotRegisterMating"),
          t("breeding.couldNotRegisterMating"),
        );
        return false;
      }

      showSnackbar(t("breeding.matingRegisteredMsg"), "success");

      setShowMatingForm(false);
      return true;
    } catch {
      showBreedingError(
        t("breeding.errorRegistering"),
        t("breeding.errorRegistering"),
      );
      return false;
    } finally {
      setIsSubmittingMating(false);
    }
  };

  const handleDeleteBreeding = async (breedingId: number) => {
    setDeletingBreedingId(breedingId);
    try {
      const result = await deleteBreedingAction(breedingId);
      if (result.success) {
        showSnackbar(t("breeding.breedingDeleted"), "success");
      } else {
        showBreedingError(
          result.error || t("breeding.couldNotDelete"),
          t("breeding.couldNotDelete"),
        );
      }
    } catch {
      showBreedingError(t("breeding.errorGeneric"), t("breeding.errorGeneric"));
    } finally {
      setDeletingBreedingId(null);
    }
  };

  // The former inline onRegisterBirth/onUpdate lambdas on <BreedingList> become
  // named handlers so KullarTab can receive them:
  const handleRegisterBirth = async (data: {
    breedingId: number;
    date: string;
    litter_size: number;
    litter_size6w?: number | null;
    notes?: string;
  }): Promise<boolean> => {
    const result = await registerBirthAction(data.breedingId, {
      date: data.date,
      litter_size: data.litter_size,
      litter_size6w: data.litter_size6w,
      notes: data.notes,
    });
    if (result.success) {
      showSnackbar(t("breeding.litterRegistered"), "success");
      return true;
    }
    showBreedingError(
      result.error || t("breeding.couldNotRegisterLitter"),
      t("breeding.couldNotRegisterLitter"),
    );
    return false;
  };

  const handleUpdateBreeding = async (data: {
    id: number;
    [key: string]: unknown;
  }): Promise<boolean> => {
    const { id, ...rest } = data;
    const result = await updateBreedingAction(id, rest);
    if (result.success) {
      showSnackbar(t("breeding.updated"), "success");
      return true;
    }
    showBreedingError(
      result.error || t("breeding.errorGeneric"),
      t("breeding.editTitle"),
    );
    return false;
  };

  // Programmatic tab change (quick actions, "Se alla kaniner →" links) — same
  // URL contract as the old MUI Tabs onChange
  const goTab = (tab: TabValue) => {
    setActiveTab(tab);
    const params = new URLSearchParams();
    params.set("tab", tab);
    if (userHerdId) params.set("herd", userHerdId);
    router.replace(`/stamboken/min-besattning?${params.toString()}`, {
      scroll: false,
    });
  };

  const makeTabHref = (key: string) => {
    const params = new URLSearchParams();
    params.set("tab", key);
    if (userHerdId) params.set("herd", userHerdId);
    return `/stamboken/min-besattning?${params.toString()}`;
  };

  const tabBar = (
    <TabBar
      tabs={MB_TABS}
      active={activeTab}
      makeHref={makeTabHref}
      idBase="herd"
    />
  );

  // Show loading until hydration completes
  if (!isHydrated) {
    return (
      <React.Fragment>
        {tabBar}
        <div className={`${styles["mb-container"]} ${styles["mb-main"]}`}>
          <p className="sb-meta">Laddar…</p>
        </div>
      </React.Fragment>
    );
  }

  if (!herdData || !userHerdId) {
    const isTransientError = userHerdId && !herdData;
    return (
      <div className={`${styles["mb-container"]} ${styles["mb-main"]}`}>
        <div className={styles["mb-empty"]}>
          <h2 className="sb-h6">
            {!userHerdId
              ? "Ingen besättning hittad"
              : "Kunde inte ladda besättningsdata"}
          </h2>
          <p>
            {!userHerdId
              ? "Du verkar inte vara ägare till någon besättning."
              : "Ett fel uppstod när besättningsdata skulle hämtas."}
          </p>
          {isTransientError && (
            <button
              type="button"
              className="sb-btn sb-btn-secondary"
              onClick={() => router.refresh()}
            >
              Försök igen
            </button>
          )}
        </div>
      </div>
    );
  }

  const breed = userHerdId.startsWith("G") ? "Gotlandskanin" : "Mellerudskanin";
  const sinceYear = herdData.start_date
    ? String(herdData.start_date).slice(0, 4)
    : null;

  return (
    <React.Fragment>
      <Masthead
        eyebrow={`Besättning ${userHerdId}`}
        title={herdData.herd_name || `Besättning ${userHerdId}`}
        meta={
          <React.Fragment>
            {breed}
            {sinceYear ? ` · Genbanksbesättning sedan ${sinceYear}` : null}
            {" · "}
            <span className="sb-tag-dot">
              {herdData.is_active ? "Aktiv" : "Inaktiv"}
            </span>
          </React.Fragment>
        }
        actions={
          user?.is_owner && user.is_owner.length > 1 ? (
            <HerdSwitcher
              herds={user.is_owner.map((id) => ({ id, label: id }))}
              active={userHerdId}
            />
          ) : undefined
        }
      />
      {tabBar}
      <div className={`${styles["mb-container"]} ${styles["mb-main"]}`}>
        <TabPanel value={activeTab} index="overview">
          <OversiktTab
            herd={herdData}
            breedings={breedingList}
            herdNumber={userHerdId}
            onGoTab={goTab}
            onNewLitter={() => {
              setShowLitterForm(true);
              setShowMatingForm(false);
              goTab("breeding");
            }}
            onNewMating={() => {
              setShowMatingForm(true);
              setShowLitterForm(false);
              goTab("breeding");
            }}
          />
        </TabPanel>
        <TabPanel value={activeTab} index="individuals">
          <KaninerTab
            individuals={herdData?.individuals || []}
            herdNumber={userHerdId}
            genebankId={genebankId}
          />
        </TabPanel>
        <TabPanel value={activeTab} index="breeding">
          <KullarTab
            breedings={breedingList}
            userHerdId={userHerdId}
            genebankId={genebankId}
            showLitterForm={showLitterForm}
            showMatingForm={showMatingForm}
            isSubmittingLitter={isSubmittingLitter}
            isSubmittingMating={isSubmittingMating}
            deletingBreedingId={deletingBreedingId}
            onShowLitterForm={(v) => {
              setShowLitterForm(v);
              if (v) setShowMatingForm(false);
            }}
            onShowMatingForm={(v) => {
              setShowMatingForm(v);
              if (v) setShowLitterForm(false);
            }}
            onLitterSubmit={handleLitterSubmit}
            onMatingSubmit={handleMatingSubmit}
            onDeleteBreeding={handleDeleteBreeding}
            onRegisterBirth={handleRegisterBirth}
            onUpdateBreeding={handleUpdateBreeding}
          />
        </TabPanel>
        <TabPanel value={activeTab} index="pedigree">
          <SlakttradTab individuals={herdData?.individuals || []} />
        </TabPanel>
      </div>
    </React.Fragment>
  );
}
