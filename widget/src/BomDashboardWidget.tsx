import "./styles.css";

import { useEffect, useMemo, useState } from "react";

import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";
import { generateSnowflakeIdAtTime } from "doover-js";
import {
  useDeviceMap,
  useMultiAgentAggregates,
  useMultiAgentChannelMessages,
} from "doover-js/react";

import {
  FLOOD_SEVERITY,
  HISTORY_WINDOW_MS,
  bomAppKey,
  fmt,
  isReporting,
  lastReading,
  relativeTime,
  toGauge,
  type FloodBand,
  type Gauge,
  type GaugeDevice,
  type TagValues,
} from "./lib/gauges";

interface WidgetProps {
  uiElement?: { app_key?: string };
}

const CLASS_STYLES: Record<string, string> = {
  "Below flood level": "bg-green-100 text-green-800",
  Minor: "bg-yellow-100 text-yellow-800",
  Moderate: "bg-orange-100 text-orange-800",
  Major: "bg-red-100 text-red-800",
};

const TREND_ARROWS: Record<string, string> = { rising: "↑", falling: "↓", steady: "→" };

function useNow(intervalMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function Summary({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
      {detail && <div className="truncate text-xs text-muted-foreground">{detail}</div>}
    </div>
  );
}

/** Flood bands as a horizontal bar, with a marker at the current level. */
function FloodBar({ bands, level }: { bands: FloodBand[]; level: number | null }) {
  if (bands.length === 0) {
    return <div className="text-xs text-muted-foreground">No flood levels for this gauge</div>;
  }
  const lo = bands[0].min;
  const hi = bands[bands.length - 1].max;
  const pct = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100))}%`;
  return (
    <div>
      <div className="relative flex h-2.5 overflow-visible rounded-full">
        {bands.map((b, i) => (
          <div
            key={b.label}
            title={`${b.label}: ${b.min}–${b.max} m`}
            className={`h-full ${i === 0 ? "rounded-l-full" : ""} ${i === bands.length - 1 ? "rounded-r-full" : ""}`}
            style={{ width: `${((b.max - b.min) / (hi - lo)) * 100}%`, background: b.colour, opacity: 0.75 }}
          />
        ))}
        {level != null && (
          <div
            className="absolute -top-1 h-4.5 w-1 -translate-x-1/2 rounded bg-foreground ring-2 ring-card"
            style={{ left: pct(level) }}
            title={`${level.toFixed(2)} m`}
          />
        )}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground tabular-nums">
        {bands.slice(1).map((b) => (
          <span key={b.label}>
            {b.label} {b.min} m
          </span>
        ))}
      </div>
    </div>
  );
}

/** Last 24 h of river level, with the minor flood level drawn if it is in view. */
function Sparkline({ points, bands, now }: { points: Array<[number, number]>; bands: FloodBand[]; now: number }) {
  const w = 280;
  const h = 56;
  if (points.length < 2) {
    return <div className="flex h-14 items-center text-xs text-muted-foreground">Collecting history…</div>;
  }
  const values = points.map(([, v]) => v);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (hi - lo < 0.1) {
    lo -= 0.05;
    hi += 0.05;
  }
  const t0 = now - HISTORY_WINDOW_MS;
  const x = (t: number) => ((t - t0) / HISTORY_WINDOW_MS) * w;
  const y = (v: number) => h - 4 - ((v - lo) / (hi - lo)) * (h - 8);
  const d = points.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const minor = bands[1]?.min;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-14 w-full" preserveAspectRatio="none" role="img" aria-label="River level, last 24 hours">
      {minor != null && minor >= lo && minor <= hi && (
        <line x1={0} x2={w} y1={y(minor)} y2={y(minor)} stroke="#eab308" strokeDasharray="4 3" strokeWidth={1} />
      )}
      <path d={d} fill="none" stroke="#2563eb" strokeWidth={1.75} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function GaugeCard({ g, now }: { g: Gauge; now: number }) {
  const reporting = isReporting(g, now);
  return (
    <a
      href={`/agent/${g.id}`}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 text-inherit no-underline hover:shadow-sm"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold">{g.name}</div>
          <div className="text-xs text-muted-foreground">
            {reporting ? "" : "Not reporting · "}
            {relativeTime(lastReading(g), now)}
          </div>
        </div>
        {g.floodClass && (
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${CLASS_STYLES[g.floodClass] ?? "bg-muted"}`}>
            {g.floodClass}
          </span>
        )}
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{fmt(g.level, 2, " m")}</span>
        {g.trend && (
          <span className="text-sm text-muted-foreground">
            {TREND_ARROWS[g.trend] ?? ""} {g.trend}
          </span>
        )}
        {g.datum && <span className="ml-auto text-[10px] text-muted-foreground">{g.datum}</span>}
      </div>

      <FloodBar bands={g.bands} level={g.level} />
      <Sparkline points={g.history} bands={g.bands} now={now} />

      <div className="grid grid-cols-2 gap-2 border-t border-border pt-2 text-sm">
        <div>
          <div className="text-xs text-muted-foreground">Rain last hour</div>
          <div className="tabular-nums">{fmt(g.rainHour, 1, " mm")}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Rain since 9am</div>
          <div className="tabular-nums">{fmt(g.rain9am, 1, " mm")}</div>
        </div>
      </div>
    </a>
  );
}

