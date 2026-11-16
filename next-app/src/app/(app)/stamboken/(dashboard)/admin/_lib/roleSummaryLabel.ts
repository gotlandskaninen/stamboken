// role_summary kommer rått från backend ("admin", "manager(G,M)", "owner(2
// besättningar)", "ingen roll", "manager(G) + matrikel_admin") — översätt
// rollnamnen till svenska.
export function roleSummaryLabel(s: string): string {
  if (s === "ingen roll") return "Ingen roll";
  return s
    .replace(/^admin/, "Administratör")
    .replace(/^manager/, "Genbanksansvarig ")
    .replace(/^helper/, "Genbankshjälpare ")
    .replace(/^viewer/, "Granskare ")
    .replace(/^owner/, "Besättningsägare ")
    .replace(/matrikel_admin/, "Matrikeladministratör");
}
