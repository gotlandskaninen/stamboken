// Shared TypeScript contracts for the v2 Adminpanel.
// Defined ONCE here — every admin page/component imports from this file.

export interface AdminUserListItem {
  id: number;
  username: string | null;
  email: string;
  fullname: string | null;
  role_summary: string;
  validated: boolean;
  v2_prod_access: boolean;
  is_active: boolean;
  last_active: string | null;
  google_linked: boolean;
}

export interface AdminUserDetail extends AdminUserListItem {
  uuid: string;
  _privileges: PrivilegeEntry[];
  profile_picture: string | null;
  google_picture: string | null;
  google_name: string | null;
  google_email: string | null;
  use_google_picture: boolean;
}

export type PrivilegeEntry =
  | { level: "admin" }
  | { level: "matrikel_admin" }
  | { level: "manager" | "viewer"; genebank: number }
  | { level: "owner"; herd: number };

export interface SyncStatus {
  started_at: string | null; // null när demo_sync_status är tom
  finished_at: string | null;
  success: boolean | null;
  detail: string | null;
  rows_synced: number | null;
  stale: boolean;
}

export interface RateLimitStatus {
  enabled: boolean;
  storage: "redis" | "memory";
  storage_healthy: boolean;
  active_counter_keys: number | null;
  registered_limits: { endpoint: string; limit: string }[];
}
