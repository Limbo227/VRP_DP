import { useEffect } from "react";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import type { Depot, VanResult } from "./types";

function FitBounds({
  depot,
  vans,
}: {
  depot: Depot;
  vans: VanResult[];
}) {
  const map = useMap();
  useEffect(() => {
    const bb = L.latLngBounds(
      L.latLng(depot.latitude, depot.longitude),
      L.latLng(depot.latitude, depot.longitude),
    );
    for (const v of vans) {
      for (const s of v.stops) {
        bb.extend([s.latitude, s.longitude]);
      }
      const g = v.geometry;
      if (g?.coordinates?.length) {
        for (const c of g.coordinates) {
          bb.extend([c[1], c[0]]);
        }
      }
    }
    if (bb.isValid()) {
      map.fitBounds(bb, { padding: [36, 36], maxZoom: 11 });
    }
  }, [depot, vans, map]);
  return null;
}

function MapFocus({
  focus,
}: {
  focus: { lat: number; lon: number; key: string } | null;
}) {
  const map = useMap();
  useEffect(() => {
    if (!focus) return;
    const z = Math.max(map.getZoom(), 15);
    map.setView([focus.lat, focus.lon], z, { animate: true, duration: 0.35 });
  }, [focus, map]);
  return null;
}

export default function RouteMap({
  depot,
  vans,
  focus,
}: {
  depot: Depot;
  vans: VanResult[];
  focus: { lat: number; lon: number; key: string } | null;
}) {
  const center: [number, number] = [depot.latitude, depot.longitude];
  return (
    <div className="map-wrap">
      <MapContainer
        center={center}
        zoom={9}
        scrollWheelZoom
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds depot={depot} vans={vans} />
        <MapFocus focus={focus} />
        <CircleMarker
          center={[depot.latitude, depot.longitude]}
          radius={11}
          pathOptions={{
            color: "#111",
            weight: 2,
            fillColor: "#ffab00",
            fillOpacity: 1,
          }}
        >
          <Popup>
            <strong>{depot.delivery_id}</strong>
            <br />
            {depot.postcode}
          </Popup>
        </CircleMarker>
        {vans.map((v) =>
          v.geometry ? (
            <GeoJSON
              key={`route-${v.id}`}
              data={v.geometry}
              style={{
                color: v.color,
                weight: 4,
                opacity: 0.92,
              }}
            />
          ) : null,
        )}
        {vans.flatMap((v) =>
          v.stops.map((s) => (
            <CircleMarker
              key={`${v.id}-${s.delivery_id}`}
              center={[s.latitude, s.longitude]}
              radius={6}
              pathOptions={{
                color: "#1a1a1a",
                weight: 1,
                fillColor: v.color,
                fillOpacity: 0.92,
              }}
            >
              <Popup>
                <strong>{s.delivery_id}</strong> — {v.label}
                <br />
                {s.customer_name}
                <br />
                Demand: {s.demand}
              </Popup>
            </CircleMarker>
          )),
        )}
        {focus ? (
          <CircleMarker
            key={focus.key}
            center={[focus.lat, focus.lon]}
            radius={9}
            pathOptions={{
              color: "#fff",
              weight: 3,
              fillColor: "#ff1744",
              fillOpacity: 1,
            }}
          >
            <Popup>Selected maneuver</Popup>
          </CircleMarker>
        ) : null}
      </MapContainer>
      <div className="legend-strip">
        {vans.map((v) => (
          <span key={v.id} style={{ background: v.color }}>
            {v.label}: {v.stops.length} stops ·{" "}
            {v.distanceRouteKm.toFixed(1)} km
          </span>
        ))}
      </div>
    </div>
  );
}
