import type {
  RabbitView,
  ReportView,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

export const rabbit = (
  id: number,
  over: Partial<RabbitView> = {},
): RabbitView => ({
  id,
  number: `G9001-${id}`,
  name: `Kanin${id}`,
  sex: "female",
  color: "viltgrå",
  birth_date: "2022-03-01",
  castrated: false,
  adult: true,
  last_reported: "2025-12-31",
  death_date: null,
  death_day_known: true,
  state: "att_valja",
  later: null,
  kopt: null,
  ...over,
});

export const view = (over: Partial<ReportView> = {}): ReportView => ({
  herd: {
    id: 1,
    herd: "G9001",
    name: "Gårdsnamn",
    genebank_id: 1,
    genebank: "Gotlandskanin",
  },
  year: 2026,
  round: {
    start_date: "2026-12-31",
    deadline: "2099-01-31",
    end_date: "2099-03-01",
    activated: true,
    open: true,
  },
  access: "owner",
  source: "login",
  can_sell: true,
  other_active_herd: false,
  rabbits: [rabbit(1), rabbit(2)],
  litters: [],
  sales: [],
  forslag: [],
  kopanmalningar: [],
  arenden: [],
  herds: ["G9002"],
  report: null,
  draft: null,
  item: null,
  ...over,
});
