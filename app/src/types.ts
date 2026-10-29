// Shapes of the per-chain bundle written by `portolan build` (build/app/<chain>.json).

export type Grade = "A" | "B" | "C" | "D";

/** A resolved field: the value we show plus the claims behind it. */
export interface Resolved<T = unknown> {
  outcome: "resolved" | "contested";
  value: T;
  as_of: string | null;
  grade: Grade;
  claim_ids: string[];
  source_claim_ids: string[];
  range: [number, number] | null;
  basis: string | null;
  review_state: string;
}

export interface Molecule {
  id: string;
  name: string;
  tier: "base" | "intermediate" | "specialty";
  role: "context" | "feedstock" | "core" | "downstream";
  cas: string | null;
  hs6: string[];
  hs6_exact: boolean;
  weight?: number;
  byproduct?: boolean;
  hs6_scope?: string;
  trade_basis?: string;
  cn_hs8?: string;
  note?: string;
}

export interface Route {
  id: string;
  product_id: string;
  inputs: { molecule_id: string; role: string }[];
  route_name: string;
}

export interface Site {
  id: string;
  name: string;
  country: string;
  admin1?: string;
  locality: string;
  address?: string;
  park_name?: string;
  geo_precision: string;
  lat?: number;
  lon?: number;
  location_source?: string;
  unit_ids: string[];
  [k: string]: unknown;
}

export interface Unit {
  id: string;
  site_id: string;
  molecule_id: string;
  route_id: string | null;
  status_unconfirmed?: { last_seen: string; claim_ids: string[] };
  [k: string]: unknown;
}

export interface Company {
  id: string;
  name: string;
  aliases: string[];
  hq_country?: string;
  website?: string;
  type?: string[];
  parents?: string[];
  group?: string;
}

export interface Estimate {
  method: string;
  inputs: string[];
  low?: number;
  high?: number;
  confidence: "low" | "medium" | "high";
}

export interface Claim {
  subject_id: string;
  field: string;
  value: unknown;
  value_norm?: unknown;
  unit_raw?: string;
  capacity_basis?: string;
  as_of: string;
  evidence_ids: string[];
  confidence: Grade;
  review_state: string;
  review_note?: string;
  flags: string[];
  estimate?: Estimate;
}

export interface Evidence {
  id: string;
  url: string;
  publisher?: string;
  published_at?: string;
  retrieved_at?: string;
  source_type: string;
  language?: string;
  quote: string;
  quote_en?: string;
  locator?: string;
  quote_check?: string;
}

export interface ChainEvent {
  id: string;
  date: string;
  type: string;
  subjects: string[];
  summary: string;
  evidence_ids: string[];
}

export interface Bundle {
  chain: { id: string; name: string; version: string; why: string };
  built_on: string;
  licence: string;
  attribution: string;
  display?: { estimates_default: boolean; chain_total: boolean; trade_footnote_codes: string[] };
  trade_codes?: Record<string, { molecules: string[]; broad?: boolean; scope?: string; label?: string }>;
  molecules: Molecule[];
  routes: Route[];
  sites: Site[];
  units: Unit[];
  companies: Company[];
  claims: Record<string, Claim>;
  evidence: Record<string, Evidence>;
  events: ChainEvent[];
  trade: Record<string, Record<string, Record<string, number>>>;
  market: Record<string, Record<string, Resolved<number> | null>>;
  flows: Record<
    string,
    {
      year: number;
      unit: string;
      exporters: Record<
        string,
        {
          total: number;
          partners: Record<string, number>;
          source: string;
          estimate?: { method: string; low: number; high: number; confidence: string; price_usd_per_kg: number };
        }
      >;
    }
  >;
  cn_exports: {
    source: string;
    codes: Record<
      string,
      {
        description: string;
        by_year: Record<string, number>;
        partial_years: Record<string, string>;
        top_destinations: Record<string, Record<string, number>>;
      }
    >;
  };
}
