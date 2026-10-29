import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection } from "geojson";
import "./style.css";
import type { Bundle, Claim, Company, Evidence, Molecule, Resolved, Site, Unit } from "./types";

// ---------------------------------------------------------------- config

const CHAIN = "isoprenoids";
const MAP_STYLE = { light: "https://tiles.openfreemap.org/styles/positron", dark: "https://tiles.openfreemap.org/styles/dark" };
const OFFLINE = import.meta.env.VITE_OFFLINE === "1";
const REPO = "https://github.com/LorenzoArbolino/portolan";

// ---------------------------------------------------------------- data

async function loadJSON<T>(inlineId: string, url: string): Promise<T> {
  const el = document.getElementById(inlineId);
  if (el?.textContent) return JSON.parse(el.textContent) as T;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

let B: Bundle;
const molById = new Map<string, Molecule>();
const siteById = new Map<string, Site>();
const coById = new Map<string, Company>();

/** A figure as shown: sourced, or an estimate (with its range), and the resolved record behind it. */
interface Fig<T> {
  v: T;
  est: boolean;
  r: Resolved<T>;
  lo?: number;
  hi?: number;
}

interface Row {
  u: Unit;
  s: Site;
  m: Molecule;
  op?: Company;
  cap?: Fig<number>;
  out?: Fig<number>;
  status?: Fig<string>;
  start?: Fig<number>;
}

let rows: Row[] = [];
let tracked: Molecule[] = [];

const state = {
  mol: "",
  q: "",
  site: "",
  est: false,
  feed: false,
  country: "",
  status: "",
  sort: "cap" as "cap" | "plant" | "country" | "operator" | "status",
  all: false,
};

// ---------------------------------------------------------------- helpers

const esc = (s: unknown): string => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const COUNTRY: Record<string, string> = {
  BR: "Brazil", CN: "China", DE: "Germany", IN: "India", MY: "Malaysia", JP: "Japan", CH: "Switzerland",
  US: "United States", FR: "France", ES: "Spain", IT: "Italy", GB: "United Kingdom", ID: "Indonesia",
  KR: "South Korea", SG: "Singapore", NL: "Netherlands", BE: "Belgium", FI: "Finland", SE: "Sweden",
  AT: "Austria", PL: "Poland", MX: "Mexico", PT: "Portugal", TR: "Türkiye", TW: "Taiwan", VN: "Vietnam",
  TH: "Thailand", RU: "Russia", UA: "Ukraine", AR: "Argentina", ZA: "South Africa", EG: "Egypt", IL: "Israel",
  CA: "Canada", AU: "Australia", NZ: "New Zealand", HU: "Hungary", CZ: "Czechia", DK: "Denmark", IE: "Ireland",
  NO: "Norway", GR: "Greece", RO: "Romania", BG: "Bulgaria", HK: "Hong Kong", AE: "UAE", SA: "Saudi Arabia",
  PK: "Pakistan", LK: "Sri Lanka", PH: "Philippines", CL: "Chile", CO: "Colombia", PE: "Peru", MA: "Morocco",
  TN: "Tunisia", SK: "Slovakia", SI: "Slovenia", HR: "Croatia", LT: "Lithuania", LV: "Latvia", EE: "Estonia",
  LU: "Luxembourg", CY: "Cyprus", MT: "Malta", NP: "Nepal", NG: "Nigeria", MM: "Myanmar", BY: "Belarus", KH: "Cambodia", BD: "Bangladesh", UY: "Uruguay", PY: "Paraguay",
}; // prettier-ignore
const cname = (c: string): string => COUNTRY[c] ?? c;

const molName = (id: string): string => {
  const m = molById.get(id);
  if (!m) return id;
  return m.name.replace(/\s*\(.*\)$/, "").replace(/^\w/, (c) => c.toUpperCase());
};

function kt(v: number, perYear = true): string {
  const a = perYear ? "/a" : "";
  if (v >= 1000) {
    const k = v / 1000;
    return `${k >= 10 ? Math.round(k).toLocaleString("en") : k.toFixed(1).replace(/\.0$/, "")} kt${a}`;
  }
  return `${Math.round(v).toLocaleString("en")} t${a}`;
}
const pct = (x: number): string => `${Math.round(x * 100)}%`;
/** "8–13 kt/a", "300–500 t/a": one unit for both ends. */
function ktRange(lo: number, hi: number): string {
  const k = hi >= 1000;
  const f = (v: number) => (k ? (v / 1000 >= 10 ? Math.round(v / 1000).toLocaleString("en") : (v / 1000).toFixed(1).replace(/\.0$/, "")) : Math.round(v).toLocaleString("en"));
  return `${f(lo)}–${f(hi)} ${k ? "kt" : "t"}/a`;
}

const STATUS_LABEL: Record<string, string> = {
  operating: "Running",
  commissioning: "Starting up",
  under_construction: "Building",
  planned: "Planned",
  idle: "Idle",
  closing: "Closing",
  closed: "Closed",
  cancelled: "Cancelled",
  unknown: "Unknown",
};
const STATUS_GROUP: Record<string, string> = {
  operating: "running",
  commissioning: "building",
  under_construction: "building",
  planned: "planned",
  idle: "down",
  closing: "down",
  closed: "down",
  cancelled: "down",
};
const GROUP_LABEL: Record<string, string> = {
  running: "Running",
  building: "Building",
  planned: "Planned",
  down: "Idle or closed",
  unknown: "Unknown",
};

const companyName = (c?: Company): string => {
  if (!c) return "Unknown operator";
  // A long legal name with a short everyday alias ("Huilong"): the alias reads better in a league row.
  const short = c.aliases.filter((a) => /^[A-Za-z][A-Za-z .&-]{4,}$/.test(a)).sort((x, y) => x.length - y.length)[0];
  if (c.name.length > 34 && short) return short;
  const latin = [c.name, ...c.aliases].find((n) => /^[\x00-\x7FÀ-ɏ\s.,&()'-]+$/.test(n));
  const words = (latin ?? c.name).replace(/\s*[(（].*?[)）]/g, "").trim().split(/\s+/);
  while (words.length > 1 && LEGAL.has(words[words.length - 1].toLowerCase().replace(/[.,]/g, ""))) words.pop();
  return words.join(" ").replace(/[,.]+$/, "");
};

/** Legal forms dropped from the end of a display name ("Wanhua Chemical Group Co., Ltd." → "Wanhua Chemical"). */
const LEGAL = new Set(
  "co company ltd limited inc incorporated corp corporation plc llc lp se ag gmbh kg sa spa srl bv nv ab oy oyj sdn bhd pvt pte kk group holdings holding".split(" "),
);

/** Sourced value first; an estimate only fills a gap, and only while estimates are on. */
function fig<T>(obj: Record<string, unknown>, name: string): Fig<T> | undefined {
  const r = obj[name] as Resolved<T> | null | undefined;
  if (r && r.grade !== "D") return { v: r.value, est: false, r };
  const e = obj[`${name}__estimate`] as Resolved<T> | undefined;
  if (!state.est || !e) return undefined;
  const meta = B.claims[e.claim_ids[0]]?.estimate;
  return { v: e.value, est: true, r: e, lo: meta?.low, hi: meta?.high };
}

function buildRows(): void {
  rows = [];
  for (const u of B.units) {
    const s = siteById.get(u.site_id);
    const m = molById.get(u.molecule_id);
    if (!s || !m) continue;
    const opr = (s.operator ?? u.operator) as Resolved<string> | undefined;
    rows.push({
      u,
      s,
      m,
      op: opr ? coById.get(String(opr.value)) : undefined,
      cap: fig<number>(u, "capacity"),
      out: fig<number>(u, "production"),
      status: fig<string>(u, "status"),
      start: fig<number>(u, "start_year"),
    });
  }
  // Molecules worth a tab: at least three plants and two sourced capacity or output figures.
  const by = new Map<string, Row[]>();
  rows.forEach((r) => by.set(r.m.id, [...(by.get(r.m.id) ?? []), r]));
  // By-products (turpentine) are a separate feedstock layer, shown only on request.
  tracked = [...by.entries()]
    .filter(([id, rs]) => {
      const m = molById.get(id)!;
      if (m.role === "context" || (m.byproduct && !state.feed)) return false;
      // Weight-3 molecules always get a tab (an unknown is worth showing); others need some sourced data.
      return (m.weight ?? 1) >= 3 || (rs.length >= 3 && rs.filter((r) => (r.cap && !r.cap.est) || r.out).length >= 2);
    })
    .map(([id]) => molById.get(id)!)
    .sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1) || sourced(rowsFor(b.id)) - sourced(rowsFor(a.id)));
}

const rowsFor = (mol: string): Row[] => rows.filter((r) => r.m.id === mol);
const isTracked = (id: string): boolean => tracked.some((m) => m.id === id);

function matches(r: Row): boolean {
  if (!state.q) return true;
  const c = r.op;
  const hay = [r.s.name, r.s.locality, r.s.admin1, cname(r.s.country), c?.name, ...(c?.aliases ?? []), r.m.name]
    .join(" ")
    .toLowerCase();
  return hay.includes(state.q.toLowerCase());
}

/** Rows in scope for the selected molecule and search (the map, KPIs and league use these). */
const scope = (): Row[] =>
  rows.filter((r) => (state.mol ? r.m.id === state.mol : isTracked(r.m.id)) && matches(r));

/** Scope plus the table filters. */
const filtered = (): Row[] =>
  scope().filter(
    (r) =>
      (!state.country || r.s.country === state.country) &&
      (!state.status || (STATUS_GROUP[r.status?.v ?? ""] ?? "unknown") === state.status),
  );

function total(rs: Row[]): { v: number; lo: number; hi: number; sourced: number } {
  let v = 0, lo = 0, hi = 0, sourced = 0; // prettier-ignore
  for (const r of rs) {
    if (!r.cap) continue;
    v += r.cap.v;
    lo += r.cap.lo ?? r.cap.v;
    hi += r.cap.hi ?? r.cap.v;
    if (!r.cap.est) sourced += r.cap.v;
  }
  return { v, lo, hi, sourced };
}

/** Sourced capacity of plants that exist (not planned, being built, cancelled or closed): shares, totals and
 * leagues never rest on estimates. */
const NOT_YET_OR_GONE = new Set(["planned", "under_construction", "cancelled", "closed"]);
/** A capacity quoted per product without saying which (e.g. Chinese vitamin figures): shown, never added up. */
const basisUnstated = (f?: Fig<number>): boolean =>
  !!f && f.r.claim_ids.some((i) => B.claims[i]?.flags?.includes("product basis not stated"));
const counts = (r: Row): boolean => !!r.cap && !r.cap.est && !NOT_YET_OR_GONE.has(r.status?.v ?? "") && !basisUnstated(r.cap);
const sourced = (rs: Row[]): number => rs.reduce((a, r) => a + (counts(r) ? r.cap!.v : 0), 0);
const withSourcedCap = (rs: Row[]): Row[] => rs.filter(counts);

/** Shares of sourced capacity, grouped by `key`. */
function shares(rs: Row[], key: (r: Row) => string): [string, number, Row[]][] {
  const t = sourced(rs) || 1;
  const g = new Map<string, Row[]>();
  withSourcedCap(rs).forEach((r) => g.set(key(r), [...(g.get(key(r)) ?? []), r]));
  return [...g.entries()]
    .map(([k, rr]) => [k, sourced(rr) / t, rr] as [string, number, Row[]])
    .sort((a, b) => b[1] - a[1]);
}

/** Shares are shown only when most existing plants have a published capacity; otherwise a "share" would mostly
 * measure which companies publish. */
const FAIR_COVERAGE = 2 / 3;
function coverage(rs: Row[]): { with: number; of: number; fair: boolean } {
  const live = rs.filter((r) => !NOT_YET_OR_GONE.has(r.status?.v ?? ""));
  const w = live.filter(counts).length;
  return { with: w, of: live.length, fair: live.length > 0 && w / live.length >= FAIR_COVERAGE };
}

/** The group a plant's operator belongs to (parent roll-up), and how to name it. */
function groupOf(c?: Company): Company | undefined {
  return c?.group ? coById.get(c.group) ?? c : c;
}
function groupName(r: Row): string {
  const g = groupOf(r.op);
  if (!g) return "Unknown operator";
  const ps = (g.parents ?? []).map((p) => companyName(coById.get(p)));
  return g.parents && g.parents.length > 1 ? `${companyName(g)} (JV: ${ps.join(", ")})` : companyName(g);
}

// ---------------------------------------------------------------- URL state

function readURL(): void {
  const p = new URLSearchParams(location.search);
  state.mol = p.get("mol") ?? "";
  state.site = p.get("plant") ?? p.get("site") ?? "";
  state.feed = p.get("feed") === "1";
}

/** Estimates: the bundle says the default (off: sourced only); `?est=1` / `?est=0` overrides. */
function readEst(): void {
  const e = new URLSearchParams(location.search).get("est");
  state.est = e ? e === "1" : (B.display?.estimates_default ?? false);
}

function writeURL(): void {
  const p = new URLSearchParams();
  if (state.mol) p.set("mol", state.mol);
  if (state.site) p.set("plant", state.site);
  if (state.est !== (B.display?.estimates_default ?? false)) p.set("est", state.est ? "1" : "0");
  if (state.feed) p.set("feed", "1");
  const qs = p.toString();
  try {
    history.replaceState(null, "", (qs ? `?${qs}` : location.pathname) + location.hash);
  } catch {
    /* sandboxed frames may refuse */
  }
}

// ---------------------------------------------------------------- chips and source popovers

type Payload =
  | { kind: "fig"; title: string; f: Fig<unknown>; label: string }
  | { kind: "html"; title: string; html: string };
const payloads: Payload[] = [];

function chip(label: string, p: Payload, cls = ""): string {
  payloads.push(p);
  return `<button type="button" class="chip ${cls}" data-chip="${payloads.length - 1}">${esc(label)}</button>`;
}

function figChip<T>(f: Fig<T> | undefined, label: (v: T) => string, title: string, cls = ""): string {
  if (!f) return `<span class="nil">·</span>`;
  const text = f.est && f.lo != null && f.hi != null && f.lo !== f.hi ? ktRange(f.lo, f.hi) : label(f.v);
  return chip(f.est ? `~${text}` : text, { kind: "fig", title, f: f as Fig<unknown>, label: text },
    `${cls} ${f.est ? "est" : `g${f.r.grade}`}`); // prettier-ignore
}

const capChip = (r: Row): string =>
  figChip(r.cap, (v) => kt(v) + (basisUnstated(r.cap) ? " (basis?)" : ""), `Capacity · ${molName(r.m.id)} · ${r.s.locality}`, "num");
function statusChip(r: Row): string {
  const seen = r.u.status_unconfirmed;
  if (!r.status && seen)
    return chip(`Unconfirmed · seen ${seen.last_seen.slice(0, 4)}`, {
      kind: "html",
      title: `Status · ${molName(r.m.id)} · ${r.s.locality}`,
      html: `<p class="sum"><b>Status unconfirmed</b> · last seen ${esc(seen.last_seen)}</p>
        <p class="muted">No source states whether this unit runs today. This is the latest source that mentions it.
        If you know, <a href="${esc(correctionURL(r.s))}" target="_blank" rel="noopener">tell us</a>.</p>
        ${seen.claim_ids.map(claimHTML).join("")}`,
    }, "st st-unknown"); // prettier-ignore
  // A status more than two years old shows its year, so "Idle" from 2020 doesn't read as today.
  const yr = (r.status?.r.as_of ?? "").slice(0, 4);
  const old = !!yr && Number(B.built_on.slice(0, 4)) - Number(yr) >= 2;
  return figChip(r.status, (v) => (STATUS_LABEL[v] ?? v) + (old ? ` · ${yr}` : ""), `Status · ${molName(r.m.id)} · ${r.s.locality}`,
    `st st-${STATUS_GROUP[r.status?.v ?? ""] ?? "unknown"}`); // prettier-ignore
}

const BACKTEST = `${REPO}/blob/main/eval/estimates.md`;
const METHOD: Record<string, string> = {
  capacity_from_output:
    "The plant's own reported output, read as a capacity range: from the output itself (full utilisation) to output at 60% utilisation.",
  capacity_from_world_residual:
    "Published world capacity (grade A/B, under five years old) minus every plant we can source, split evenly across the plants with no figure and capped at the largest sourced plant. Used only for molecules where it passed the backtest.",
  capacity_from_peers:
    "Lower quartile of the sourced capacities for the same molecule. Used only for molecules where it passed the backtest.",
};

function claimValue(c: Claim): string {
  if ((c.field === "capacity" || c.field === "world_capacity") && typeof c.value_norm === "number") {
    const raw = c.unit_raw && c.unit_raw !== "t/a" ? `${c.value} ${c.unit_raw} → ` : "";
    return `${raw}${kt(c.value_norm, c.capacity_basis !== "production")}${c.capacity_basis === "production" ? " made" : ""}`;
  }
  if (c.field === "operator" || c.field === "parent") return companyName(coById.get(String(c.value_norm ?? c.value)));
  if (c.field === "status") return STATUS_LABEL[String(c.value_norm ?? c.value)] ?? String(c.value);
  return `${c.value}${c.unit_raw ? ` ${c.unit_raw}` : ""}`;
}

function evidenceHTML(e: Evidence): string {
  const meta = [e.publisher, e.published_at, e.source_type.replace(/_/g, " "), e.locator]
    .filter(Boolean)
    .map(esc)
    .join(" · ");
  const ok = e.quote_check === "pass";
  const where = /\.(zip|csv)$/i.test(e.url) ? "row found in the dataset" : "quote found on the page";
  const lang = e.language && e.language !== "en" ? ` lang="${esc(e.language)}"` : "";
  return `<div class="ev"><blockquote${lang}>${esc(e.quote)}</blockquote>
    ${e.quote_en && e.quote_en !== e.quote ? `<p class="en">${esc(e.quote_en)}</p>` : ""}
    <p class="src">${meta}</p>
    <p class="links"><span class="${ok ? "ok" : "warn"}">${ok ? where : `quote ${esc(e.quote_check ?? "unchecked")}`}</span>
      · <a href="${esc(e.url)}" target="_blank" rel="noopener">Source ↗</a>
      · <a href="https://web.archive.org/web/${esc(e.url)}" target="_blank" rel="noopener">Archive ↗</a></p></div>`;
}

/** Product-basis conversions and caveats, in words. */
function basisNote(c: Claim): string {
  const f = (c.flags ?? []).find((x) => x.startsWith("product basis"));
  if (!f) return "";
  return f === "product basis not stated"
    ? `<p class="muted">The source doesn't say whether this is pure acetate or a formulation (50% powder, 500,000 IU/g), so it is shown but not added into totals or shares.</p>`
    : `<p class="muted">Converted: ${esc(f.replace("product basis: ", ""))}.</p>`;
}

function claimHTML(id: string): string {
  const c = B.claims[id];
  if (!c) return "";
  const ev = c.evidence_ids.map((e) => B.evidence[e]).filter(Boolean);
  return `<article class="claim"><p class="cv"><b>${esc(claimValue(c))}</b>
    <span>${esc(c.field.replace(/_/g, " "))} · ${esc(c.as_of)} · grade ${c.confidence}</span></p>
    ${basisNote(c)}${ev.map(evidenceHTML).join("")}</article>`;
}

const pop = document.getElementById("pop") as HTMLElement;
let anchor: HTMLElement | null = null;

function openPop(btn: HTMLElement): void {
  const p = payloads[Number(btn.dataset.chip)];
  if (!p) return;
  let body = "";
  if (p.kind === "html") body = p.html;
  else if (p.f.est) {
    const c = B.claims[p.f.r.claim_ids[0]];
    const e = c?.estimate;
    const range = e?.low != null && e?.high != null ? ` · range ${kt(e.low)} – ${kt(e.high)}` : "";
    body = `<p class="sum"><span class="badge est">Estimate</span> <b>${esc(p.label)}</b>${esc(range)} ·
      confidence ${esc(e?.confidence ?? "low")}</p>
      <p>${esc(METHOD[e?.method ?? ""] ?? e?.method ?? "")} <a href="${BACKTEST}" target="_blank" rel="noopener">How we test estimates</a></p>
      <h4>Built from</h4>${(e?.inputs ?? []).slice(0, 6).map(claimHTML).join("")}
      ${(e?.inputs.length ?? 0) > 6 ? `<p class="muted">…and ${e!.inputs.length - 6} more sourced figures.</p>` : ""}`;
  } else {
    const others = p.f.r.source_claim_ids.filter((i) => !p.f.r.claim_ids.includes(i) && B.claims[i]?.confidence !== "D");
    body = `<p class="sum"><b>${esc(p.label)}</b>${p.f.r.basis ? ` · ${esc(p.f.r.basis)}` : ""} · as of ${esc(p.f.r.as_of)}
      · grade ${p.f.r.grade}${p.f.r.outcome === "contested" ? ` · <span class="warn">sources disagree</span>` : ""}</p>
      ${p.f.r.claim_ids.map(claimHTML).join("")}
      ${others.length ? `<h4>Other sources</h4>${others.slice(0, 4).map(claimHTML).join("")}` : ""}`;
  }
  pop.innerHTML = `<header><h3>${esc(p.title)}</h3><button type="button" class="x" aria-label="Close">×</button></header>
    <div class="pop-body">${body}</div>`;
  pop.hidden = false;
  anchor = btn;
  placePop();
  (pop.querySelector(".x") as HTMLElement).focus({ preventScroll: true });
}

function placePop(): void {
  if (pop.hidden || !anchor) return;
  if (window.innerWidth < 700) {
    pop.classList.add("docked");
    pop.style.left = pop.style.top = "";
    return;
  }
  pop.classList.remove("docked");
  const r = anchor.getBoundingClientRect();
  const left = Math.min(Math.max(12, r.left), window.innerWidth - pop.offsetWidth - 12);
  let top = r.bottom + 6;
  if (top + pop.offsetHeight > window.innerHeight - 12) top = Math.max(12, r.top - pop.offsetHeight - 6);
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
}

function closePop(): void {
  pop.hidden = true;
  anchor?.focus({ preventScroll: true });
  anchor = null;
}

document.addEventListener("click", (ev) => {
  const t = ev.target as HTMLElement;
  const btn = t.closest<HTMLElement>("[data-chip]");
  if (btn) {
    ev.stopPropagation();
    if (anchor === btn) closePop();
    else openPop(btn);
    return;
  }
  if (t.closest(".x") && pop.contains(t)) return closePop();
  if (!pop.hidden && !pop.contains(t)) closePop();
  const go = t.closest<HTMLElement>("[data-site]");
  if (go) {
    ev.preventDefault();
    selectSite(go.dataset.site!, true);
    return;
  }
  const mol = t.closest<HTMLElement>("[data-mol]");
  if (mol) {
    ev.preventDefault();
    setMol(mol.dataset.mol!);
    return;
  }
  const who = t.closest<HTMLElement>("[data-q]");
  if (who) {
    ev.preventDefault();
    (document.getElementById("q") as HTMLInputElement).value = who.dataset.q!;
    state.q = who.dataset.q!;
    renderAll();
    document.getElementById("plants")?.scrollIntoView({ behavior: "smooth" });
  }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape") return;
  if (!pop.hidden) closePop();
  else if (state.site) selectSite("", false);
});
window.addEventListener("resize", () => placePop());
window.addEventListener("scroll", () => placePop(), { passive: true });

// ---------------------------------------------------------------- map

let map: maplibregl.Map;
const markers = new Map<string, maplibregl.Marker>();

const PALETTES = {
  light: { land: "#f7f8f8", water: "#d3dfe7", line: "#c4ced5", label: "#5e707c" },
  dark: { land: "#132430", water: "#09121a", line: "#2b4455", label: "#8fa6b4" },
};
const palette = () => PALETTES[isDark() ? "dark" : "light"];

// ---------------------------------------------------------------- theme (light default; follows the system
// setting until the viewer picks one, which is remembered in this browser)

function isDark(): boolean {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}

const SUN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
const MOON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`;

function syncTheme(): void {
  const dark = isDark();
  document.documentElement.dataset.dark = dark ? "1" : "0";
  const btn = document.getElementById("theme");
  if (btn) {
    btn.innerHTML = dark ? SUN : MOON;
    btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0b141b" : "#f3f5f6");
}

async function setTheme(t: "light" | "dark"): Promise<void> {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem("portolan-theme", t);
  } catch {
    /* storage blocked: the choice lasts for this visit */
  }
  syncTheme();
  await restyleMap();
}

async function restyleMap(): Promise<void> {
  if (map) map.setStyle(OFFLINE ? offlineStyle(await basemap()) : MAP_STYLE[isDark() ? "dark" : "light"]);
}

try {
  const saved = localStorage.getItem("portolan-theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
} catch {
  /* no storage */
}
syncTheme();
const basemap = () =>
  loadJSON<{ land: FeatureCollection; borders: FeatureCollection }>("basemap-data", "./basemap.json");

function offlineStyle(base: { land: FeatureCollection; borders: FeatureCollection }) {
  return {
    version: 8 as const,
    sources: {
      land: { type: "geojson" as const, data: base.land },
      borders: { type: "geojson" as const, data: base.borders, attribution: "Natural Earth" },
    },
    layers: [
      { id: "water", type: "background" as const, paint: { "background-color": palette().water } },
      { id: "land", type: "fill" as const, source: "land", paint: { "fill-color": palette().land } },
      { id: "borders", type: "line" as const, source: "borders", paint: { "line-color": palette().line, "line-width": 0.7 } },
    ],
  };
}

/** Recolour the basemap to the theme: quiet land, a clear sea, muted labels, so the plants carry the colour. */
function tintBasemap(): void {
  const PALETTE = palette();
  for (const l of map.getStyle().layers ?? []) {
    try {
      if (l.type === "background") map.setPaintProperty(l.id, "background-color", PALETTE.land);
      else if (l.id === "water" || l.id.startsWith("water")) {
        if (l.type === "fill") map.setPaintProperty(l.id, "fill-color", PALETTE.water);
      } else if (l.type === "fill" && /landuse|landcover|park|building/.test(l.id)) {
        map.setPaintProperty(l.id, "fill-opacity", 0.25);
      } else if (l.type === "line" && /boundary|admin/.test(l.id)) map.setPaintProperty(l.id, "line-color", PALETTE.line);
      else if (l.type === "symbol") map.setPaintProperty(l.id, "text-color", PALETTE.label);
    } catch {
      /* layer without that property */
    }
  }
}

const STATUS_COLOR: Record<string, string> = {
  running: "var(--st-running)",
  building: "var(--st-building)",
  planned: "var(--st-planned)",
  down: "var(--st-down)",
  unknown: "var(--st-unknown)",
};

function siteGroup(rs: Row[]): string {
  const g = rs.map((r) => STATUS_GROUP[r.status?.v ?? ""] ?? "unknown");
  return ["running", "building", "planned", "down"].find((x) => g.includes(x)) ?? "unknown";
}

/** Capacity behind a marker: the molecule in view, or (All view) the plant's largest single molecule, never a sum. */
function markerCap(rs: Row[]): { v: number; sourced: number } {
  if (state.mol) return total(rs);
  const big = rs.filter((r) => r.cap).sort((a, b) => b.cap!.v - a.cap!.v)[0];
  return big ? { v: big.cap!.v, sourced: big.cap!.est ? 0 : big.cap!.v } : { v: 0, sourced: 0 };
}

function markerSVG(rs: Row[]): { svg: string; size: number } {
  const t = markerCap(rs);
  const g = siteGroup(rs);
  // Area ∝ capacity of the molecule in view. Unknown capacity: a fixed hollow ring, never a sized bubble.
  const known = t.v > 0;
  const r = known ? Math.min(28, 4 + 18 * Math.sqrt(t.v / 50000)) : 6;
  const size = Math.ceil(2 * (r + 3));
  const c = size / 2;
  const col = STATUS_COLOR[g];
  const est = known && t.sourced < t.v * 0.5;
  const body = !known
    ? `<circle cx="${c}" cy="${c}" r="${r}" fill="var(--bg)" fill-opacity=".6" stroke="${col}" stroke-width="2"/>`
    : g === "planned"
      ? `<circle cx="${c}" cy="${c}" r="${r}" fill="${col}" fill-opacity=".18" stroke="${col}" stroke-width="1.6" stroke-dasharray="3 2"/>`
      : g === "building"
        ? `<circle cx="${c}" cy="${c}" r="${r}" fill="${col}" fill-opacity=".25" stroke="${col}" stroke-width="1.6"/>
           <path d="M${c} ${c - r} A${r} ${r} 0 0 0 ${c} ${c + r} Z" fill="${col}"/>`
        : `<circle cx="${c}" cy="${c}" r="${r}" fill="${col}" fill-opacity="${est ? 0.45 : 0.85}"
             stroke="${est ? col : "var(--bg)"}" stroke-width="${est ? 1.2 : 1}" ${est ? 'stroke-dasharray="2 2"' : ""}/>`;
  return { svg: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">${body}</svg>`, size };
}

