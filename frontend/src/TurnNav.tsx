import type { VanResult } from "./types";

function fmtLen(m: number): string {
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${Math.round(m)} m`;
}

export default function TurnNav({
  vans,
  includeTurns,
  onFocusTurn,
}: {
  vans: VanResult[];
  includeTurns: boolean;
  onFocusTurn: (lat: number, lon: number, key: string) => void;
}) {
  if (!includeTurns) {
    return (
      <div className="turns-panel muted">
        Turn-by-turn was disabled for this run. Enable the checkbox before
        running <strong>Cluster &amp; build routes</strong> to load OSRM steps.
      </div>
    );
  }

  const anyTurns = vans.some((v) => (v.turns?.length ?? 0) > 0);
  if (!anyTurns) {
    return (
      <div className="turns-panel muted">
        No OSRM steps returned (route may have used straight-line fallback). Check
        OSRM and try again.
      </div>
    );
  }

  return (
    <div className="turns-panel">
      <h2 className="turns-title">Turn-by-turn (OSRM)</h2>
      <p className="turns-hint">
        {vans.length === 1 ? (
          <>
            Showing <strong>one van</strong> only (use &quot;Show on map&quot; to
            switch or show all).
          </>
        ) : (
          <>
            Click a step to move the map to that maneuver point (same data OSRM
            uses for navigation engines).
          </>
        )}
      </p>
      <div className="turns-scroll">
        {vans.map((v) => (
          <details key={v.id} className="van-turns" open={vans.length === 1}>
            <summary style={{ color: v.color }}>
              {v.label} · {(v.turns?.length ?? 0)} steps
            </summary>
            <ol className="turn-list">
              {(v.turns ?? []).map((t) => {
                const key = `${v.id}-${t.index}-${t.lat}-${t.lon}`;
                return (
                  <li key={key}>
                    <button
                      type="button"
                      className="turn-btn"
                      onClick={() => onFocusTurn(t.lat, t.lon, key)}
                    >
                      <span className="turn-inst">{t.instruction}</span>
                      <span className="turn-meta">
                        {fmtLen(t.distanceM)} · {t.durationS.toFixed(0)}s
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </details>
        ))}
      </div>
    </div>
  );
}
