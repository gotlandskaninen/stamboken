"use client";
import { createContext, useContext } from "react";

// Matches User.frontend_data() from database.py:1099-1118
export interface UserContext {
  id: number;
  email: string;
  fullname: string | null;
  username: string | null;
  validated: boolean;
  is_admin: boolean;
  is_manager: number[] | null; // genebank IDs the user manages, or null
  is_owner: string[] | null; // herd number STRINGS (e.g. "G1274"), not IDs — or null
  is_matrikel_admin: boolean; // full matrikel CRUD, no studbook rights (member-v2)
  profile_picture: string | null;
  google_picture: string | null;
  google_name: string | null;
  google_email: string | null;
  use_google_picture: boolean;
  v2_prod_access: boolean;
}

const UserCtx = createContext<UserContext | null>(null);

export function UserProvider({
  user,
  children,
}: {
  user: UserContext;
  children: React.ReactNode;
}) {
  return <UserCtx.Provider value={user}>{children}</UserCtx.Provider>;
}

export function useUser() {
  const ctx = useContext(UserCtx);
  if (!ctx) throw new Error("useUser must be used within UserProvider");
  return ctx;
}
