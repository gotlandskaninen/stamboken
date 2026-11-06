import { fetchApi } from "@/lib/api";
import { Masthead } from "@/components/shell/Masthead";
import { ProvparningClient } from "@/components/provparning/ProvparningClient";
import {
  parseProvparningParams,
  pickedFromIndividual,
  serializeProvparningParams,
} from "@/lib/provparning";
import type { Individual, PaginatedIndividualItem } from "@/redux/api/apiSlice";

export const dynamic = "force-dynamic"; // Never statically generate

export const metadata = { title: "Provparning" };

type Resolved = { picked: PaginatedIndividualItem; genebankId: number };

// A shared link may name animals the viewer cannot see or that no longer exist:
// those are silently dropped (the form simply opens with fewer prefilled).
async function resolve(
  number: string,
  sex: "male" | "female",
): Promise<Resolved | null> {
  try {
    const ind = await fetchApi<Individual>(
      `/v2/individual/${encodeURIComponent(number)}`,
    );
    if (!ind || ind.sex !== sex) return null;
    return { picked: pickedFromIndividual(ind), genebankId: ind.genebank_id };
  } catch {
    return null;
  }
}

export default async function ProvparningPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = parseProvparningParams(await searchParams);

  const { genebanks } = await fetchApi<{
    genebanks: { id: number; name: string }[] | null;
  }>("/genebanks");
  const accessible = genebanks ?? [];

  const [female, ...males] = await Promise.all([
    params.hona ? resolve(params.hona, "female") : Promise.resolve(null),
    ...params.hane.map((n) => resolve(n, "male")),
  ]);

  const known = (id: number | null | undefined) =>
    id != null && accessible.some((g) => g.id === id) ? id : null;
  const genebankId =
    known(params.genebank) ??
    known(female?.genebankId) ??
    known(males.find((m) => m)?.genebankId) ??
    accessible[0]?.id ??
    null;

  const inGenebank = (r: Resolved | null): r is Resolved =>
    r !== null && r.genebankId === genebankId;

  const initialFemale = inGenebank(female) ? female.picked : null;
  const initialMales = males.filter(inGenebank).map((m) => m.picked);

  return (
    <>
      <Masthead
        eyebrow="Stamboken"
        title="Provparning"
        meta="Se vilken inavelsgrad en tänkt avkomma skulle få innan du parar."
      />
      <ProvparningClient
        genebanks={accessible}
        requestedQuery={serializeProvparningParams(params)}
        initialGenebankId={genebankId}
        initialFemale={initialFemale}
        initialMales={initialMales}
      />
    </>
  );
}