function Message({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-border p-4 text-center text-sm text-muted-foreground">{children}</div>;
}

function BomDashboardWidgetInner({ uiElement }: WidgetProps) {
  const params = useRemoteParams();
  const agentId = params?.agentId == null ? undefined : String(params.agentId);
  const appKey = uiElement?.app_key;
  const now = useNow();

  const { devices, deviceIds, hasDeviceMap, isLoading } = useDeviceMap<GaugeDevice>(agentId, appKey);
  const { aggregatesByAgent, query } = useMultiAgentAggregates<TagValues>("tag_values", deviceIds);

  const bomKeys = useMemo(
    () => [...new Set(devices.map((d) => bomAppKey(d, aggregatesByAgent[d.id]?.data)).filter(Boolean))] as string[],
    [devices, aggregatesByAgent],
  );
  // Fixed per mount, so the history query key doesn't change every minute.
  const [after] = useState(() => generateSnowflakeIdAtTime(Date.now() - HISTORY_WINDOW_MS));
  const { messages } = useMultiAgentChannelMessages<Record<string, Record<string, unknown>>>(
    "tag_values",
    deviceIds,
    { fields: bomKeys, after, agentMessageLimit: 500, autoPaginate: true, maxPages: 10 },
  );

  const gauges = useMemo(() => {
    const history: Record<string, Array<[number, number]>> = {};
    for (const m of messages ?? []) {
      const device = m.channel?.agent_id;
      if (!device) continue;
      for (const key of bomKeys) {
        const v = m.data?.[key]?.river_level;
        if (typeof v === "number") (history[device] ??= []).push([m.timestamp, v]);
      }
    }
    return devices
      .map((d) => toGauge(d, aggregatesByAgent[d.id]?.data, (history[d.id] ?? []).sort((a, b) => a[0] - b[0])))
      .filter((g) => g.appKey)
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [devices, aggregatesByAgent, messages, bomKeys]);

  if (!agentId || !appKey) return <Message>The dashboard host did not provide an agent ID and app key.</Message>;
  if (isLoading || (deviceIds.length > 0 && query.isLoading)) return <Message>Loading gauges…</Message>;
  if (!hasDeviceMap) return <Message>Give this dashboard permission to a group of BOM gauges in its app settings.</Message>;
  if (gauges.length === 0) return <Message>None of the permitted devices run the Bureau of Meteorology app.</Message>;

  const worst = gauges.reduce<Gauge | null>(
    (w, g) => ((FLOOD_SEVERITY[g.floodClass ?? ""] ?? -1) > (FLOOD_SEVERITY[w?.floodClass ?? ""] ?? -1) ? g : w),
    null,
  );
  const wettest = gauges.reduce<Gauge | null>((w, g) => ((g.rain9am ?? -1) > (w?.rain9am ?? -1) ? g : w), null);
  const rising = gauges.filter((g) => g.trend === "rising");
  const reporting = gauges.filter((g) => isReporting(g, now));

  return (
    <section className="flex flex-col gap-4 text-sm" aria-label="River and rain overview">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Summary
          label="Flood status"
          value={!worst || (FLOOD_SEVERITY[worst.floodClass ?? ""] ?? 0) === 0 ? "No flooding" : `${worst.floodClass} flood`}
          detail={worst && (FLOOD_SEVERITY[worst.floodClass ?? ""] ?? 0) > 0 ? worst.name : `${gauges.length} gauges below flood level`}
        />
        <Summary
          label="Rivers rising"
          value={`${rising.length} of ${gauges.length}`}
          detail={rising.map((g) => g.name).join(", ") || "None rising"}
        />
        <Summary
          label="Wettest since 9am"
          value={fmt(wettest?.rain9am ?? null, 1, " mm")}
          detail={wettest && (wettest.rain9am ?? 0) > 0 ? wettest.name : "No rain recorded"}
        />
        <Summary
          label="Reporting"
          value={`${reporting.length} of ${gauges.length}`}
          detail={reporting.length === gauges.length ? "All gauges current" : "Some gauges silent for 2 h+"}
        />
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {gauges.map((g) => (
          <GaugeCard key={g.id} g={g} now={now} />
        ))}
      </div>
      <div className="text-right text-[11px] text-muted-foreground">Data: Bureau of Meteorology</div>
    </section>
  );
}

const BomDashboardWidget = (props: WidgetProps) => (
  <RemoteComponentWrapper>
    <BomDashboardWidgetInner {...props} />
  </RemoteComponentWrapper>
);

export default BomDashboardWidget;
