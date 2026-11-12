import { permanentRedirect } from "next/navigation";

// The address until November 2026. Nobody becomes a gene bank; a herd joins
// one (docs/ORDLISTA.md), so the page moved and old links land here.
export default function BliGenbankRedirect() {
  permanentRedirect("/bli-genbanksbesattning");
}
