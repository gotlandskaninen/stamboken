"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { isCurrentPath } from "./navCurrent";

export function NavLink({ href, label }: { href: string; label: string }) {
  const current = isCurrentPath(usePathname(), href);
  return (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      style={{
        fontSize: "13.5px",
        color: current ? "var(--sb-ink)" : "#3D362C",
        textDecoration: "none",
        fontWeight: current ? 600 : 400,
        borderBottom: `2px solid ${current ? "var(--sb-lera)" : "transparent"}`,
        paddingBottom: "2px",
        minHeight: "44px",
        display: "inline-flex",
        alignItems: "center",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </Link>
  );
}
