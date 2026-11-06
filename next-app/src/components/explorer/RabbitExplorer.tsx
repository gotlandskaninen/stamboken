"use client";

import React, { useState, useCallback, useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  Box,
  Card,
  CardContent,
  Chip,
  Typography,
  Tooltip,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  useMediaQuery,
} from "@mui/material";
import { Male as MaleIcon, Female as FemaleIcon } from "@mui/icons-material";
import {
  DataGrid,
  GridColDef,
  GridSortModel,
  GridPaginationModel,
  GridToolbarColumnsButton,
  GridToolbarContainer,
} from "@mui/x-data-grid";
import { Masthead } from "@/components/shell/Masthead";
import {
  useFetchIndividualsQuery,
  PaginatedIndividualItem,
  PaginatedIndividualsResponse,
} from "@/redux/api/apiSlice";
import { useDebounce } from "@/hooks/useDebounce";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import styles from "./explorer.module.css";

// Status options matching the backend's _derive_individual_status()
const STATUS_OPTIONS: {
  value: string;
  label: string;
  color: "success" | "error" | "warning" | "default" | "info";
}[] = [
  { value: "", label: "Alla", color: "default" },
  { value: "active", label: "Aktiv", color: "success" },
  { value: "inactive", label: "Inaktiv", color: "default" },
  { value: "död", label: "Död", color: "error" },
  { value: "slaktad", label: "Slaktad", color: "error" },
  { value: "avlivad", label: "Avlivad", color: "error" },
  { value: "försvunnen", label: "Försvunnen", color: "warning" },
];

const GENEBANK_OPTIONS = [
  { value: 0, label: "Alla" },
  { value: 1, label: "Gotlandskanin" },
  { value: 2, label: "Mellerudskanin" },
] as const;

const SEX_OPTIONS = [
  { value: "", label: "Alla" },
  { value: "female", label: "Hona" },
  { value: "male", label: "Hane" },
] as const;

function ExplorerToolbar() {
  return (
    <GridToolbarContainer>
      <GridToolbarColumnsButton />
    </GridToolbarContainer>
  );
}

function getStatusChipColor(
  status: string,
): "success" | "error" | "warning" | "default" | "info" {
  return STATUS_OPTIONS.find((opt) => opt.value === status)?.color || "default";
}

function getStatusLabel(status: string): string {
  return STATUS_OPTIONS.find((opt) => opt.value === status)?.label || status;
}

function individualHref(number: string): string {
  return `/stamboken/individ/${encodeURIComponent(number)}`;
}

// sb-badge tone per status, same convention as Min besättning (MbStatus)
function getStatusBadgeClass(status: string): string {
  if (status === "active") return "sb-badge sb-badge-mossa";
  if (status === "försvunnen") return "sb-badge sb-badge-lera";
  return "sb-badge";
}

function ExplorerMobileRow({ rabbit }: { rabbit: PaginatedIndividualItem }) {
  return (
    <Link href={individualHref(rabbit.number)} className={styles["ex-row"]}>
      <div className={styles["ex-id"]}>
        <span className="sb-meta">{rabbit.number}</span>
        <span className={styles["ex-name"]}>{rabbit.name || "Namnlös"}</span>
      </div>
      <div className={styles["ex-meta"]}>
        {(rabbit.sex === "female" || rabbit.sex === "male") && (
          <span className={styles["ex-sex"]} data-sex={rabbit.sex}>
            {rabbit.sex === "female" ? "♀ Hona" : "♂ Hane"}
          </span>
        )}
        <span>{rabbit.herd}</span>
        {rabbit.birth_date && <span>{rabbit.birth_date.slice(0, 10)}</span>}
      </div>
      <div className={styles["ex-badges"]}>
        <span className={getStatusBadgeClass(rabbit.status)}>
          {getStatusLabel(rabbit.status)}
        </span>
      </div>
      <span className={styles["ex-chevron"]} aria-hidden="true">
        ›
      </span>
    </Link>
  );
}