function drawMarkers(): void {
  markers.forEach((m) => m.remove());
  markers.clear();
  const bySite = new Map<string, Row[]>();
  filtered().forEach((r) => bySite.set(r.s.id, [...(bySite.get(r.s.id) ?? []), r]));
  const placed = [...bySite.entries()].filter(([id]) => siteById.get(id)?.lat != null);
  placed.sort((a, b) => markerCap(b[1]).v - markerCap(a[1]).v);
  for (const [id, rs] of placed) {
    const s = siteById.get(id)!;
    const el = document.createElement("button");
    el.type = "button";
    el.className = "mk" + (id === state.site ? " on" : "");
    el.innerHTML = markerSVG(rs).svg;
    const caps = rs.filter((r) => r.cap).map((r) => `${molName(r.m.id)} ${r.cap!.est ? "~" : ""}${kt(r.cap!.v)}`);
    el.setAttribute("aria-label", `${s.name}: ${GROUP_LABEL[siteGroup(rs)]}${caps.length ? `, ${caps.join(", ")}` : ""}`);
    el.title = `${companyName(rs[0].op)} · ${s.locality}${caps.length ? ` · ${caps.join(" · ")}` : " · capacity not public"}`;
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      selectSite(id, false);
    });
    markers.set(id, new maplibregl.Marker({ element: el }).setLngLat([s.lon!, s.lat!]).addTo(map));
  }
  renderLegend();
}

