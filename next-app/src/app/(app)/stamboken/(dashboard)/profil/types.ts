import type { MembershipStatus } from "@/lib/membershipStatus";

export type Consent = Record<"name" | "phone" | "email" | "address", boolean>;

// Contracts of GET /api/v2/members/me and GET /api/v2/my-membership as the
// unified profil page consumes them. Field names mirror
// app/blueprints/members.py::_me_response and memberships.py::get_my_membership.
export type Me = {
  id: number;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  role: "huvudmedlem" | "familjemedlem" | "skotare";
  membership: {
    id: number;
    member_number: number | null;
    membership_status: MembershipStatus;
    address: string | null;
    postal_code: string | null;
    city: string | null;
    postal_address: string | null;
    joined_date: string | null;
  };
  publication_consent: Consent;
  // false = stored `{}`, i.e. the Koharen question has never been answered,
  // so the first save then submits all four keys.
  consent_answered: boolean;
  main_member_name: string | null;
};

export type MyGrant = {
  id: number;
  herd_id: number;
  herd: string;
  valid_until: string | null;
  revoked_at: string | null;
};

export type MyPerson = {
  id: number;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  role: "huvudmedlem" | "familjemedlem" | "skotare";
  grants: MyGrant[];
};

export type MyHerd = { id: number; herd: string; herd_name: string | null };

export type MyMembership = {
  is_main_member: boolean;
  membership: {
    id: number;
    member_number: number | null;
    membership_status: MembershipStatus;
    persons: MyPerson[];
    herds: MyHerd[];
  };
};

export const ROLE_LABELS: Record<MyPerson["role"], string> = {
  huvudmedlem: "Huvudmedlem",
  familjemedlem: "Familjemedlem",
  skotare: "Skötare",
};
