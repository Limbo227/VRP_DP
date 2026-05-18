export type GeoJSONLineString = {
  type: "LineString";
  coordinates: [number, number][];
};

export type Depot = {
  delivery_id: string;
  customer_name: string;
  postcode: string;
  latitude: number;
  longitude: number;
};

export type Stop = {
  delivery_id: string;
  customer_name: string;
  postcode: string;
  latitude: number;
  longitude: number;
  demand: number;
  priority: string;
  cluster: number;
};

export type TurnStep = {
  index: number;
  instruction: string;
  maneuverType: string;
  modifier: string;
  street: string;
  distanceM: number;
  durationS: number;
  lon: number;
  lat: number;
};

export type VanResult = {
  id: number;
  label: string;
  color: string;
  stops: Stop[];
  visitOrder: string[];
  distanceMatrixKm: number;
  distanceRouteKm: number;
  durationSec: number;
  geometry: GeoJSONLineString | null;
  turns?: TurnStep[];
};

export type ProcessResponse = {
  depot: Depot;
  vans: VanResult[];
  summary: {
    totalStops: number;
    vehicleCount: number;
    kmeansInertia: number;
    sumDistanceMatrixKm: number;
    sumDistanceRouteKm: number;
    sumDurationSec: number;
    osrmBase: string;
    osrmProfile: string;
    maxStopsPerVehicle: number;
    includeTurns?: boolean;
  };
  warnings: string[];
};
