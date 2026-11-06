import { apiSlice } from "./apiSlice";

export const memberApplicationsApi = apiSlice.injectEndpoints({
  endpoints: (build) => ({
    pendingMemberApplicationCount: build.query<{ pending: number }, void>({
      query: () => "/v2/member-applications/count?status=pending",
    }),
  }),
});

export const { usePendingMemberApplicationCountQuery } = memberApplicationsApi;