const columns: GridColDef<PaginatedIndividualItem>[] = [
  {
    field: "number",
    headerName: "Individnummer",
    width: 150,
    renderCell: (params) => (
      <Typography
        variant="body2"
        sx={{
          fontWeight: "medium",
        }}
      >
        {params.value || "Inget nummer"}
      </Typography>
    ),
  },
  {
    field: "name",
    headerName: "Namn",
    width: 150,
    renderCell: (params) => (
      <Typography variant="body2">{params.value || "Namnlös"}</Typography>
    ),
  },
  {
    field: "sex",
    headerName: "Kön",
    width: 100,
    sortable: false,
    renderCell: (params) => {
      const sex = params.value as string | null;
      if (!sex) return "-";
      return (
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 0.5,
          }}
        >
          {sex === "female" ? (
            <FemaleIcon fontSize="small" color="secondary" />
          ) : sex === "male" ? (
            <MaleIcon fontSize="small" color="primary" />
          ) : null}
          <Typography variant="body2">
            {sex === "female" ? "Hona" : sex === "male" ? "Hane" : "Okänt"}
          </Typography>
        </Box>
      );
    },
  },
  {
    field: "birth_date",
    headerName: "Födelsedatum",
    width: 130,
    valueFormatter: (value) => {
      if (!value) return "-";
      return new Date(value as string).toLocaleDateString("sv-SE");
    },
  },
  {
    field: "status",
    headerName: "Status",
    width: 120,
    sortable: false,
    renderCell: (params) => (
      <Tooltip title={getStatusLabel(params.value)}>
        <Chip
          label={getStatusLabel(params.value)}
          color={getStatusChipColor(params.value)}
          size="small"
          sx={{ minWidth: 80 }}
        />
      </Tooltip>
    ),
  },
  {
    field: "herd",
    headerName: "Besättning",
    width: 120,
    sortable: false,
  },
  {
    field: "litter_size",
    headerName: "Kullstorlek",
    width: 110,
    sortable: false,
    type: "number",
    valueFormatter: (value) =>
      value !== null && value !== undefined ? `${value}` : "-",
  },
  {
    field: "mother_number",
    headerName: "Mor",
    width: 130,
    sortable: false,
    renderCell: (params) => {
      const num = params.value as string | null;
      const name = params.row.mother_name;
      if (!num) return "-";
      return (
        <Tooltip title={name || "Namnlös"}>
          <Typography variant="body2">{num}</Typography>
        </Tooltip>
      );
    },
  },
  {
    field: "father_number",
    headerName: "Far",
    width: 130,
    sortable: false,
    renderCell: (params) => {
      const num = params.value as string | null;
      const name = params.row.father_name;
      if (!num) return "-";
      return (
        <Tooltip title={name || "Namnlös"}>
          <Typography variant="body2">{num}</Typography>
        </Tooltip>
      );
    },
  },
  {
    field: "color",
    headerName: "Färg",
    width: 120,
    sortable: false,
    valueFormatter: (value) => (value as string) || "-",
  },
  {
    field: "litter_size6w",
    headerName: "Kullstorlek 6v",
    width: 130,
    sortable: false,
    type: "number",
    valueFormatter: (value) =>
      value !== null && value !== undefined ? `${value}` : "-",
  },
];

interface MobileListState {
  source: PaginatedIndividualsResponse | null;
  queryKey: string; // the list query minus its page
  firstPage: number;
  page: number;
  totalPages: number;
  items: PaginatedIndividualItem[];
}

// The next page of the same query → append; anything else (a new filter,
// search, sort or page size, or a non-adjacent page) → start over.
function nextMobileList(
  prev: MobileListState,
  response: PaginatedIndividualsResponse,
  queryKey: string,
): MobileListState {
  const next = {
    source: response,
    queryKey,
    page: response.page,
    totalPages: response.total_pages,
  };
  if (queryKey !== prev.queryKey || response.page !== prev.page + 1) {
    return { ...next, firstPage: response.page, items: response.items };
  }
  const seen = new Set(prev.items.map((item) => item.number));
  return {
    ...next,
    firstPage: prev.firstPage,
    items: [
      ...prev.items,
      ...response.items.filter((item) => !seen.has(item.number)),
    ],
  };
}

interface RabbitExplorerProps {
  initialData: PaginatedIndividualsResponse | null;
}

