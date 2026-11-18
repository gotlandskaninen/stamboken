"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * A page that marks the user's notices read while it renders runs after the
 * layout has counted them. When there were unread notices, refresh once so the
 * menu's badge shows the new count (revalidatePath is not allowed in a render).
 */
export function RefreshBadge({ unread }: { unread: number }) {
  const router = useRouter();
  useEffect(() => {
    if (unread > 0) router.refresh();
  }, [unread, router]);
  return null;
}
