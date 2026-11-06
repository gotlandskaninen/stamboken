// Shared shapes for the matrikel pages. Mirrors the v2 backend serialization
// of GET /api/v2/members (flat membership rows) and GET /api/v2/members/<id>
// (membership detail). Field names must stay in sync with
// app/blueprints/members.py.

export type MembershipListPerson = {
  id: number;
  first_name: string;
  last_name: string;
  role: string;
  end_date: string | null;
};

export type MembershipRow = {
  id: number; // membership id
  member_number: number | null;
  membership_status: string;
  main_first_name: string | null;
  main_last_name: string | null;
  main_email: string | null;
  main_phone: string | null;
  address: string | null;
  postal_code: string | null;
  city: string | null;
  postal_address: string | null;
  persons: MembershipListPerson[];
};

export type Grant = {
  id: number;
  herd_id: number;
  herd: string; // herd code, e.g. "G6"
  valid_until: string | null;
  revoked_at: string | null;
};

export type Person = {
  id: number;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  role: string;
  end_date: string | null;
  user_id: number | null;
  /** Linked account summary (Phase 19 T5a) — the Konto column renders from it. */
  user: { id: number; username: string | null; email: string } | null;
  grants: Grant[];
};

export type MembershipHerd = {
  id: number;
  herd: string;
  herd_name: string | null;
};

export type MembershipDetail = {
  id: number;
  member_number: number | null;
  membership_status: string;
  address: string | null;
  postal_code: string | null;
  city: string | null;
  postal_address: string | null;
  publication_consent: Record<string, boolean>;
  payment_note: string | null;
  joined_date: string | null;
  notes: string | null;
  persons: Person[];
  herds: MembershipHerd[];
};

// Default page size for the matrikel list — the RSC page uses it whenever the
// URL carries no (valid) per_page.
export const MEMBERS_PAGE_SIZE = 25;

export const STATUS_LABELS: Record<string, string> = {
  active: "Aktiv",
  inactive: "Inaktiv",
  pending: "Väntar",
  friexemplar: "Friexemplar",
};

export const ROLE_LABELS: Record<string, string> = {
  huvudmedlem: "Huvudmedlem",
  familjemedlem: "Familjemedlem",
  skotare: "Skötare",
};