function renderLegend(): void {
  const groups = ["running", "building", "planned", "down", "unknown"];
  const notes = [...new Set(scope().map((r) => r.m))].filter((m) => m.note && isTracked(m.id));
  const legend = document.getElementById("legend") as HTMLElement;
  legend.innerHTML = `<details ${window.innerWidth >= 700 ? "open" : ""}><summary>Key</summary>
    <ul>${groups
      .map((g) => `<li><span class="dot" style="--c:${STATUS_COLOR[g]}"></span>${GROUP_LABEL[g]}</li>`)
      .join("")}</ul>
    <p>Filled bubble: area = sourced capacity${state.mol ? "" : " of the plant's largest molecule"}. Hollow ring: capacity not public.${state.est ? " Dashed: mostly estimated." : ""}</p>
    ${notes.map((m) => `<p class="note"><b>${esc(molName(m.id))}:</b> ${esc(m.note)}</p>`).join("")}
    <label class="tog"><input type="checkbox" id="est" ${state.est ? "checked" : ""}/> Include estimates</label>
    ${B.molecules.some((m) => m.byproduct) ? `<label class="tog"><input type="checkbox" id="feed" ${state.feed ? "checked" : ""}/> Pine feedstock (turpentine)</label>` : ""}
  </details>`;
  legend.querySelector<HTMLInputElement>("#feed")?.addEventListener("change", (ev) => {
    state.feed = (ev.target as HTMLInputElement).checked;
    if (!state.feed && molById.get(state.mol)?.byproduct) state.mol = "";
    writeURL();
    buildRows();
    renderAll();
  });
  (legend.querySelector("#est") as HTMLInputElement).addEventListener("change", (ev) => {
    state.est = (ev.target as HTMLInputElement).checked;
    writeURL();
    buildRows();
    renderAll();
  });
}

