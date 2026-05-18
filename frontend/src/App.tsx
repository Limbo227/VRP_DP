import { useCallback, useEffect, useMemo, useState } from "react";
import RouteMap from "./RouteMap";
import TurnNav from "./TurnNav";
import type { ProcessResponse } from "./types";

type ViewVanFilter = "all" | number;

const defaultCsvHint =
  "Columns: delivery_id, customer_name, postcode, latitude, longitude, demand, priority — plus one DEPOT row.";

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [osrmBase, setOsrmBase] = useState("http://127.0.0.1:5000");
  const [profile, setProfile] = useState("driving");
  const [maxStops, setMaxStops] = useState(20);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ProcessResponse | null>(null);

  const [includeTurns, setIncludeTurns] = useState(true);
  const [viewVan, setViewVan] = useState<ViewVanFilter>("all");
  const [mapFocus, setMapFocus] = useState<{
    lat: number;
    lon: number;
    key: string;
  } | null>(null);

  useEffect(() => {
    setMapFocus(null);
  }, [viewVan]);

  const run = useCallback(async () => {
    setError(null);
    setData(null);
    setMapFocus(null);
    setViewVan("all");
    if (!file) {
      setError("Choose a CSV file first.");
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("osrm_base", osrmBase.trim());
      fd.append("osrm_profile", profile.trim());
      fd.append("max_stops_per_vehicle", String(maxStops));
      fd.append("include_turns", includeTurns ? "true" : "false");
      const res = await fetch("/api/process", { method: "POST", body: fd });
      const text = await res.text();
      if (!res.ok) {
        let msg = text;
        try {
          const j = JSON.parse(text) as { detail?: string | unknown };
          if (typeof j.detail === "string") msg = j.detail;
          else if (Array.isArray(j.detail))
            msg = j.detail.map((d) => JSON.stringify(d)).join("\n");
        } catch {
          /* plain text */
        }
        const prefix =
          res.status === 503
            ? "[503 — API offline] "
            : res.status === 500
              ? "[500] "
              : `[HTTP ${res.status}] `;
        throw new Error(prefix + (msg || "").trim() || `empty body`);
      }
      setData(JSON.parse(text) as ProcessResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [file, maxStops, osrmBase, profile, includeTurns]);

  const visibleVans = useMemo(() => {
    if (!data) return [];
    if (viewVan === "all") return data.vans;
    const one = data.vans.filter((v) => v.id === viewVan);
    return one.length > 0 ? one : data.vans;
  }, [data, viewVan]);

  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>VRP + OSRM</h1>
        <p className="sub">
          Upload <code>deliveries.csv</code> (with <code>DEPOT</code>). Server
          clusters stops (k-means, max per van), builds road matrix from OSRM,
          orders with NN→2-opt, then draws OSRM driving routes on the map.
        </p>
        <p className="sub" style={{ color: "var(--ok)", fontSize: "0.74rem" }}>
          Requires the API on <strong>127.0.0.1:8000</strong>{" "}
          <code style={{ fontSize: "0.7rem" }}>
            uvicorn app:app --reload --port 8000
          </code>{" "}
          from <code>frontend/server</code>, plus OSRM on the URL you set.
        </p>
        <label>CSV file</label>
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <p className="sub" style={{ marginTop: "0.35rem" }}>
          {defaultCsvHint}
        </p>
        <label>OSRM base URL</label>
        <input
          type="text"
          value={osrmBase}
          onChange={(e) => setOsrmBase(e.target.value)}
          placeholder="http://127.0.0.1:5000"
        />
        <label>Profile</label>
        <input
          type="text"
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          placeholder="driving"
        />
        <label>Max stops per vehicle</label>
        <input
          type="number"
          min={2}
          max={100}
          value={maxStops}
          onChange={(e) => setMaxStops(Number(e.target.value) || 20)}
        />
        <label className="row-check">
          <input
            type="checkbox"
            checked={includeTurns}
            onChange={(e) => setIncludeTurns(e.target.checked)}
          />
          <span>
            Request OSRM <strong>steps=true</strong> (turn-by-turn list; larger
            response)
          </span>
        </label>
        <button
          type="button"
          className="primary"
          disabled={loading}
          onClick={() => void run()}
        >
          {loading ? "Running…" : "Cluster & build routes"}
        </button>
        {error ? <div className="err">{error}</div> : null}
        {data?.warnings?.length ? (
          <div className="warn">
            {data.warnings.map((w) => (
              <div key={w}>{w}</div>
            ))}
          </div>
        ) : null}
        {data ? (
          <div className="summary">
            <div>
              <strong>Vehicles</strong> {data.summary.vehicleCount} ·{" "}
              <strong>Stops</strong> {data.summary.totalStops}
            </div>
            <div>
              <strong>Σ matrix (2-opt)</strong>{" "}
              {data.summary.sumDistanceMatrixKm.toFixed(2)} km
            </div>
            <div>
              <strong>Σ OSRM route</strong>{" "}
              {data.summary.sumDistanceRouteKm.toFixed(2)} km ·{" "}
              <strong>Σ duration</strong>{" "}
              {(data.summary.sumDurationSec / 60).toFixed(1)} min
            </div>
            <div>
              <strong>KMeans inertia</strong> {data.summary.kmeansInertia}
            </div>
            <div style={{ marginTop: "0.35rem", fontSize: "0.75rem" }}>
              OSRM: {data.summary.osrmBase} ({data.summary.osrmProfile})
              {data.summary.includeTurns === false ? " · steps off" : ""}
            </div>
          </div>
        ) : null}
        {data ? (
          <>
            <label className="van-filter-label">Show on map</label>
            <select
              className="van-filter"
              value={viewVan === "all" ? "all" : String(viewVan)}
              onChange={(e) => {
                const raw = e.target.value;
                setViewVan(raw === "all" ? "all" : Number(raw));
              }}
            >
              <option value="all">All vans (overlay)</option>
              {data.vans.map((v) => (
                <option key={v.id} value={String(v.id)}>
                  {v.label} only — {v.stops.length} stops,{" "}
                  {v.distanceRouteKm.toFixed(1)} km
                </option>
              ))}
            </select>
            <p className="sub van-filter-hint">
              Pick one van to hide other routes and stop clutter.
            </p>
          </>
        ) : null}
        {data ? (
          <TurnNav
            vans={visibleVans}
            includeTurns={data.summary.includeTurns !== false}
            onFocusTurn={(lat, lon, key) =>
              setMapFocus({ lat, lon, key })
            }
          />
        ) : null}
      </aside>
      <main className="map-wrap">
        {data ? (
          <RouteMap depot={data.depot} vans={visibleVans} focus={mapFocus} />
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              minHeight: "100vh",
              color: "var(--muted)",
              fontSize: "0.95rem",
            }}
          >
            Run a dataset to show the map.
          </div>
        )}
      </main>
    </div>
  );
}