export default function RabbitExplorer({ initialData }: RabbitExplorerProps) {
  const { t } = useTranslation();
  const router = useRouter();
  // CSS picks list vs grid on first paint; after hydration phones also
  // unmount the (hidden) grid so it neither renders rows nor warns about
  // its zero-height parent.
  const isDesktop = useMediaQuery("(min-width: 900px)", {
    defaultMatches: true,
  });

  // State for server-side pagination, sorting, filtering
  const [paginationModel, setPaginationModel] = useState<GridPaginationModel>({
    page: 0,
    pageSize: DEFAULT_PAGE_SIZE,
  });
  const [sortModel, setSortModel] = useState<GridSortModel>([
    { field: "name", sort: "asc" },
  ]);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search, 300);
  const [selectedGenebank, setSelectedGenebank] = useState(0);
  const [selectedStatus, setSelectedStatus] = useState("");
  const [selectedSex, setSelectedSex] = useState("");

  // Track whether user has interacted (sort, filter, search, paginate)
  const [userHasInteracted, setUserHasInteracted] = useState(false);

  // Reset to page 0 when debounced search changes (skip initial render)
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    setUserHasInteracted(true);
    setPaginationModel((prev) => ({ ...prev, page: 0 }));
  }, [debouncedSearch]);

  const listQuery = {
    per_page: paginationModel.pageSize,
    sort: sortModel[0]?.field || "name",
    order: sortModel[0]?.sort || "asc",
    genebank_id: selectedGenebank || null,
    search: debouncedSearch || undefined,
    status: selectedStatus || null,
    sex: selectedSex || null,
  };
  const listQueryKey = JSON.stringify(listQuery);

  // Skip client fetch only for pristine initial state — once user interacts, always fetch
  const { data, currentData, isLoading, error, isFetching } =
    useFetchIndividualsQuery(
      {
        ...listQuery,
        page: paginationModel.page + 1, // DataGrid is 0-indexed, API is 1-indexed
      },
      { skip: !userHasInteracted && !!initialData },
    );

  const displayData = !userHasInteracted && initialData ? initialData : data;

  // Mobile list accumulates pages ("Visa fler"); the DataGrid shows one page.
  // Only currentData (never RTK Query's retained previous result) is
  // accumulated, so every response is tied to listQueryKey. Adjusted during
  // render, not in an effect.
  const [mobileList, setMobileList] = useState<MobileListState>({
    source: initialData,
    queryKey: listQueryKey,
    firstPage: initialData?.page ?? 1,
    page: initialData?.page ?? 0,
    totalPages: initialData?.total_pages ?? 0,
    items: initialData?.items ?? [],
  });
  const mobileSource =
    !userHasInteracted && initialData ? initialData : currentData;
  if (mobileSource && mobileSource !== mobileList.source) {
    setMobileList(nextMobileList(mobileList, mobileSource, listQueryKey));
  }

  // On mobile the list must start at page 1. A page reached in the grid
  // (possibly still loading when the viewport drops below 900px) can't be
  // its top, so restart from page 1. On phones the list already starts at
  // page 1 after hydration and nothing resets.
  if (!isDesktop && mobileList.firstPage !== 1 && paginationModel.page !== 0) {
    setPaginationModel({ ...paginationModel, page: 0 });
  }

  const handleShowMore = useCallback(() => {
    setUserHasInteracted(true);
    setPaginationModel((prev) => ({ ...prev, page: prev.page + 1 }));
  }, []);

  const handleRowClick = useCallback(
    (params: { row: PaginatedIndividualItem }) => {
      router.push(individualHref(params.row.number));
    },
    [router],
  );

  const handleSortModelChange = useCallback((model: GridSortModel) => {
    setUserHasInteracted(true);
    setSortModel(model);
    setPaginationModel((prev) => ({ ...prev, page: 0 }));
  }, []);

  const handleGenebankChange = useCallback((value: number) => {
    setUserHasInteracted(true);
    setSelectedGenebank(value);
    setPaginationModel((prev) => ({ ...prev, page: 0 }));
  }, []);

  const handleSexChange = useCallback((value: string) => {
    setUserHasInteracted(true);
    setSelectedSex(value);
    setPaginationModel((prev) => ({ ...prev, page: 0 }));
  }, []);

  const handleStatusChange = useCallback((value: string) => {
    setUserHasInteracted(true);
    setSelectedStatus(value);
    setPaginationModel((prev) => ({ ...prev, page: 0 }));
  }, []);

  const handlePaginationModelChange = useCallback(
    (model: GridPaginationModel) => {
      setUserHasInteracted(true);
      setPaginationModel(model);
    },
    [],
  );

  if (error) {
    return (
      <Box
        sx={{
          p: 4,
        }}
      >
        <Alert severity="error">
          Kunde inte ladda kaniner. Försök igen senare.
        </Alert>
      </Box>
    );
  }

  return (
    <React.Fragment>
      <Masthead
        eyebrow="Stamboken"
        title={t("explorer.title", "Alla kaniner")}
        meta={t("explorer.subtitle", "Utforska alla kaniner i genbanken")}
      />

      <Card>
        <CardContent>
          {/* Filters row */}
          <Box
            sx={{
              display: "flex",
              gap: 2,
              mb: 3,
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            {/* Gene bank toggle */}
            <div style={{ display: "flex", gap: 8 }}>
              {GENEBANK_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  title={t("explorer.genebank", "Genbank")}
                  aria-pressed={selectedGenebank === opt.value}
                  className={
                    selectedGenebank === opt.value
                      ? "sb-btn sb-btn-sm"
                      : "sb-btn sb-btn-sm sb-btn-secondary"
                  }
                  onClick={() => handleGenebankChange(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* Search field */}
            <div style={{ flex: 1, minWidth: 250 }}>
              <input
                type="search"
                className="sb-input"
                placeholder={t(
                  "explorer.search",
                  "Sök på individnummer eller namn...",
                )}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label={t(
                  "explorer.search",
                  "Sök på individnummer eller namn...",
                )}
              />
            </div>

            {/* Status filter */}
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>{t("explorer.status", "Status")}</InputLabel>
              <Select
                value={selectedStatus}
                onChange={(e) => handleStatusChange(e.target.value)}
                label={t("explorer.status", "Status")}
              >
                {STATUS_OPTIONS.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {/* Sex filter */}
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel>{t("explorer.sex", "Kön")}</InputLabel>
              <Select
                value={selectedSex}
                onChange={(e) => handleSexChange(e.target.value)}
                label={t("explorer.sex", "Kön")}
              >
                {SEX_OPTIONS.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>

          {/* Result count */}
          {displayData && (
            <Box
              sx={{
                mb: 2,
              }}
            >
              <span className="sb-meta">
                {displayData.total_count.toLocaleString("sv-SE")} kaniner
                {isFetching && !isLoading && " (laddar...)"}
              </span>
            </Box>
          )}

          {/* Mobile list (<900px) */}
          <div className={styles["ex-list"]} data-testid="explorer-mobile-list">
            {mobileList.items.map((rabbit) => (
              <ExplorerMobileRow key={rabbit.number} rabbit={rabbit} />
            ))}
            {mobileList.source && mobileList.items.length === 0 && (
              <p className={styles["ex-empty"]}>Inga kaniner hittades</p>
            )}
            {mobileList.page < mobileList.totalPages && (
              <div className={styles["ex-more"]}>
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary"
                  onClick={handleShowMore}
                  disabled={isFetching}
                >
                  {isFetching ? "Laddar..." : "Visa fler"}
                </button>
              </div>
            )}
          </div>

          {/* Server-side DataGrid (≥900px) */}
          <Box
            className={styles["ex-grid"]}
            sx={{ height: 650, width: "100%" }}
          >
            {isDesktop && (
              <DataGrid
                rows={displayData?.items || []}
                columns={columns}
                rowCount={displayData?.total_count || 0}
                paginationMode="server"
                sortingMode="server"
                filterMode="server"
                disableColumnFilter
                slots={{ toolbar: ExplorerToolbar }}
                paginationModel={paginationModel}
                onPaginationModelChange={handlePaginationModelChange}
                sortModel={sortModel}
                onSortModelChange={handleSortModelChange}
                pageSizeOptions={[25, 50, 100]}
                initialState={{
                  columns: {
                    columnVisibilityModel: {
                      litter_size6w: false,
                    },
                  },
                }}
                getRowId={(row) => row.number}
                loading={isFetching}
                onRowClick={handleRowClick}
                disableRowSelectionOnClick
                sx={{
                  "& .MuiDataGrid-row": {
                    cursor: "pointer",
                  },
                  "& .MuiDataGrid-cell": {
                    display: "flex",
                    alignItems: "center",
                  },
                }}
                localeText={{
                  toolbarColumns: "Kolumner",
                  toolbarColumnsLabel: "Välj kolumner",
                  columnsManagementSearchTitle: "Sök",
                  columnsManagementShowHideAllText: "Visa/dölj alla",
                  columnsManagementReset: "Återställ",
                  noRowsLabel: "Inga kaniner hittades",
                  noResultsOverlayLabel: "Inga resultat hittades",
                  columnMenuLabel: "Meny",
                  columnMenuShowColumns: "Visa kolumner",
                  columnMenuManageColumns: "Hantera kolumner",
                  columnMenuHideColumn: "Dölj",
                  columnMenuUnsort: "Ta bort sortering",
                  columnMenuSortAsc: "Sortera stigande",
                  columnMenuSortDesc: "Sortera fallande",
                  columnHeaderSortIconLabel: "Sortera",
                  paginationRowsPerPage: "Rader per sida:",
                  paginationItemAriaLabel: (type) =>
                    type === "first"
                      ? "Gå till första sidan"
                      : type === "last"
                        ? "Gå till sista sidan"
                        : type === "next"
                          ? "Gå till nästa sida"
                          : "Gå till föregående sida",
                  paginationDisplayedRows: ({ from, to, count }) =>
                    `${from}–${to} av ${count !== -1 ? count : `fler än ${to}`}`,
                  footerRowSelected: (count) =>
                    count !== 1
                      ? `${count.toLocaleString()} rader valda`
                      : `${count.toLocaleString()} rad vald`,
                }}
                showToolbar
              />
            )}
          </Box>
        </CardContent>
      </Card>
    </React.Fragment>
  );
}