function fitToScope(): void {
  const pts = filtered().map((r) => r.s).filter((s) => s.lat != null);
  if (!pts.length || !map) return;
  const b = new maplibregl.LngLatBounds();
  pts.forEach((s) => b.extend([s.lon!, s.lat!]));
  const narrow = window.innerWidth < 700;
  map.fitBounds(b, { padding: narrow ? 36 : { top: 60, bottom: 50, left: 260, right: 60 }, maxZoom: 5, duration: 600 });
}

// ---------------------------------------------------------------- detail sheet

const sheet = document.getElementById("sheet") as HTMLElement;

function selectSite(id: string, fly: boolean): void {
  state.site = id;
  writeURL();
  markers.forEach((m, sid) => m.getElement().classList.toggle("on", sid === id));
  if (!id) {
    sheet.hidden = true;
    return;
  }
  const s = siteById.get(id);
  if (!s) return;
  renderSheet(s);
  if (fly) document.getElementById("map")?.scrollIntoView({ behavior: "smooth" });
  if (s.lat != null && map) {
    const phone = window.innerWidth < 700;
    map.easeTo({
      center: [s.lon!, s.lat!],
      zoom: Math.max(map.getZoom(), 4),
      padding: { top: 0, left: 0, bottom: phone ? sheet.offsetHeight : 0, right: phone ? 0 : sheet.offsetWidth + 24 },
      duration: fly ? 800 : 400,
    });
  }
}

function locationNote(s: Site): string {
  const ll = s.lat_lon as Resolved<string> | undefined;
  if (ll && ll.grade !== "D")
    return chip("Coordinates from a document", { kind: "fig", title: `Location · ${s.name}`, f: { v: ll.value, est: false, r: ll }, label: String(ll.value) }, "plain"); // prettier-ignore
  if (!s.location_source) return "";
  return chip("Approximate", {
    kind: "html",
    title: `Location · ${s.name}`,
    html: `<p>Plotted near ${esc(s.locality)}; the exact plot isn't published. Good enough for a regional view,
      not for routing a truck.</p><p class="links"><a href="${esc(s.location_source)}" target="_blank" rel="noopener">Reference ↗</a></p>`,
  }, "plain"); // prettier-ignore
}

function renderSheet(s: Site): void {
  const rs = rows.filter((r) => r.s.id === s.id).sort((a, b) => (b.cap?.v ?? 0) - (a.cap?.v ?? 0));
  const op = rs[0]?.op;
  const ids = new Set(rs.map((r) => r.u.id));
  const evs = B.events.filter((e) => e.subjects.some((x) => ids.has(x) || x === s.id));
  const place = [s.locality !== cname(s.country) ? s.locality : "", s.admin1, cname(s.country)].filter(Boolean).map(esc).join(", ");
  sheet.innerHTML = `<header><div><p class="eyebrow">${esc(place)}</p><h3>${esc(siteTitle(s))}</h3>
      <p class="op">${op ? `<a href="#plants" data-q="${esc(companyName(op))}">${esc(companyName(op))}</a>${groupOf(op) !== op ? ` <span class="muted">· ${esc(groupName(rs[0]))} group</span>` : ""}` : "Operator unknown"}
        ${locationNote(s)}</p></div>
      <button type="button" class="x" id="sheet-x" aria-label="Close">×</button></header>
    <table class="mini"><thead><tr><th>Molecule</th><th class="n">Capacity</th><th>Status</th><th class="n">Since</th></tr></thead>
    <tbody>${rs
      .map(
        (r) => `<tr><td><a href="#" data-mol="${esc(r.m.id)}">${esc(molName(r.m.id))}</a></td><td class="n">${capChip(r)}</td>
        <td>${statusChip(r)}</td><td class="n">${figChip(r.start, String, `Start · ${molName(r.m.id)} · ${s.locality}`, "num")}</td></tr>`,
      )
      .join("")}</tbody></table>
    ${rs.some((r) => r.out) ? `<p class="small">Reported output: ${rs.filter((r) => r.out).map((r) => `${esc(molName(r.m.id))} ${figChip(r.out, (v) => kt(v, false), `Output · ${molName(r.m.id)} · ${s.locality}`, "num")}`).join(" · ")} in ${esc((rs.find((r) => r.out)!.out!.r.as_of ?? "").slice(0, 4))}</p>` : ""}
    ${evs.length ? `<h4>News</h4><ul class="elist">${evs.map((e) => `<li><time>${esc(e.date)}</time> ${esc(e.summary)} ${srcChip(e.evidence_ids, e.type, e.date)}</li>`).join("")}</ul>` : ""}
    <p class="fix">Is this right? <a href="${esc(correctionURL(s))}" target="_blank" rel="noopener">Correct it on GitHub ↗</a>
      or <a href="${esc(correctionMail(s))}">email us</a>, with a public source.</p>`;
  sheet.hidden = false;
  sheet.scrollTop = 0;
  (sheet.querySelector("#sheet-x") as HTMLElement).addEventListener("click", () => selectSite("", false));
}

/** A site's display name: without notes that belong to one product ("(citral plant)") or to our gaps. */
const siteTitle = (s: Site): string =>
  s.name.replace(/\s*\(plant location not public\)/, "").replace(/\s*\([^)]*\bplant\)$/i, "");

