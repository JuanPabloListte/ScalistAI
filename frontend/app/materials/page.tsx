"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  api,
  type Material,
  type MaterialCreatePayload,
  type MaterialYieldInput,
} from "@/lib/api";

const APPLIES_TO_OPTIONS: { value: string; label: string }[] = [
  { value: "wall", label: "Muro" },
  { value: "room_floor", label: "Recinto · Piso" },
  { value: "room_wall", label: "Recinto · Paredes" },
  { value: "room_perimeter", label: "Recinto · Perímetro" },
  { value: "opening", label: "Abertura · Área" },
  { value: "opening_perimeter", label: "Abertura · Perímetro" },
  { value: "beam", label: "Viga" },
  { value: "roof", label: "Techo / Losa" },
  { value: "column", label: "Columna" },
];

const UNIT_SUGGESTIONS = ["un", "m", "m²", "m³", "kg", "l", "ml"];

function appliesLabel(value: string): string {
  return APPLIES_TO_OPTIONS.find((o) => o.value === value)?.label ?? value;
}

export default function MaterialsPage() {
  const router = useRouter();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Material | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Material | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    api
      .listMaterials()
      .then(setMaterials)
      .catch((err) => {
        if (err instanceof Error && err.message.includes("401")) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Error desconocido");
      })
      .finally(() => setLoading(false));
  }, [router]);

  function handleCreated(m: Material) {
    setMaterials((prev) => [...prev, m].sort((a, b) => a.name.localeCompare(b.name)));
    setCreating(false);
  }

  function handleUpdated(m: Material) {
    setMaterials((prev) =>
      prev.map((x) => (x.id === m.id ? m : x)).sort((a, b) => a.name.localeCompare(b.name)),
    );
    setEditing(null);
  }

  function handleDeleted(id: number) {
    setMaterials((prev) => prev.filter((m) => m.id !== id));
    setDeleting(null);
  }

  const filtered = materials.filter((m) =>
    filter.trim()
      ? `${m.name} ${m.category}`.toLowerCase().includes(filter.trim().toLowerCase())
      : true,
  );

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-8 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-brand dark:text-sky-400">Materiales</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            Catálogo de materiales con rendimientos y precios. Se aplican al cómputo de los planos.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="shrink-0 rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
        >
          + Nuevo material
        </button>
      </header>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      {!loading && materials.length > 0 && (
        <div className="mb-4">
          <input
            type="search"
            placeholder="Filtrar por nombre o categoría..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
          />
        </div>
      )}

      {loading ? (
        <p className="text-slate-500 dark:text-slate-400">Cargando...</p>
      ) : materials.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-slate-700 dark:text-slate-400">
          <p className="mb-2 text-lg font-medium">Catálogo vacío</p>
          <p className="text-sm">
            Creá tu primer material para empezar a calcular cómputos.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {filtered.map((m) => (
            <li
              key={m.id}
              className="group rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">
                      {m.name}
                    </h3>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {m.category}
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      unidad: <strong>{m.unit}</strong>
                    </span>
                  </div>

                  {m.yields.length > 0 ? (
                    <div className="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                      {m.yields.map((y) => (
                        <div
                          key={y.id}
                          className="flex items-center justify-between rounded border border-slate-100 bg-slate-50/50 px-2 py-1 text-xs dark:border-slate-800 dark:bg-slate-950/40"
                        >
                          <span className="font-medium text-slate-600 dark:text-slate-300">
                            {appliesLabel(y.applies_to)}
                          </span>
                          <span className="text-slate-500 dark:text-slate-400">
                            {y.consumption} {m.unit} · merma {(y.waste_factor * 100).toFixed(0)}% · ${y.unit_price}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-3 text-xs italic text-slate-400">Sin rendimientos definidos.</p>
                  )}
                </div>

                <div className="flex shrink-0 items-center gap-1 opacity-70 transition group-hover:opacity-100">
                  <button
                    type="button"
                    onClick={() => setEditing(m)}
                    title="Editar"
                    aria-label="Editar material"
                    className="rounded-md p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                  >
                    <EditIcon />
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleting(m)}
                    title="Eliminar"
                    aria-label="Eliminar material"
                    className="rounded-md p-2 text-slate-400 transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                  >
                    <TrashIcon />
                  </button>
                </div>
              </div>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="rounded-lg border border-dashed border-slate-300 py-8 text-center text-sm text-slate-400 dark:border-slate-700">
              Ningún material coincide con &ldquo;{filter}&rdquo;.
            </li>
          )}
        </ul>
      )}

      {(creating || editing) && (
        <MaterialModal
          material={editing}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={editing ? handleUpdated : handleCreated}
        />
      )}

      {deleting && (
        <DeleteModal
          material={deleting}
          onCancel={() => setDeleting(null)}
          onDeleted={() => handleDeleted(deleting.id)}
        />
      )}
    </main>
  );
}

