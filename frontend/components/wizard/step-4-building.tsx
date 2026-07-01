"use client";

import { useEffect, useState } from "react";

import { api, type BuildingType, type Project } from "@/lib/api";

type FieldDef = { key: string; label: string; suffix?: string; integer?: boolean };

export const BUILDING_FIELDS: Record<BuildingType, FieldDef[]> = {
  casa: [
    { key: "area_cubierta_m2", label: "Área cubierta", suffix: "m²" },
    { key: "area_descubierta_m2", label: "Área descubierta", suffix: "m²" },
    { key: "pisos", label: "Pisos", integer: true },
    { key: "habitaciones", label: "Habitaciones", integer: true },
    { key: "banos", label: "Baños", integer: true },
  ],
  edificio: [
    { key: "area_total_m2", label: "Área total construida", suffix: "m²" },
    { key: "pisos", label: "Cantidad de pisos", integer: true },
    { key: "unidades_por_piso", label: "Unidades por piso", integer: true },
    { key: "area_unidad_m2", label: "Área promedio por unidad", suffix: "m²" },
  ],
  condominio: [
    { key: "area_comun_m2", label: "Área común", suffix: "m²" },
    { key: "area_privada_m2", label: "Área privada total", suffix: "m²" },
    { key: "num_unidades", label: "Número de unidades", integer: true },
    { key: "pisos", label: "Pisos", integer: true },
  ],
  comercial: [
    { key: "area_cubierta_m2", label: "Área cubierta", suffix: "m²" },
    { key: "area_descubierta_m2", label: "Área descubierta", suffix: "m²" },
    { key: "pisos", label: "Pisos", integer: true },
    { key: "num_locales", label: "Número de locales", integer: true },
  ],
};

const TYPE_OPTIONS: { value: BuildingType; label: string; icon: string }[] = [
  { value: "casa", label: "Casa", icon: "🏠" },
  { value: "edificio", label: "Edificio", icon: "🏢" },
  { value: "condominio", label: "Condominio", icon: "🏘️" },
  { value: "comercial", label: "Comercial", icon: "🏬" },
];

export function Step4Building({
  project,
  onSaved,
  onBack,
}: {
  project: Project;
  onSaved: (project: Project) => void;
  onBack: () => void;
}) {
  const [buildingType, setBuildingType] = useState<BuildingType | null>(
    project.building_type ?? null,
  );
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    if (project.building_info) {
      for (const [k, v] of Object.entries(project.building_info)) {
        initial[k] = String(v);
      }
    }
    return initial;
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autofilled, setAutofilled] = useState(false);

  // El IFC precarga tipo + datos en el proyecto de forma ASÍNCRONA (procesa el
  // modelo en background). Al entrar al paso, re-consultamos el proyecto para
  // levantar esos datos si el usuario todavía no cargó nada a mano.
  useEffect(() => {
    if (buildingType || Object.keys(values).length > 0) return;
    api.getProject(project.id)
      .then((p) => {
        if (p.building_type) setBuildingType(p.building_type);
        if (p.building_info && Object.keys(p.building_info).length > 0) {
          const v: Record<string, string> = {};
          for (const [k, val] of Object.entries(p.building_info)) v[k] = String(val);
          setValues(v);
          setAutofilled(true);
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fields = buildingType ? BUILDING_FIELDS[buildingType] : [];
  const allFilled = fields.every((f) => {
    const raw = values[f.key];
    return raw !== undefined && raw !== "" && Number(raw) >= 0 && !Number.isNaN(Number(raw));
  });

  async function handleSave() {
    if (!buildingType || !allFilled) return;
    setError(null);
    setSubmitting(true);
    try {
      const numericValues: Record<string, number> = {};
      for (const f of fields) {
        numericValues[f.key] = Number(values[f.key]);
      }
      const updated = await api.updateProjectBuildingInfo(project.id, {
        building_type: buildingType,
        building_info: numericValues,
      });
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error guardando datos");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Información de construcción</h2>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Elegí el tipo de obra y completá los datos correspondientes.
      </p>

      {autofilled && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
          ✓ Datos precargados desde el modelo BIM. Revisalos y completá lo que falte.
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {TYPE_OPTIONS.map((opt) => {
          const active = buildingType === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => {
                setBuildingType(opt.value);
                // si cambia de tipo, descartar campos del tipo previo
                if (opt.value !== buildingType) setValues({});
              }}
              className={`flex flex-col items-center gap-1 rounded-lg border-2 p-4 transition ${
                active
                  ? "border-brand bg-brand/5 dark:border-sky-400 dark:bg-sky-400/10"
                  : "border-slate-200 hover:border-slate-300 dark:border-slate-700 dark:hover:border-slate-600"
              }`}
            >
              <span className="text-2xl">{opt.icon}</span>
              <span className="text-sm font-medium">{opt.label}</span>
            </button>
          );
        })}
      </div>

      {buildingType && (
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {fields.map((field) => (
            <label key={field.key} className="flex flex-col gap-1 text-sm">
              <span className="font-medium">{field.label}</span>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min="0"
                  step={field.integer ? "1" : "0.01"}
                  value={values[field.key] ?? ""}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                  }
                  className="flex-1 rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
                />
                {field.suffix && (
                  <span className="text-sm text-slate-500 dark:text-slate-400">
                    {field.suffix}
                  </span>
                )}
              </div>
            </label>
          ))}
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
          disabled={submitting || !buildingType || !allFilled}
          className="rounded-md bg-brand px-5 py-2 font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {submitting ? "Guardando..." : "Siguiente →"}
        </button>
      </div>
    </div>
  );
}