/** A GitHub issue (form `correction.yml`) prefilled with the plant, so a correction takes a minute on a phone. */
function correctionURL(s: Site): string {
  const p = new URLSearchParams({ template: "correction.yml", title: `Correction: ${s.name}`, site: s.id });
  return `${REPO}/issues/new?${p.toString()}`;
}

/** Corrections by email, for readers without a GitHub account. Assembled at run time
 * so the address isn't sitting in the page source for scrapers. */
const CONTACT = ["arbolino.lorenzo", "gmail.com"];
function correctionMail(s: Site): string {
  const subject = `Portolan correction: ${s.name} (${s.id})`;
  const body = `Plant: ${s.name} (${s.id})\nWhat is wrong or missing:\nCorrect value:\nPublic source (link):\n`;
  return `mailto:${CONTACT.join("@")}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

const srcChip = (evIds: string[], type: string, date: string): string =>
  chip("src", {
    kind: "html",
    title: `${type.replace(/_/g, " ")} · ${date}`,
    html: evIds.map((x) => (B.evidence[x] ? evidenceHTML(B.evidence[x]) : "")).join(""),
  }, "plain mini-src"); // prettier-ignore

// ---------------------------------------------------------------- sections

function renderTabs(): void {
  const tabs = document.getElementById("tabs") as HTMLElement;
  // Never a chain-wide tonnage: the All tab counts plants; each molecule tab shows its own sourced total.
  const plantsAll = new Set(rows.filter((r) => isTracked(r.m.id)).map((r) => r.s.id)).size;
  tabs.innerHTML =
    `<button type="button" class="tab ${state.mol ? "" : "on"}" data-mol=""><span>All</span><small>${plantsAll} plants</small></button>` +
    tracked
      .map((m) => {
        const v = sourced(rowsFor(m.id));
        return `<button type="button" class="tab ${state.mol === m.id ? "on" : ""}" data-mol="${esc(m.id)}">
          <span>${esc(molName(m.id))}</span><small>${v ? `${esc(kt(v))} sourced` : `${new Set(rowsFor(m.id).map((r) => r.s.id)).size} plants`}</small></button>`;
      })
      .join("");
}

function setMol(id: string): void {
  state.mol = id;
  state.country = state.status = "";
  state.all = false;
  writeURL();
  renderAll();
  fitToScope();
  document.getElementById("top")?.scrollIntoView({ behavior: "smooth" });
}

function renderKPIs(): void {
  const rs = scope();
  const plants = new Set(rs.map((r) => r.s.id)).size;
  const countries = new Set(rs.map((r) => r.s.country)).size;
  const tile = (label: string, big: string, small: string) =>
    `<div class="tile"><p class="k">${label}</p><p class="v">${big}</p><p class="s">${small}</p></div>`;
  const el = document.getElementById("kpis") as HTMLElement;
  if (!state.mol) {
    const groups = new Set(rs.map((r) => groupName(r)).filter((g) => g !== "Unknown operator")).size;
    el.innerHTML = `<div class="kpi-row">
      ${tile("Plants", `${plants}`, `in ${countries} countr${countries === 1 ? "y" : "ies"}`)}
      ${tile("Producer groups", `${groups}`, "parents rolled up")}
      ${tile("Molecules", `${tracked.length}`, "each with its own total below")}
    </div>`;
    return;
  }
  const m = molById.get(state.mol)!;
  const v = sourced(rs);
  const units = rs.length;
  const withCap = withSourcedCap(rs).length;
  const est = state.est ? rs.reduce((a, r) => a + (r.cap?.est ? r.cap.v : 0), 0) : 0;
  const cos = shares(rs, groupName);
  const top3 = cos.slice(0, 3).reduce((a, x) => a + x[1], 0);
  const hubs = shares(rs, (r) => r.s.country);
  const cov = coverage(rs);
  const world = B.market[state.mol]?.world_capacity as Resolved<number> | null | undefined;
  const c = cnFor(m);
  const shared = m.cn_hs8 ? B.trade_codes?.[`CN ${m.cn_hs8}`]?.label : undefined;
  el.innerHTML = `<div class="kpi-row">
    ${tile("Sourced capacity", v ? esc(kt(v)) : "—", `${withCap} of ${units} plants with a sourced capacity${est ? ` · ~${esc(kt(est))} more estimated` : ""}`)}
    ${tile("Plants", `${plants}`, `in ${countries} countr${countries === 1 ? "y" : "ies"}`)}
    ${cov.fair && cos.length ? tile("Top 3 groups", pct(top3), `of sourced capacity: ${esc(cos.slice(0, 3).map((x) => x[0]).join(", "))}`) : tile("Coverage", `${cov.with} of ${cov.of}`, "existing plants with a published capacity; too few for market shares")}
    ${cov.fair && hubs.length ? tile("Hub", esc(cname(hubs[0][0])), `${pct(hubs[0][1])} of sourced capacity`) : ""}
    ${c ? tile(shared ? `China exports · ${esc(shared)}` : "China exports", esc(kt(c.v, false)), `${c.last} · ${c.x.toFixed(1)}× ${c.first}`) : ""}
    ${world ? tile("World, per the trade", esc(kt(world.value)), `published figure · ${chip("src", { kind: "fig", title: `World capacity · ${molName(state.mol)}`, f: { v: world.value, est: false, r: world }, label: kt(world.value) }, "plain mini-src")}`) : ""}
  </div>
  ${m.note ? `<p class="mnote">${esc(m.note)}</p>` : ""}`;
}

function renderLeague(): void {
  const dek = document.getElementById("producers-dek") as HTMLElement;
  const box = document.getElementById("league") as HTMLElement;
  if (!state.mol) {
    // One row per molecule, each with its own numbers: tonnes are never added across molecules.
    dek.textContent = "Each molecule on its own: sourced capacity, how many plants have a published figure, and who leads.";
    box.innerHTML = `<div class="tablewrap"><table class="grid compact"><thead><tr><th>Molecule</th><th class="n">Plants</th>
      <th class="n">Sourced capacity</th><th class="n">Plants with a figure</th><th>Largest published</th><th>Hub</th></tr></thead><tbody>${tracked
      .map((m) => {
        const rs = rowsFor(m.id).filter(matches);
        const cos = shares(rs, groupName);
        const hub = shares(rs, (r) => r.s.country)[0];
        return `<tr><td data-l="Molecule"><a href="#" data-mol="${esc(m.id)}">${esc(molName(m.id))}</a></td>
          <td data-l="Plants" class="n">${new Set(rs.map((r) => r.s.id)).size}</td>
          <td data-l="Sourced capacity" class="n">${sourced(rs) ? esc(kt(sourced(rs))) : "<span class=nil>unknown</span>"}</td>
          <td data-l="Plants with a figure" class="n">${withSourcedCap(rs).length} of ${rs.length}</td>
          <td data-l="Largest published">${cos[0] ? `${esc(cos[0][0])}${coverage(rs).fair ? ` <small>${pct(cos[0][1])}</small>` : ""}` : ""}</td>
          <td data-l="Hub">${hub && coverage(rs).fair ? `${esc(cname(hub[0]))} <small>${pct(hub[1])}</small>` : "<span class=nil>too few figures</span>"}</td></tr>`;
      })
      .join("")}</tbody></table></div>
      <p class="small">Shares are of sourced capacity, shown only where at least two thirds of existing plants publish one. Pick a molecule for its producer list.</p>`;
    return;
  }
  const rs = scope();
  const cos = shares(rs, groupName);
  const countries = shares(rs, (r) => r.s.country);
  const top = cos[0];
  const top3 = cos.slice(0, 3).reduce((a, x) => a + x[1], 0);
  const what = molName(state.mol).toLowerCase();
  const unknown = [...new Set(rs.filter((r) => !counts(r)).map(groupName))].filter((n) => !cos.some((c) => c[0] === n));
  const cov = coverage(rs);
  dek.textContent = !top
    ? `No published capacity for ${what} yet.`
    : cov.fair
      ? `${top[0]} leads ${what} with ${pct(top[1])} of sourced capacity; the top three hold ${pct(top3)}. ${cname(countries[0][0])} hosts ${pct(countries[0][1])}. Shares cover the ${cov.with} of ${cov.of} existing plants with a published figure.`
      : `Only ${cov.with} of ${cov.of} existing plants publish a capacity, so this ranks those plants by tonnes and shows no market shares.`;
  const max = cos[0]?.[1] ?? 1;
  box.innerHTML = `<p class="k-label">${cov.fair ? "Share of sourced capacity, by group" : "Published capacity, by group (not a market share)"}</p><ol class="league">${cos
    .map(([name, share, rr]) => {
      const ctry = [...new Set(rr.map((r) => r.s.country))].map(cname).join(", ");
      const n = new Set(rr.map((r) => r.s.id)).size;
      return `<li><a href="#plants" data-q="${esc(name.replace(/ \(JV.*$/, ""))}" class="who">${esc(name)}</a>
        <span class="bar"><i style="width:${(share / max) * 100}%"></i></span>
        <span class="num">${esc(kt(sourced(rr)))}</span><span class="num sh">${cov.fair ? pct(share) : ""}</span>
        <span class="meta">${n} plant${n > 1 ? "s" : ""} · ${esc(ctry)}</span></li>`;
    })
    .join("")}</ol>
    ${unknown.length ? `<p class="small">Also on the map for ${esc(what)}, with no published capacity for a running plant: ${unknown.map(esc).join(", ")}.</p>` : ""}`;
}

function renderFilters(): void {
  const rs = scope();
  const countries = shares(rs, (r) => r.s.country).map((x) => x[0]);
  const groups = ["running", "building", "planned", "down", "unknown"].filter((g) =>
    rs.some((r) => (STATUS_GROUP[r.status?.v ?? ""] ?? "unknown") === g),
  );
  const el = document.getElementById("filters") as HTMLElement;
  el.innerHTML = `<label class="sel"><span class="sr">Country</span><select id="f-country">
      <option value="">All countries</option>${countries.map((c) => `<option value="${c}" ${state.country === c ? "selected" : ""}>${esc(cname(c))}</option>`).join("")}
    </select></label>
    <div class="pills" role="group" aria-label="Status">${["", ...groups]
      .map((g) => `<button type="button" class="pill ${state.status === g ? "on" : ""}" data-status="${g}">${g ? GROUP_LABEL[g] : "Any status"}</button>`)
      .join("")}</div>
    <label class="tog"><input type="checkbox" id="f-est" ${state.est ? "" : "checked"}/> Sourced figures only</label>`;
  (el.querySelector("#f-country") as HTMLSelectElement).addEventListener("change", (e) => {
    state.country = (e.target as HTMLSelectElement).value;
    renderPlants();
    drawMarkers();
  });
  el.querySelectorAll<HTMLElement>("[data-status]").forEach((b) =>
    b.addEventListener("click", () => {
      state.status = b.dataset.status!;
      renderFilters();
      renderPlants();
      drawMarkers();
    }),
  );
  (el.querySelector("#f-est") as HTMLInputElement).addEventListener("change", (e) => {
    state.est = !(e.target as HTMLInputElement).checked;
    writeURL();
    buildRows();
    renderAll();
  });
}

function renderPlants(): void {
  const rs = filtered();
  const key: Record<typeof state.sort, (r: Row) => string | number> = {
    cap: (r) => -(r.cap?.v ?? -1),
    plant: (r) => r.s.locality,
    country: (r) => cname(r.s.country),
    operator: (r) => companyName(r.op),
    status: (r) => STATUS_GROUP[r.status?.v ?? ""] ?? "z",
  };
  const k = key[state.sort];
  rs.sort((a, b) => {
    const x = k(a), y = k(b); // prettier-ignore
    return typeof x === "number" ? (x as number) - (y as number) : String(x).localeCompare(String(y));
  });
  const shown = state.all ? rs : rs.slice(0, 20);
  const th = (id: typeof state.sort, label: string, cls = "") =>
    `<th class="${cls}"><button type="button" data-sort="${id}" class="${state.sort === id ? "on" : ""}">${label}</button></th>`;
  const t = document.getElementById("plants-table") as HTMLTableElement;
  t.innerHTML = `<thead><tr>${th("plant", "Plant")}${th("country", "Country")}${th("operator", "Operator")}
    ${state.mol ? "" : "<th>Molecule</th>"}${th("cap", "Capacity", "n")}${th("status", "Status")}</tr></thead><tbody>${
      shown
        .map(
          (r) => `<tr><td data-l="Plant"><a href="#map" data-site="${esc(r.s.id)}">${esc(r.s.locality === cname(r.s.country) ? "Undisclosed site" : r.s.locality)}</a></td>
          <td data-l="Country">${esc(cname(r.s.country))}</td>
          <td data-l="Operator">${esc(companyName(r.op))}</td>
          ${state.mol ? "" : `<td data-l="Molecule"><a href="#" data-mol="${esc(r.m.id)}">${esc(molName(r.m.id))}</a></td>`}
          <td data-l="Capacity" class="n">${capChip(r)}</td><td data-l="Status">${statusChip(r)}</td></tr>`,
        )
        .join("") || `<tr><td colspan="6" class="empty">Nothing matches. Clear the search or the filters.</td></tr>`
    }</tbody>`;
  t.querySelectorAll<HTMLElement>("[data-sort]").forEach((b) =>
    b.addEventListener("click", () => {
      state.sort = b.dataset.sort as typeof state.sort;
      renderPlants();
    }),
  );
  const more = document.getElementById("plants-more") as HTMLButtonElement;
  more.hidden = rs.length <= 20;
  more.textContent = state.all ? "Show top 20" : `Show all ${rs.length} plants`;
}

function renderChain(): void {
  // Columns from the chain pack: tier (base, intermediate, specialty) and role (downstream = end products).
  const col = (m: Molecule): number =>
    m.tier === "base" ? 0 : m.tier === "intermediate" ? 1 : m.role === "downstream" ? 3 : 2;
  const titles = ["Base chemicals", "Intermediates", "Specialties", "End products"];
  const cols: Molecule[][] = [[], [], [], []];
  B.molecules.forEach((m) => cols[col(m)].push(m));
  const W = 1000, rowH = 46, top = 40, colW = (W - 280) / 3; // prettier-ignore
  const H = top + Math.max(...cols.map((c) => c.length)) * rowH + 10;
  const pos = new Map<string, [number, number]>();
  cols.forEach((c, i) => c.forEach((m, j) => pos.set(m.id, [70 + i * colW, top + j * rowH + rowH / 2 + ((Math.max(...cols.map((x) => x.length)) - c.length) * rowH) / 2])));
  const capOf = (id: string) => sourced(rowsFor(id));
  const maxCap = Math.max(1, ...B.molecules.map((m) => capOf(m.id)));
  const edges = B.routes
    .flatMap((r) => r.inputs.map((i) => [i.molecule_id, r.product_id] as [string, string]))
    .filter(([a, b]) => pos.has(a) && pos.has(b))
    .map(([a, b]) => {
      const [x1, y1] = pos.get(a)!;
      const [x2, y2] = pos.get(b)!;
      const hot = state.mol && (a === state.mol || b === state.mol);
      return `<path d="M${x1} ${y1} C${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}" class="edge ${hot ? "hot" : ""}"/>`;
    })
    .join("");
  const nodes = B.molecules
    .map((m) => {
      const [x, y] = pos.get(m.id)!;
      const c = capOf(m.id);
      const r = c ? 5 + 13 * Math.sqrt(c / maxCap) : 4;
      const on = isTracked(m.id);
      return `<g class="node ${on ? "live" : ""} ${state.mol === m.id ? "sel" : ""}" ${on ? `data-mol="${esc(m.id)}" tabindex="0" role="button"` : ""}>
        <circle cx="${x}" cy="${y}" r="${r}"/>
        <text x="${x + r + 6}" y="${y + 4}">${esc(molName(m.id))}${c ? ` <tspan class="cap">${esc(kt(c))}</tspan>` : ""}</text></g>`;
    })
    .join("");
  (document.getElementById("chain-graph") as HTMLElement).innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Production chain">
    ${titles.map((t, i) => `<text class="coltitle" x="${70 + i * colW - 8}" y="18">${t}</text>`).join("")}
    ${edges}${nodes}</svg>`;
}

