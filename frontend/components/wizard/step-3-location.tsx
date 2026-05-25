"use client";

import "mapbox-gl/dist/mapbox-gl.css";

import { useCallback, useEffect, useRef, useState } from "react";
import Map, { Marker, type MapRef } from "react-map-gl/mapbox";

import { api, type Project } from "@/lib/api";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN ?? "";

type GeocodingFeature = {
  id: string;
  place_name: string;
  center: [number, number]; // [lng, lat]
  context?: { id: string; text: string }[];
  text?: string;
};

type SelectedLocation = {
  address: string;
  latitude: number;
  longitude: number;
  city: string | null;
  country: string | null;
};

function extractContext(feature: GeocodingFeature, prefix: string): string | null {
  const ctx = feature.context?.find((c) => c.id.startsWith(prefix));
  return ctx?.text ?? null;
}

export function Step3Location({
  project,
  onSaved,
  onBack,
}: {
  project: Project;
  onSaved: (project: Project) => void;
  onBack: () => void;
}) {
  const [query, setQuery] = useState(project.address ?? "");
  const [suggestions, setSuggestions] = useState<GeocodingFeature[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [location, setLocation] = useState<SelectedLocation | null>(
    project.address && project.latitude !== null && project.longitude !== null
      ? {
          address: project.address,
          latitude: project.latitude,
          longitude: project.longitude,
          city: project.city,
          country: project.country,
        }
      : null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mapRef = useRef<MapRef | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearch = useCallback(
    (text: string) => {
      setQuery(text);
      if (searchTimer.current) clearTimeout(searchTimer.current);
      if (!text.trim() || !MAPBOX_TOKEN) {
        setSuggestions([]);
        return;
      }
      searchTimer.current = setTimeout(async () => {
        try {
          const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(
            text,
          )}.json?access_token=${MAPBOX_TOKEN}&language=es&limit=5`;
          const res = await fetch(url);
          if (!res.ok) throw new Error("geocoding falló");
          const data = (await res.json()) as { features: GeocodingFeature[] };
          setSuggestions(data.features);
          setShowSuggestions(true);
        } catch {
          setSuggestions([]);
        }
      }, 300);
    },
    [],
  );

  function pickSuggestion(feature: GeocodingFeature) {
    const [lng, lat] = feature.center;
    const selected: SelectedLocation = {
      address: feature.place_name,
      latitude: lat,
      longitude: lng,
      city: extractContext(feature, "place") ?? extractContext(feature, "locality"),
      country: extractContext(feature, "country"),
    };
    setLocation(selected);
    setQuery(feature.place_name);
    setShowSuggestions(false);
    mapRef.current?.flyTo({ center: [lng, lat], zoom: 16, duration: 1200 });
  }

  async function handleSave() {
    if (!location) {
      setError("Buscá y elegí una dirección antes de continuar");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const updated = await api.updateProjectLocation(project.id, {
        address: location.address,
        latitude: location.latitude,
        longitude: location.longitude,
        city: location.city,
        country: location.country,
      });
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error guardando ubicación");
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, []);

  if (!MAPBOX_TOKEN) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
        Falta configurar <code>NEXT_PUBLIC_MAPBOX_TOKEN</code> en el .env del proyecto.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Localización del proyecto</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Buscá la dirección de la obra y elegila del listado. El mapa se centra
        automáticamente.
      </p>

      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
          onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
          placeholder="Av. Belgrano 1234, Buenos Aires"
          className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
        />
        {showSuggestions && suggestions.length > 0 && (
          <ul className="absolute left-0 right-0 top-full z-10 mt-1 max-h-64 overflow-auto rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
            {suggestions.map((feature) => (
              <li key={feature.id}>
                <button
                  type="button"
                  onClick={() => pickSuggestion(feature)}
                  className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-700"
                >
                  {feature.place_name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="h-80 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
        <Map
          ref={mapRef}
          mapboxAccessToken={MAPBOX_TOKEN}
          initialViewState={{
            longitude: location?.longitude ?? -58.3816,
            latitude: location?.latitude ?? -34.6037,
            zoom: location ? 16 : 12,
          }}
          style={{ width: "100%", height: "100%" }}
          mapStyle="mapbox://styles/mapbox/streets-v12"
        >
          {location && (
            <Marker
              longitude={location.longitude}
              latitude={location.latitude}
              color="#0EA5E9"
            />
          )}
        </Map>
      </div>

      {location && (
        <div className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-900 dark:text-slate-300">
          <div>
            <strong>Dirección:</strong> {location.address}
          </div>
          <div>
            <strong>Coordenadas:</strong> {location.latitude.toFixed(5)},{" "}
            {location.longitude.toFixed(5)}
          </div>
        </div>
      )}

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <div className="mt-2 flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          disabled={submitting}
          className="text-sm text-slate-500 hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
        >
          ← Volver
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={submitting || !location}
          className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {submitting ? "Guardando..." : "Siguiente →"}
        </button>
      </div>
    </div>
  );
}
