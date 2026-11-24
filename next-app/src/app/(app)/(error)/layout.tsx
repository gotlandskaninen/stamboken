import { ReactNode } from "react";
import { TyckTillTab } from "@/components/tyck-till/TyckTillDialog.client";

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      {children}
      <TyckTillTab />
    </div>
  );
}