// ---------------------------------------------------------------- trade flow chart (exporters → regions)

const REGION: Record<string, string> = {};
(
  [
    ["Europe", "AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK GB CH NO IS TR RU BY UA RS BA MK AL MD GE"],
    ["North America", "US CA MX"],
    ["Latin America", "BR AR CL CO PE EC UY PY BO VE CR PA GT HN SV NI DO DM CU JM TT HT BS BB"],
    ["South Asia", "IN PK BD LK NP AF BT MV"],
    ["Southeast Asia", "SG ID MY TH VN PH MM KH LA BN"],
    ["East Asia", "CN JP KR TW HK MO MN"],
    ["Middle East & Africa", "AE SA EG NG ZA KE GN MA DZ TN IL JO IR IQ KW QA OM BH LB SY YE ET GH CI SN TZ UG CM AO MZ ZW ZM"],
    ["Oceania", "AU NZ FJ PG"],
  ] as const
).forEach(([r, cs]) => cs.split(" ").forEach((c) => (REGION[c] = r)));
const OTHER = "Other destinations";
const EXPORTER = { CN: "China", EU: "EU-27", IN: "India", US: "United States", JP: "Japan" } as Record<string, string>;
const EX_COLOR = ["var(--cn)", "var(--eu)", "var(--st-building)", "var(--st-running)", "var(--faint)"];

