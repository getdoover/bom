import type { DeviceMapEntry } from "doover-js/react";

export const BOM_APP_NAME = "bom";
// A gauge is "reporting" if BOM has published a reading within this window.
export const REPORTING_WINDOW_MS = 2 * 60 * 60_000;
export const HISTORY_WINDOW_MS = 7 * 24 * 60 * 60_000;

export interface GaugeDevice extends DeviceMapEntry {
  group?: { name?: string | null } | null;
  app_installs?: Array<{ name?: string | null; application_name?: string | null }>;
}

/** `tag_values` aggregate: `{ <app_key>: { <tag>: value } }`. */
export type TagValues = Record<string, Record<string, unknown> | undefined>;

export interface FloodBand {
  label: string;
  min: number;
  max: number;
  colour: string;
}

export interface Gauge {
  id: string;
  name: string;
  appKey: string | null;
  level: number | null;
  levelTime: number | null;
  trend: string | null;
  floodClass: string | null;
  bands: FloodBand[];
  datum: string | null;
  rainHour: number | null;
  rain9am: number | null;
  rainTime: number | null;
  status: string | null;
  history: Array<[number, number]>;
}

export const FLOOD_SEVERITY: Record<string, number> = {
  "Below flood level": 0,
  Minor: 1,
  Moderate: 2,
  Major: 3,
};

export const BAND_COLOURS: Record<string, string> = {
  green: "#16a34a",
  yellow: "#eab308",
  orange: "#f97316",
  red: "#dc2626",
};

export function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}

/** The device's BoM Station install key (its `tag_values` root). */
export function bomAppKey(device: GaugeDevice, tags?: TagValues): string | null {
  for (const install of device.app_installs ?? []) {
    if (install?.application_name === BOM_APP_NAME && install.name) return install.name;
  }
  // Fall back to whichever app in the aggregate carries BOM tags.
  for (const [key, value] of Object.entries(tags ?? {})) {
    if (value && ("river_level" in value || "rain_since_9am" in value)) return key;
  }
  return null;
}

function bands(v: unknown): FloodBand[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((b) => {
    const min = num(b?.min);
    const max = num(b?.max);
    if (min == null || max == null) return [];
    return [{ label: str(b?.label) ?? "", min, max, colour: BAND_COLOURS[b?.colour] ?? b?.colour ?? "#94a3b8" }];
  });
}

export function toGauge(device: GaugeDevice, tags: TagValues | undefined, history: Array<[number, number]>): Gauge {
  const appKey = bomAppKey(device, tags);
  const t = (appKey && tags?.[appKey]) || {};
  return {
    id: device.id,
    name: str(device.display_name) ?? str(device.name) ?? device.id,
    appKey,
    level: num(t.river_level),
    levelTime: num(t.river_level_time),
    trend: str(t.river_trend),
    floodClass: str(t.river_flood_class),
    bands: bands(t.river_ranges),
    datum: str(t.river_datum),
    rainHour: num(t.rain_last_hour),
    rain9am: num(t.rain_since_9am),
    rainTime: num(t.rain_time),
    status: str(t.status),
    history,
  };
}

export function lastReading(g: Gauge): number | null {
  const times = [g.levelTime, g.rainTime].filter((t): t is number => t != null);
  return times.length ? Math.max(...times) : null;
}

export function isReporting(g: Gauge, now: number): boolean {
  const last = lastReading(g);
  return last != null && now - last <= REPORTING_WINDOW_MS;
}

export function relativeTime(ms: number | null, now: number): string {
  if (ms == null) return "no data";
  const mins = Math.round((now - ms) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function fmt(v: number | null, digits: number, unit = ""): string {
  return v == null ? "—" : `${v.toFixed(digits)}${unit}`;
}
