import {
  createApi,
  fetchBaseQuery,
  BaseQueryFn,
  FetchArgs,
  FetchBaseQueryError,
} from "@reduxjs/toolkit/query/react";
import { User } from "@/types/auth";
import { sessionExpired } from "@/redux/slices/authSlice";
import { readModeCookieClient } from "@/lib/mode";
import type { TestbreedRequest, TestbreedResponse } from "@/lib/provparning";

// NEXT_PUBLIC_* is inlined into the client bundle at build time, so this is a
// client-visible presence signal — the browser-side equivalent of lib/api.ts's
// API_TEST_INTERNAL_URL check. Undefined in base dev, which keeps demo on /api.
const API_TEST_URL = process.env.NEXT_PUBLIC_API_TEST_URL;

// Paginated response from GET /api/individuals (Story 3.1 API)
export interface PaginatedIndividualItem {
  number: string;
  name: string | null;
  sex: string | null;
  birth_date: string | null;
  status: string;
  herd: string;
  color: string | null;
  has_photo: boolean;
  litter_size: number | null;
  litter_size6w: number | null;
  mother_number: string | null;
  mother_name: string | null;
  father_number: string | null;
  father_name: string | null;
}

export interface PaginatedIndividualsResponse {
  items: PaginatedIndividualItem[];
  total_count: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface FetchIndividualsParams {
  page?: number;
  per_page?: number;
  sort?: string;
  order?: "asc" | "desc";
  genebank_id?: number | null;
  search?: string;
  status?: string | null;
  sex?: string | null;
  herd_id?: string | null;
  include_historical?: boolean;
}

// Based on old theherdbook interfaces
export type PrivacyLevel = "private" | "authenticated" | "public" | null;

export interface HerdNameID {
  herd_name?: string;
  herd: string;
  id?: number;
}

export interface DateValue {
  date: string;
  value: string | number;
  id?: number;
}

export interface DateWeight {
  date: string;
  weight: number;
}

export type BodyFat = "low" | "normal" | "high";

export interface DateBodyfat {
  date: string;
  bodyfat: BodyFat;
}

export interface LimitedIndividual {
  id?: number;
  name?: string | null;
  number: string | null;
  sex?: string;
}

export interface HerdTrackingEntry {
  herd_id: number;
  herd: string;
  herd_name: string | null;
  date: string | null;
  kind: "BIRTH" | "TRANSFER" | "ATTESTATION" | "CORRECTION";
}

export interface Individual extends LimitedIndividual {
  herd: HerdNameID | string;
  origin_herd?: HerdNameID;
  genebank?: string;
  genebank_id: number;
  certificate: string | null;
  digital_certificate?: string | null;
  birth_date: string | null;
  mother: LimitedIndividual | null;
  father: LimitedIndividual | null;
  color?: string | null;
  color_note: string | null;
  death_date: string | null;
  death_note: string | null;
  selling_date: string | null;
  litter_size: number | null;
  litter_size6w: number | null;
  notes: string | null;
  weights?: Array<DateWeight> | null;
  bodyfat?: Array<DateBodyfat> | null;
  herd_tracking: Array<HerdTrackingEntry> | null;
  herd_active: boolean;
  is_active: boolean;
  is_registered: boolean;
  /** Sell/move permission (huvudmedlem, legacy owner, manager, admin — not caretakers). */
  can_transfer?: boolean;
  has_photo: boolean;
  alive: boolean;
  belly_color: string | null;
  eye_color: string | null;
  claw_color: string | null;
  inbreeding?: string | null; // API returns "%.2f" strings
  MK?: string | null; // API returns "%.2f" strings
  children?: number;
  hair_notes: string;
  breeding: number | null;
  butchered: boolean;
  castration_date: string | null;
  updated_at?: string | null;
}

export interface PedigreeNode {
  id: number | null;
  name: string | null;
  number: string | null;
  sex: string | null;
  /** Synthetic node for a parent that is not registered (Provparning). */
  unregistered?: boolean;
  mother: PedigreeNode | null;
  father: PedigreeNode | null;
}

export type UpdateIndividualPayload = {
  id: number;
  number: string;
  herd: string | HerdNameID;
} & Partial<
  Pick<
    Individual,
    | "name"
    | "sex"
    | "color"
    | "color_note"
    | "eye_color"
    | "claw_color"
    | "belly_color"
    | "hair_notes"
    | "notes"
    | "has_photo"
  >
>;

export interface LimitedHerd {
  id: number;
  genebank: number;
  herd: string;
  herd_name: string | null;
  is_active: boolean | null;
}

export interface Herd extends LimitedHerd {
  has_details: boolean;
  start_date: string | null;
  name: string | null;
  name_privacy?: PrivacyLevel;
  physical_address: string | null;
  physical_address_privacy?: PrivacyLevel;
  location: string | null;
  location_privacy?: PrivacyLevel;
  email: string | null;
  email_privacy?: PrivacyLevel;
  email_verified: boolean | null;
  www: string | null;
  www_privacy?: PrivacyLevel;
  mobile_phone: string | null;
  mobile_phone_privacy?: PrivacyLevel;
  wire_phone: string | null;
  wire_phone_privacy?: PrivacyLevel;
  latitude: string | null;
  longitude: string | null;
  coordinates_privacy?: PrivacyLevel;
  individuals?: Individual[];
}

// Genetics types
export interface PopulationMetrics {
  population_size: number;
  n_active: number;
  n_founders: number;
  founder_equivalents: number;
  mean_inbreeding: number;
  max_inbreeding: number;
  mean_kinship: number;
  effective_population_size: number | null; // realised Ne (individual ΔF); null = not estimable
  delta_f: number | null;
  ne_method?: string;
  ne_se?: number | null;
  ne_n?: number;
  expected_offspring_f?: number | null; // mean K over reference males × females
  mean_equiv_gen: number;
  mean_full_gen: number;
  mean_max_gen: number;
}

export interface FounderStatistics {
  n_founders: number; // founders contributing to the reference population
  n_founders_total?: number; // all founders in the pedigree
  founder_equivalents: number;
  proportional_loss: number;
  top_founders: [string, number][]; // [founder_id, contribution] tuples from API
  population_size: number;
}

export interface GeneticPriority {
  individual_id: string;
  priority: "critical" | "important" | "normal";
  reasons: string[];
  genetic_value_score: number;
  genome_uniqueness: number;
}

export interface BreedingSuggestion {
  sire_id: string;
  dam_id: string;
  expected_f: number;
  delta_gd: number;
  mate_suitability_index: number;
  reasons: string[];
}

export interface BreedingSuggestionsParams {
  genebankId: number;
  maxPairs?: number;
  maxInbreeding?: number;
  maxPerMale?: number;
}

export interface FounderAtRisk {
  founder_id: string;
  n_carriers: number;
  avg_contribution: number;
  allele_retention: number | null;
  carrier_ids: string[];
  risk_level: "lost" | "critical" | "warning" | "monitor" | "ok";
  recoverable_carriers?: string[];
}

export interface TrendDataPoint {
  year: number;
  snapshot_date: string;
  population_size: number;
  active_count: number;
  mean_inbreeding: number;
  mean_kinship: number;
  effective_population_size: number | null; // computed on-the-fly via rolling regression
  founder_equivalents: number;
  data_quality: "high" | "medium" | "low";
}

// Prod vs. demo base queries. Relative paths "/api" and "/api-test" are fixed
// nginx locations. In base dev NEXT_PUBLIC_API_TEST_URL is unset, so demo falls
// back to /api (mirrors lib/api.ts's server-side base-dev fallback).
const prodBaseQuery = fetchBaseQuery({
  baseUrl: "/api",
  credentials: "include", // Include cookies for session management
  timeout: 10000, // 10 second timeout instead of default 60s
});

const demoBaseQuery = fetchBaseQuery({
  baseUrl: API_TEST_URL || "/api-test",
  credentials: "include",
  timeout: 10000,
});

// Route each request to /api-test ONLY when mode=demo AND a client test URL is
// configured; base dev (no test URL) and prod both stay on /api. Keys off the
// same sb_mode signal as the server-side fetchApi() so both paths agree
// (Pitfall 1). This is the official RTK dynamic-baseQuery pattern.
export const modeAwareBaseQuery: BaseQueryFn<
  string | FetchArgs,
  unknown,
  FetchBaseQueryError
> = async (args, api, extraOptions) => {
  const bq =
    readModeCookieClient() === "demo" && API_TEST_URL
      ? demoBaseQuery
      : prodBaseQuery;
  return bq(args, api, extraOptions);
};

const baseQueryWithErrorHandling: BaseQueryFn<
  string | FetchArgs,
  unknown,
  FetchBaseQueryError
> = async (args, api, extraOptions) => {
  const result = await modeAwareBaseQuery(args, api, extraOptions);

  if (result.error) {
    // Check if this is a logout request that returned HTML (which shouldn't happen anymore)
    const isLogoutRequest =
      typeof args === "object" && "url" in args && args.url === "/logout";

    if (isLogoutRequest && result.error.status === "PARSING_ERROR") {
      // Logout should now return JSON, not HTML
      console.error(
        "Logout API returned HTML instead of JSON - this shouldn't happen",
      );
      return result;
    }

    // Handle 401 errors globally — only show session expired modal if user
    // was previously authenticated (avoids modal on initial unauthenticated visit)
    if (result.error.status === 401) {
      const state = api.getState() as { auth: { isAuthenticated: boolean } };
      if (state.auth.isAuthenticated) {
        api.dispatch(sessionExpired());
      }
    }
  }

  return result;
};

export const apiSlice = createApi({
  reducerPath: "api",
  baseQuery: baseQueryWithErrorHandling,
  tagTypes: ["User", "Herd", "Genetics", "Individuals"],
  endpoints: (builder) => ({
    login: builder.mutation<User, { username: string; password: string }>({
      query: (credentials) => ({
        url: "/login",
        method: "POST",
        body: credentials,
      }),
      invalidatesTags: ["User"],
    }),
    googleLogin: builder.mutation<User, { credential: string }>({
      query: (googleCredential) => ({
        url: "/auth/google",
        method: "POST",
        body: googleCredential,
      }),
      invalidatesTags: ["User"],
    }),
    fetchUser: builder.query<User | null, void>({
      query: () => "/user",
      providesTags: ["User"],
      transformResponse: (response: any) => response,
      transformErrorResponse: (response: { status: string | number }) => {
        // If it's a 401, treat it as "no user" rather than an error
        if (response.status === 401 || response.status === "PARSING_ERROR") {
          return null;
        }
        return response;
      },
    }),
    logout: builder.mutation<{ status: string; message: string }, void>({
      query: () => ({
        url: "/logout",
        method: "GET",
      }),
      // Don't invalidate User tag - we handle logout state manually to avoid 401 redirect
      transformResponse: (response: any) => {
        // The backend returns an error object after logout, which is expected
        return response;
      },
    }),
    // Herd data endpoints - using existing API structure
    fetchHerd: builder.query<any, string>({
      query: (herdId) => `/herd/${herdId}`,
      providesTags: ["Herd"],
    }),
    fetchActiveUsers: builder.query<any, void>({
      query: () => "/active_users",
      providesTags: ["Herd"],
    }),
    // updateHerd mutation removed — replaced by Server Action (Story 2.10)
    // Individual detail endpoint [Next.js]
    fetchIndividual: builder.query<Individual, string>({
      query: (individualNumber) =>
        `/individual/${encodeURIComponent(individualNumber)}`,
      providesTags: ["Herd"],
    }),
    // [Next.js] Nested ancestor tree — generations=3 gives self + parents +
    // grandparents (app/blueprints/pedigree.py). Interactive per-selection
    // fetch for the Släktträd tab, sanctioned by ADR-0008.
    getIndividualPedigree: builder.query<PedigreeNode, string>({
      query: (individualNumber) =>
        `/individual/${encodeURIComponent(individualNumber)}/pedigree?generations=3`,
      providesTags: ["Herd"],
    }),
    // [Next.js] Provparning — live offspring-F calculation, a POST that only
    // reads (no cache tags). Interactive per-selection call, sanctioned by
    // ADR-0008; app/blueprints/testbreed_v2.py.
    testbreed: builder.mutation<TestbreedResponse, TestbreedRequest>({
      query: (body) => ({ url: "/v2/testbreed", method: "POST", body }),
    }),
    updateIndividual: builder.mutation<
      { status: string; message: string },
      UpdateIndividualPayload
    >({
      query: (individualData) => ({
        url: "/individual",
        method: "PATCH",
        body: individualData,
      }),
      invalidatesTags: ["Herd"],
    }),
    // Genetics endpoints [Next.js]
    // population-metrics and founder-statistics return raw dicts (no wrapper)
    // genetic-priorities and breeding-suggestions wrap with {status, data}
    fetchPopulationMetrics: builder.query<PopulationMetrics, number>({
      query: (genebankId) => ({
        url: `/${genebankId}/population-metrics/`,
        timeout: 120000,
      }),
      providesTags: ["Genetics"],
    }),
    fetchFounderStatistics: builder.query<FounderStatistics, number>({
      query: (genebankId) => ({
        url: `/${genebankId}/founder-statistics/`,
        timeout: 120000,
      }),
      providesTags: ["Genetics"],
    }),
    fetchGeneticPriorities: builder.query<GeneticPriority[], number>({
      query: (genebankId) => ({
        url: `/${genebankId}/genetic-priorities/`,
        timeout: 120000,
      }),
      transformResponse: (response: {
        status: string;
        data: GeneticPriority[];
      }) => response.data,
      providesTags: ["Genetics"],
    }),
    fetchFoundersAtRisk: builder.query<FounderAtRisk[], number>({
      query: (genebankId) => ({
        url: `/${genebankId}/founders-at-risk/`,
        timeout: 120000,
      }),
      transformResponse: (response: {
        status: string;
        data: FounderAtRisk[];
      }) => response.data,
      providesTags: ["Genetics"],
    }),
    fetchGeneticsTrends: builder.query<TrendDataPoint[], number>({
      query: (genebankId) => ({
        url: `/${genebankId}/genetics-trends/`,
        timeout: 10000,
      }),
      transformResponse: (response: {
        status: string;
        data: TrendDataPoint[];
      }) => response.data,
      providesTags: ["Genetics"],
    }),
    fetchBreedingSuggestions: builder.query<
      BreedingSuggestion[],
      BreedingSuggestionsParams
    >({
      query: ({
        genebankId,
        maxPairs = 20,
        maxInbreeding = 0.0625,
        maxPerMale = 3,
      }) => ({
        url: `/${genebankId}/breeding-suggestions/?max_pairs=${maxPairs}&max_inbreeding=${maxInbreeding}&max_per_male=${maxPerMale}`,
        timeout: 120000,
      }),
      transformResponse: (response: {
        status: string;
        data: BreedingSuggestion[];
      }) => response.data,
      providesTags: ["Genetics"],
    }),
    // [Next.js] Paginated individual list for Rabbit Explorer
    fetchIndividuals: builder.query<
      PaginatedIndividualsResponse,
      FetchIndividualsParams
    >({
      query: (params) => {
        const searchParams = new URLSearchParams();
        if (params.page) searchParams.set("page", String(params.page));
        if (params.per_page)
          searchParams.set("per_page", String(params.per_page));
        if (params.sort) searchParams.set("sort", params.sort);
        if (params.order) searchParams.set("order", params.order);
        if (params.genebank_id != null)
          searchParams.set("genebank_id", String(params.genebank_id));
        if (params.search) searchParams.set("search", params.search);
        if (params.status) searchParams.set("status", params.status);
        if (params.sex) searchParams.set("sex", params.sex);
        if (params.herd_id) searchParams.set("herd_id", params.herd_id);
        if (params.include_historical)
          searchParams.set("include_historical", "true");
        const qs = searchParams.toString();
        return `/individuals${qs ? `?${qs}` : ""}`;
      },
      providesTags: ["Individuals"],
    }),
    // Breeding read-only query (mutations moved to Server Actions — Story 2.10)
    fetchBreedingList: builder.query<any[], string>({
      query: (herdId) => `/breeding/${herdId}`,
      transformResponse: (res: { breedings: any[] }) => res.breedings,
      providesTags: ["Herd"],
    }),
  }),
});

export const {
  useLoginMutation,
  useGoogleLoginMutation,
  useFetchUserQuery,
  useLogoutMutation,
  useFetchActiveUsersQuery,
  useFetchIndividualQuery,
  useGetIndividualPedigreeQuery,
  useUpdateIndividualMutation,
  useTestbreedMutation,
  useFetchPopulationMetricsQuery,
  useFetchFounderStatisticsQuery,
  useFetchFoundersAtRiskQuery,
  useFetchGeneticsTrendsQuery,
  useFetchGeneticPrioritiesQuery,
  useFetchBreedingSuggestionsQuery,
  useFetchIndividualsQuery,
} = apiSlice;