function renderFlow(m: Molecule): string {
  const f = B.flows?.[m.id];
  if (!f) return "";
  // Estimated exporters (India: value only) appear only with estimates on, like every other estimate.
  const hidden = Object.entries(f.exporters).filter(([, d]) => d.estimate && !state.est).map(([e]) => EXPORTER[e] ?? e);
  const ex = Object.entries(f.exporters)
    .filter(([, d]) => state.est || !d.estimate)
    .sort((a, b) => b[1].total - a[1].total);
  if (!ex.length) return "";
  // exporter → region tonnes; what the top partners don't cover goes to "Other destinations"
  const links: [string, string, number][] = [];
  for (const [e, d] of ex) {
    const by = new Map<string, number>();
    let listed = 0;
    for (const [c, t] of Object.entries(d.partners)) {
      const r = REGION[c] ?? OTHER;
      by.set(r, (by.get(r) ?? 0) + t);
      listed += t;
    }
    if (d.total - listed > 0.5) by.set(OTHER, (by.get(OTHER) ?? 0) + d.total - listed);
    by.forEach((t, r) => t > 0 && links.push([e, r, t]));
  }
  const regions = [...new Set(links.map((l) => l[1]))]
    .map((r) => [r, links.filter((l) => l[1] === r).reduce((a, l) => a + l[2], 0)] as [string, number])
    .sort((a, b) => (a[0] === OTHER ? 1 : b[0] === OTHER ? -1 : b[1] - a[1]));
  const total = ex.reduce((a, [, d]) => a + d.total, 0);
  // Band thickness is proportional; each node also gets a minimum slot so its two-line label never collides.
  const W = 900, top = 34, gap = 12, x0 = 170, x1 = W - 240, nodeW = 12, minSlot = 38, span = 300; // prettier-ignore
  const k = span / total;
  const slot = (t: number) => Math.max(t * k, minSlot);
  const yL = new Map<string, number>();
  const yR = new Map<string, number>();
  let y = top;
  ex.forEach(([e, d]) => {
    yL.set(e, y + (slot(d.total) - d.total * k) / 2);
    y += slot(d.total) + gap;
  });
  const hL = y;
  y = top;
  regions.forEach(([r, t]) => {
    yR.set(r, y + (slot(t) - t * k) / 2);
    y += slot(t) + gap;
  });
  const H = Math.max(hL, y);
  const offL = new Map(yL), offR = new Map(yR); // prettier-ignore
  const color = (e: string) => EX_COLOR[ex.findIndex((x) => x[0] === e) % EX_COLOR.length];
  const bands = links
    .sort((a, b) => regions.findIndex((r) => r[0] === a[1]) - regions.findIndex((r) => r[0] === b[1]))
    .map(([e, r, t]) => {
      const h = Math.max(1, t * k);
      const ya = offL.get(e)! + h / 2;
      const yb = offR.get(r)! + h / 2;
      offL.set(e, offL.get(e)! + t * k);
      offR.set(r, offR.get(r)! + t * k);
      const est = f.exporters[e].estimate;
      return `<path class="flow-band" d="M${x0 + nodeW} ${ya} C${(x0 + x1) / 2} ${ya}, ${(x0 + x1) / 2} ${yb}, ${x1} ${yb}"
        stroke="${color(e)}" stroke-width="${h}" ${est ? 'stroke-opacity=".22"' : ""}><title>${esc(EXPORTER[e] ?? e)} → ${esc(r)}: ${est ? "~" : ""}${esc(kt(t, false))}</title></path>`;
    })
    .join("");
  const left = ex
    .map(([e, d]) => {
      const h = d.total * k;
      const y0 = yL.get(e)!;
      const est = !!d.estimate;
      return `<g class="flow-node"><rect x="${x0}" y="${y0}" width="${nodeW}" height="${Math.max(2, h)}" fill="${color(e)}"/>
        <text x="${x0 - 10}" y="${y0 + h / 2}" text-anchor="end" dominant-baseline="middle">${esc(EXPORTER[e] ?? e)}
          <tspan class="v" x="${x0 - 10}" dy="16">${est ? "~" : ""}${esc(kt(d.total, false))}</tspan></text></g>`;
    })
    .join("");
  const right = regions
    .map(([r, t]) => {
      const h = t * k;
      const y0 = yR.get(r)!;
      return `<g class="flow-node"><rect x="${x1}" y="${y0}" width="${nodeW}" height="${Math.max(2, h)}" fill="var(--faint)"/>
        <text x="${x1 + nodeW + 10}" y="${y0 + h / 2}" dominant-baseline="middle">${esc(r)}
          <tspan class="v" dx="8">${esc(kt(t, false))}</tspan></text></g>`;
    })
    .join("");
  const notes = ex
    .filter(([, d]) => d.estimate)
    .map(([e, d]) => `${EXPORTER[e] ?? e} is an estimate: ${d.estimate!.method} (${d.estimate!.price_usd_per_kg} US$/kg; range ${kt(d.estimate!.low, false)}–${kt(d.estimate!.high, false)}).`)
    .join(" ");
  const shared = m.cn_hs8 ? sharedLabel(`CN ${m.cn_hs8}`) : undefined;
  return `<div class="panel"><h3>Who ships to whom, ${f.year}${shared ? ` · ${esc(shared)}` : ""}</h3>
    <svg viewBox="0 0 ${W} ${H + 12}" role="img" aria-label="Exports by origin and destination region">
      <text class="flow-head" x="${x0 + nodeW}" y="14" text-anchor="end">Exporters</text>
      <text class="flow-head" x="${x1}" y="14">Destinations</text>
      ${bands}${left}${right}</svg>
    <p class="small">${ex.length > 1 ? `${ex.length} exporters, ${kt(total, false)} in all. ` : ""}${esc(
      [...new Set(ex.map(([, d]) => d.source.split(",")[0]))].join(" · "),
    )}. ${esc(notes)}${hidden.length ? ` ${esc(hidden.join(", "))} not shown: value-only data, tonnes would be an estimate (switch estimates on to see it).` : ""}${
      ex.length === 1 && !hidden.length
        ? shared
          ? ` Only China reports a code this narrow, and it covers ${esc(shared.replace(" (shared code)", ""))} together.`
          : " Only China's customs code isolates this molecule; other countries report it inside a broader code."
        : ""
    }</p></div>`;
}

function cnFor(m: Molecule) {
  const c = m.cn_hs8 ? B.cn_exports?.codes?.[m.cn_hs8] : undefined;
  if (!c) return null;
  const years = Object.keys(c.by_year).sort();
  const full = years.filter((y) => !c.partial_years[y]);
  const last = full[full.length - 1];
  const first = full[0];
  return { ...c, years, last, first, v: c.by_year[last], x: c.by_year[last] / Math.max(1, c.by_year[first]) };
}

function yearBars(c: NonNullable<ReturnType<typeof cnFor>>): string {
  const W = 300, H = 70, n = c.years.length, bw = W / n - 4; // prettier-ignore
  const max = Math.max(...c.years.map((y) => c.by_year[y]));
  return `<svg class="ybars" viewBox="0 0 ${W} ${H + 14}" role="img" aria-label="China exports by year">${c.years
    .map((y, i) => {
      const h = (c.by_year[y] / max) * H;
      const part = c.partial_years[y];
      return `<rect x="${i * (W / n) + 2}" y="${H - h}" width="${bw}" height="${h}" class="${part ? "part" : ""}"><title>${y}: ${kt(c.by_year[y], false)}${part ? ` (${part})` : ""}</title></rect>
        <text x="${i * (W / n) + 2 + bw / 2}" y="${H + 12}">${y.slice(2)}</text>`;
    })
    .join("")}</svg>`;
}

/** The label for a code that several molecules share ("alpha- + beta-pinene (shared code)"), if any. */
const sharedLabel = (code: string): string | undefined => B.trade_codes?.[code]?.label;
/** EU figures only where the HS6 code is the molecule's own; broad codes go to a footnote. */
const euFor = (m: Molecule) => (m.hs6_exact ? tradeFor(m) : null);

function broadNote(ms: Molecule[]): string {
  const codes = [...new Map(ms.filter((m) => !m.hs6_exact && m.hs6[0] && B.trade[m.hs6[0]]).map((m) => [m.hs6[0], m])).values()];
  if (!codes.length) return "";
  return `<p class="small">Not shown: EU trade under codes that cover more than the molecule. ${codes
    .map((m) => esc(m.hs6_scope ?? `HS ${m.hs6[0]}`))
    .join("; ")}.</p>`;
}