function MaterialModal({
  material,
  onCancel,
  onSaved,
}: {
  material: Material | null;
  onCancel: () => void;
  onSaved: (m: Material) => void;
}) {
  const isEdit = material != null;
  const [name, setName] = useState(material?.name ?? "");
  const [category, setCategory] = useState(material?.category ?? "");
  const [unit, setUnit] = useState(material?.unit ?? "");
  const [yields, setYields] = useState<MaterialYieldInput[]>(
    material?.yields.map((y) => ({
      applies_to: y.applies_to,
      consumption: y.consumption,
      waste_factor: y.waste_factor,
      unit_price: y.unit_price,
    })) ?? [],
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function addYield() {
    setYields((prev) => [
      ...prev,
      { applies_to: "wall", consumption: 1, waste_factor: 0.05, unit_price: 0 },
    ]);
  }

  function updateYield(i: number, patch: Partial<MaterialYieldInput>) {
    setYields((prev) => prev.map((y, idx) => (idx === i ? { ...y, ...patch } : y)));
  }

  function removeYield(i: number) {
    setYields((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !category.trim() || !unit.trim()) {
      setErr("Nombre, categoría y unidad son obligatorios");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const payload: MaterialCreatePayload = {
        name: name.trim(),
        category: category.trim(),
        unit: unit.trim(),
        yields,
      };
      const result = isEdit
        ? await api.updateMaterial(material!.id, payload)
        : await api.createMaterial(payload);
      onSaved(result);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onCancel}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col gap-4 overflow-y-auto rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
      >
        <h2 className="text-lg font-semibold">
          {isEdit ? `Editar material: ${material!.name}` : "Nuevo material"}
        </h2>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-sm sm:col-span-2">
            <span className="font-medium">Nombre *</span>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ej: Ladrillo hueco 18×18×33"
              className="rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Unidad *</span>
            <input
              type="text"
              required
              list="unit-suggestions"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              placeholder="un / m² / l..."
              className="rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
            />
            <datalist id="unit-suggestions">
              {UNIT_SUGGESTIONS.map((u) => (
                <option key={u} value={u} />
              ))}
            </datalist>
          </label>
        </div>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Categoría *</span>
          <input
            type="text"
            required
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="Ej: Mampostería, Pintura, Pisos, Zócalos..."
            className="rounded-md border border-slate-300 px-3 py-2 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-400"
          />
        </label>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">Rendimientos</span>
            <button
              type="button"
              onClick={addYield}
              className="rounded border border-brand px-2 py-0.5 text-xs font-medium text-brand hover:bg-brand hover:text-white dark:border-sky-400 dark:text-sky-400 dark:hover:bg-sky-400 dark:hover:text-slate-900"
            >
              + Agregar
            </button>
          </div>

          {yields.length === 0 ? (
            <p className="rounded-md border border-dashed border-slate-300 px-3 py-4 text-center text-xs text-slate-400 dark:border-slate-700">
              Sin rendimientos. Agregá uno para que el material aplique al cómputo.
            </p>
          ) : (
            <div className="space-y-2">
              {yields.map((y, i) => (
                <div
                  key={i}
                  className="grid grid-cols-12 gap-2 rounded-md border border-slate-200 bg-slate-50/40 p-2 text-xs dark:border-slate-800 dark:bg-slate-950/40"
                >
                  <select
                    value={y.applies_to}
                    onChange={(e) => updateYield(i, { applies_to: e.target.value })}
                    className="col-span-4 rounded border border-slate-300 bg-white px-2 py-1 focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                  >
                    {APPLIES_TO_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  <NumberField
                    className="col-span-3"
                    label="Consumo"
                    value={y.consumption}
                    onChange={(v) => updateYield(i, { consumption: v })}
                  />
                  <NumberField
                    className="col-span-2"
                    label="Merma"
                    value={y.waste_factor}
                    onChange={(v) => updateYield(i, { waste_factor: v })}
                    step={0.01}
                  />
                  <NumberField
                    className="col-span-2"
                    label="Precio"
                    value={y.unit_price}
                    onChange={(v) => updateYield(i, { unit_price: v })}
                  />
                  <button
                    type="button"
                    onClick={() => removeYield(i)}
                    title="Quitar rendimiento"
                    aria-label="Quitar rendimiento"
                    className="col-span-1 flex items-center justify-center rounded text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                  >
                    <TrashIcon />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}

        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-50"
          >
            {saving ? "Guardando..." : isEdit ? "Guardar cambios" : "Crear material"}
          </button>
        </div>
      </form>
    </div>
  );
}

function NumberField({
  className,
  label,
  value,
  onChange,
  step = 0.01,
}: {
  className?: string;
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
}) {
  const [str, setStr] = useState(String(value));
  useEffect(() => {
    setStr(String(value));
  }, [value]);
  return (
    <label className={`flex flex-col gap-0.5 ${className ?? ""}`}>
      <span className="text-[10px] uppercase tracking-wide text-slate-400">{label}</span>
      <input
        type="number"
        step={step}
        min={0}
        value={str}
        onChange={(e) => setStr(e.target.value)}
        onBlur={() => {
          const parsed = parseFloat(str);
          if (Number.isFinite(parsed) && parsed >= 0) {
            onChange(parsed);
          } else {
            setStr(String(value));
          }
        }}
        className="rounded border border-slate-300 bg-white px-1.5 py-1 text-xs focus:border-brand focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
      />
    </label>
  );
}

function DeleteModal({
  material,
  onCancel,
  onDeleted,
}: {
  material: Material;
  onCancel: () => void;
  onDeleted: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function confirm() {
    setDeleting(true);
    setErr(null);
    try {
      await api.deleteMaterial(material.id);
      onDeleted();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al eliminar");
      setDeleting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={deleting ? undefined : onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex w-full max-w-sm flex-col gap-4 rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800"
      >
        <h3 className="text-lg font-semibold">Eliminar material</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          ¿Eliminar <span className="font-semibold">{material.name}</span>? Se va a quitar también
          de todos los elementos que lo tengan asignado. Esta acción no se puede deshacer.
        </p>
        {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={deleting}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >
            {deleting ? "Eliminando..." : "Eliminar"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  );
}
