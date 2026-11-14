import { permanentRedirect } from "next/navigation";

// A short address that is easy to copy from a printed form; it matches the
// contact address dataskydd@.
export default function DataskyddRedirect() {
  permanentRedirect("/integritetspolicy");
}