function renderTrade(): void {
  const body = document.getElementById("trade-body") as HTMLElement;
  const dek = document.getElementById("trade-dek") as HTMLElement;
  if (!state.mol) {
    (document.getElementById("flow-chart") as HTMLElement).innerHTML = "";
    dek.textContent = "China's customs exports and EU-27 imports, latest full year. Pick a molecule for the detail.";
    const seen = new Set<string>();
    const lines = tracked.filter((m) => {
      const key = m.cn_hs8 ? `CN ${m.cn_hs8}` : m.id;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    body.innerHTML = `<table class="grid compact"><thead><tr><th>Molecule</th><th class="n">China exports</th><th class="n">vs first year</th>
      <th class="n">EU imports</th><th>EU's main origin</th></tr></thead><tbody>${lines
      .map((m) => {
        const c = cnFor(m);
        const t = euFor(m);
        const label = m.cn_hs8 ? sharedLabel(`CN ${m.cn_hs8}`) : undefined;
        return `<tr><td data-l="Molecule"><a href="#" data-mol="${esc(m.id)}">${esc(label ?? molName(m.id))}</a></td>
          <td data-l="China exports" class="n">${c ? `${esc(kt(c.v, false))} <small>${c.last}</small>` : "<span class=nil>·</span>"}</td>
          <td data-l="vs first year" class="n">${c ? `<span class="${c.x >= 1 ? "up" : "down"}">${c.x.toFixed(1)}×</span> <small>${c.first}</small>` : ""}</td>
          <td data-l="EU imports" class="n">${t ? `${esc(kt(t.total, false))} <small>${t.year}</small>` : "<span class=nil>·</span>"}</td>
          <td data-l="EU's main origin">${t?.partners[0] ? `${esc(cname(t.partners[0][0]))} ${pct(t.partners[0][1] / t.total)}` : ""}</td></tr>`;
      })
      .join("")}</tbody></table>
      <p class="small">China: GACC customs, 8-digit codes. EU: Eurostat Comext, only where the code is the molecule's own.</p>
      ${broadNote(tracked)}`;
    return;
  }
  const m = molById.get(state.mol)!;
  const c = cnFor(m);
  const t = euFor(m);
  const shared = m.cn_hs8 ? sharedLabel(`CN ${m.cn_hs8}`) : undefined;
  const mapped = new Set(rowsFor(m.id).map((r) => r.s.country));
  dek.textContent = c
    ? `China shipped ${kt(c.v, false)} ${shared ? `of ${shared.replace(" (shared code)", "")} ` : ""}in ${c.last}, ${c.x.toFixed(1)}× ${c.first}.` + (t ? ` The EU imported ${kt(t.total, false)} under HS ${m.hs6[0]}.` : "")
    : t
      ? `The EU imported ${kt(t.total, false)} under HS ${m.hs6[0]} in ${t.year}.`
      : "No trade code isolates this molecule.";
  const cnPanel = c
    ? (() => {
        const dest = Object.entries(c.top_destinations).sort((a, b) => (b[1][c.last] ?? 0) - (a[1][c.last] ?? 0)).slice(0, 10);
        const max = dest[0]?.[1][c.last] ?? 1;
        const prev = String(Number(c.last) - 1);
        return `<div class="panel"><h3>Where China ships ${shared ? esc(shared.replace(" (shared code)", "")) : "it"}</h3>${shared ? `<p class="small"><span class="tag">shared code</span> one customs line covers ${esc(shared.replace(" (shared code)", ""))}; the figure is not ${esc(molName(m.id).toLowerCase())} alone.</p>` : ""}${yearBars(c)}
          <ol class="trade">${dest
            .map(([iso, v]) => {
              const d = v[prev] ? (v[c.last] - v[prev]) / v[prev] : null;
              return `<li><span class="who">${esc(cname(iso))}</span><span class="bar"><i class="cn" style="width:${(v[c.last] / max) * 100}%"></i></span>
                <span class="num">${esc(kt(v[c.last], false))}</span><span class="num chg ${d == null ? "" : d >= 0 ? "up" : "down"}">${d == null ? "new" : `${d >= 0 ? "+" : ""}${Math.round(d * 100)}%`}</span></li>`;
            })
            .join("")}</ol>
          <p class="small">GACC customs code ${esc(m.cn_hs8 ?? "")} (${esc(c.description)}). Change vs ${prev}. ${Object.entries(c.partial_years).map(([y, p]) => `${y} = ${p}`).join("; ")}.</p></div>`;
      })()
    : "";
  const euPanel = t
    ? (() => {
        const max = t.partners[0]?.[1] ?? 1;
        return `<div class="panel"><h3>Where Europe buys it</h3><ol class="trade">${t.partners
          .slice(0, 10)
          .map(([cc, v, series]) => `<li><span class="who">${esc(cname(cc))}${mapped.has(cc) ? "" : ` <span class="tag" title="No plant mapped in this country yet">no plant mapped</span>`}</span>
            <span class="bar"><i style="width:${(v / max) * 100}%"></i></span><span class="num">${esc(kt(v, false))}</span>
            <span class="spark">${spark(series)}</span></li>`)
          .join("")}</ol>
          <p class="small">Eurostat Comext, HS ${esc(m.hs6[0])}, ${t.year}; line ${t.first}–${t.year}.</p></div>`;
      })()
    : "";
  (document.getElementById("flow-chart") as HTMLElement).innerHTML = renderFlow(m);
  body.innerHTML = `<div class="tradegrid">${cnPanel}${euPanel}</div>
    ${m.trade_basis ? `<p class="small"><b>Trade basis:</b> ${esc(m.trade_basis)}</p>` : ""}
    ${broadNote([m])}`;
}

function tradeFor(m: Molecule) {
  const code = m.hs6[0];
  const d = code ? B.trade[code] : undefined;
  if (!d) return null;
  const years = [...new Set(Object.values(d).flatMap((y) => Object.keys(y)))].sort();
  // the latest year with most partners reported (the current year is often incomplete)
  const year = years.filter((y) => Object.values(d).filter((p) => p[y]).length >= Object.keys(d).length * 0.5).pop() ?? years[years.length - 1];
  const partners = Object.entries(d)
    .map(([c, ys]) => [c, ys[year] ?? 0, years.map((y) => ys[y] ?? 0)] as [string, number, number[]])
    .filter((x) => x[1] > 0)
    .sort((a, b) => b[1] - a[1]);
  return { year, first: years[0], total: partners.reduce((a, x) => a + x[1], 0), partners };
}

function spark(series: number[]): string {
  const w = 90, h = 20, max = Math.max(1, ...series); // prettier-ignore
  const pts = series.map((v, i) => `${(i / Math.max(1, series.length - 1)) * w},${h - (v / max) * (h - 2) - 1}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}"/></svg>`;
}

function renderEvents(): void {
  const list = [...B.events]
    .filter((e) => {
      const u = B.units.find((x) => e.subjects.includes(x.id));
      return !state.mol || !u || u.molecule_id === state.mol;
    })
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 12);
  (document.getElementById("event-list") as HTMLElement).innerHTML = list
    .map((e) => {
      const u = B.units.find((x) => e.subjects.includes(x.id));
      const s = u ? siteById.get(u.site_id) : undefined;
      return `<li><time>${esc(e.date)}</time><div><p>${esc(e.summary)}</p><p class="meta">
        ${u ? `<a href="#" data-mol="${esc(u.molecule_id)}">${esc(molName(u.molecule_id))}</a>` : ""}
        ${s ? ` · <a href="#map" data-site="${esc(s.id)}">${esc(s.locality)}</a>` : ""} · ${srcChip(e.evidence_ids, e.type, e.date)}</p></div></li>`;
    })
    .join("");
}

function renderMethod(): void {
  (document.getElementById("method-body") as HTMLElement).innerHTML = `
    <div class="cols">
      <div><h4>Every number has a source</h4><p>Tap a figure to see the sentence it came from: company filings,
        environmental permits, exchange documents, government registers, trade press. Code checks that the quote
        is really on the page. Grades: A primary source, B trade press, C aggregator.</p></div>
      <div><h4>Unknown means unknown</h4><p>Where no source gives a figure, the map says so: a blank capacity, or
        "status unconfirmed" with the date we last saw the plant in a source. A figure with <b>~</b> is an estimate, shown as a
        range with its method; we use only methods that pass a <a href="${BACKTEST}" target="_blank" rel="noopener">backtest</a>
        on sourced plants. Know a figure? Tell us, with a public source.</p></div>
      <div><h4>Locations</h4><p>Plants sit at their published coordinates where a permit gives them, otherwise
        in their town or region. Fine for a regional view, not for logistics.</p></div>
      <div><h4>Trade</h4><p>China's exports from GACC customs (8-digit codes), EU-27 trade from Eurostat Comext. A
        code shared by two molecules is shown once, under both names; codes that cover a wider family are left out
        and named in a footnote.</p></div>
    </div>
    <p class="small">Data ${esc(B.licence)} · built ${esc(B.built_on)} · <a href="${REPO}" target="_blank" rel="noopener">Code and data on GitHub</a>
      · Basemap © OpenMapTiles © OpenStreetMap contributors, OpenFreeMap; Natural Earth.</p>`;
}

function renderAll(): void {
  payloads.length = 0;
  renderTabs();
  drawMarkers();
  renderKPIs();
  renderLeague();
  renderFilters();
  renderPlants();
  renderChain();
  renderTrade();
  renderEvents();
  if (state.site && siteById.get(state.site)) renderSheet(siteById.get(state.site)!);
}

// ---------------------------------------------------------------- boot

async function boot(): Promise<void> {
  readURL();
  B = await loadJSON<Bundle>("bundle-data", `./data/${CHAIN}.json`);
  readEst();
  B.molecules.forEach((m) => molById.set(m.id, m));
  B.sites.forEach((s) => siteById.set(s.id, s));
  B.companies.forEach((c) => coById.set(c.id, c));
  buildRows();
  if (state.mol && !isTracked(state.mol)) state.mol = "";

  document.getElementById("plants-more")!.addEventListener("click", () => {
    state.all = !state.all;
    renderPlants();
  });
  const q = document.getElementById("q") as HTMLInputElement;
  q.addEventListener("input", () => {
    state.q = q.value.trim();
    renderAll();
  });

  map = new maplibregl.Map({
    container: "mapcanvas",
    style: OFFLINE ? offlineStyle(await basemap()) : MAP_STYLE[isDark() ? "dark" : "light"],
    center: [60, 25],
    zoom: 1.3,
    attributionControl: { compact: true },
    cooperativeGestures: matchMedia("(pointer: coarse)").matches,
    dragRotate: false,
    pitchWithRotate: false,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.on("style.load", () => !OFFLINE && tintBasemap());
  if (!OFFLINE) {
    let loaded = false;
    map.once("style.load", () => (loaded = true));
    const fallback = async () => {
      if (loaded) return;
      loaded = true;
      map.setStyle(offlineStyle(await basemap()));
    };
    map.on("error", (e) => {
      if (!loaded && /style|fetch|Failed/i.test(String(e.error?.message ?? ""))) void fallback();
    });
    setTimeout(() => void fallback(), 6000);
  }
  map.on("click", () => state.site && selectSite("", false));
  document.getElementById("theme")!.addEventListener("click", () => void setTheme(isDark() ? "light" : "dark"));
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (document.documentElement.dataset.theme) return; // the viewer's own choice wins
    syncTheme();
    void restyleMap();
  });

  renderMethod();
  renderAll();
  fitToScope();
  if (state.site) selectSite(state.site, false);
}

boot().catch((e) => {
  (document.getElementById("kpis") as HTMLElement).innerHTML = `<p class="err">The data didn't load (${esc(
    (e as Error).message,
  )}). Reload the page.</p>`;
  console.error(e);
});
