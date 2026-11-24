import React from "react";

// While `active`, closing or reloading the tab gets the browser's own "Leave site?" prompt (it ignores any
// custom text: preventDefault and returnValue are what ask for it). Removed when `active` ends or the dialog closes.
export function useLeaveWarning(active: boolean) {
  React.useEffect(() => {
    if (!active) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);
}
