import { permanentRedirect } from "next/navigation";

// The contact page's former address. It was the menu's Kontakt link and
// is in search results, so it keeps working.
export default function StyrelsenRedirect() {
  permanentRedirect("/kontakt");
}
