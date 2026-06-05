"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useRef } from "react";

import {
  api,
  type Material,
  type Assembly,
  type AssemblyCreatePayload,
  type AssemblyMaterialInput,
} from "@/lib/api";

import { ExcelMapperModal } from "@/components/ExcelMapperModal";

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

const APPLIES_BASE_UNIT: Record<string, { unit: string; hint: string }> = {
  wall: { unit: "m² de muro", hint: "Cantidad de insumo por cada metro cuadrado de muro (largo × alto, descontando aberturas)." },
  room_floor: { unit: "m² de piso", hint: "Cantidad por cada metro cuadrado de piso del recinto." },
  room_wall: { unit: "m² de pared", hint: "Cantidad por cada metro cuadrado de pared interior del recinto." },
  room_perimeter: { unit: "m de perímetro", hint: "Cantidad por cada metro lineal del perímetro del recinto." },
  opening: { unit: "m² de abertura", hint: "Cantidad por cada metro cuadrado de la abertura." },
  opening_perimeter: { unit: "m de marco", hint: "Cantidad por cada metro lineal del marco de la abertura." },
  beam: { unit: "m de viga", hint: "Cantidad por cada metro lineal de viga." },
  roof: { unit: "m² de techo", hint: "Cantidad por cada metro cuadrado de techo o losa." },
  column: { unit: "m² de columna", hint: "Cantidad por cada metro cuadrado de columna." },
};

function baseUnitFor(appliesTo: string): { unit: string; hint: string } {
  return APPLIES_BASE_UNIT[appliesTo] ?? { unit: "unidad", hint: "" };
}

function appliesLabel(value: string): string {
  return APPLIES_TO_OPTIONS.find((o) => o.value === value)?.label ?? value;
}

export default function MaterialsPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"assemblies" | "materials">("assemblies");

  const [materials, setMaterials] = useState<Material[]>([]);
  const [assemblies, setAssemblies] = useState<Assembly[]>([]);
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modals state
  const [editingMaterial, setEditingMaterial] = useState<Material | null>(null);
  const [creatingMaterial, setCreatingMaterial] = useState(false);
  const [deletingMaterial, setDeletingMaterial] = useState<Material | null>(null);

  const [editingAssembly, setEditingAssembly] = useState<Assembly | null>(null);
  const [creatingAssembly, setCreatingAssembly] = useState(false);
  const [deletingAssembly, setDeletingAssembly] = useState<Assembly | null>(null);

  const [filter, setFilter] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedExcelFile, setSelectedExcelFile] = useState<File | null>(null);
  const [uploadingExcel, setUploadingExcel] = useState(false);

  useEffect(() => {
    Promise.all([api.listMaterials(), api.listAssemblies()])
      .then(([m, a]) => {
        setMaterials(m);
        setAssemblies(a);
      })
      .catch((err) => {
        if (err instanceof Error && err.message.includes("401")) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Error desconocido");
      })
      .finally(() => setLoading(false));
  }, [router]);

  // Handlers
  function handleMaterialCreated(m: Material) {
    setMaterials((prev) => [...prev, m].sort((a, b) => a.name.localeCompare(b.name)));
    setCreatingMaterial(false);
  }

  function handleMaterialUpdated(m: Material) {
    setMaterials((prev) =>
      prev.map((x) => (x.id === m.id ? m : x)).sort((a, b) => a.name.localeCompare(b.name)),
    );
    setEditingMaterial(null);
  }

  function handleMaterialDeleted(id: number) {
    setMaterials((prev) => prev.filter((m) => m.id !== id));
    // Also remove from assemblies locally for UI consistency
    setAssemblies((prev) => prev.map(a => ({
      ...a,
      assembly_materials: a.assembly_materials.filter(am => am.material.id !== id)
    })));
    setDeletingMaterial(null);
  }

  function handleAssemblyCreated(a: Assembly) {
    setAssemblies((prev) => [...prev, a].sort((x, y) => x.name.localeCompare(y.name)));
    setCreatingAssembly(false);
  }

  function handleAssemblyUpdated(a: Assembly) {
    setAssemblies((prev) =>
      prev.map((x) => (x.id === a.id ? a : x)).sort((x, y) => x.name.localeCompare(y.name)),
    );
    setEditingAssembly(null);
  }

  function handleAssemblyDeleted(id: number) {
    setAssemblies((prev) => prev.filter((a) => a.id !== id));
    setDeletingAssembly(null);
  }

  const filteredMaterials = materials.filter((m) =>
    filter.trim()
      ? `${m.name} ${m.category}`.toLowerCase().includes(filter.trim().toLowerCase())
      : true,
  );

  const filteredAssemblies = assemblies.filter((a) =>
    filter.trim()
      ? `${a.name} ${appliesLabel(a.applies_to)}`.toLowerCase().includes(filter.trim().toLowerCase())
      : true,
  );

  function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setSelectedExcelFile(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleMapComplete(items: any[]) {
    setSelectedExcelFile(null);
    setUploadingExcel(true);
    setError(null);
    try {
      const res = await api.uploadMaterialsJson(items);
      alert(`Éxito: Se importaron ${res.imported} nuevos insumos y se actualizaron ${res.updated}.`);
      
      const m = await api.listMaterials();
      setMaterials(m);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al subir Excel");
    } finally {
      setUploadingExcel(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">Cómputos</h1>
        <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
          Definí tus sistemas constructivos e insumos base para calcular materiales.
        </p>
      </header>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      {/* TABS */}
      <div className="mb-6 flex gap-4 border-b border-slate-200 dark:border-slate-800">
        <button
          onClick={() => setTab("assemblies")}
          className={`border-b-2 px-1 pb-2 text-sm font-medium transition ${
            tab === "assemblies"
              ? "border-brand-500 text-brand-600 dark:border-brand-400 dark:text-brand-400"
              : "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300"
          }`}
        >
          Sistemas Constructivos
        </button>
        <button
          onClick={() => setTab("materials")}
          className={`border-b-2 px-1 pb-2 text-sm font-medium transition ${
            tab === "materials"
              ? "border-brand-500 text-brand-600 dark:border-brand-400 dark:text-brand-400"
              : "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300"
          }`}
        >
          Insumos Base
        </button>
      </div>

      {!loading && (
        <div className="mb-4 flex items-center justify-between gap-4">
          <input
            type="search"
            placeholder="Filtrar..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full max-w-sm rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:border-brand-400 dark:focus:ring-brand-400/20"
          />
          {tab === "materials" && (
            <div>
              <input 
                type="file" 
                accept=".xlsx" 
                ref={fileInputRef} 
                onChange={handleFileUpload} 
                className="hidden" 
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadingExcel}
                className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              >
                {uploadingExcel ? "Subiendo..." : "Importar Excel"}
              </button>
            </div>
          )}
        </div>
      )}

      {loading ? (
        <p className="text-slate-500 dark:text-slate-400">Cargando...</p>
      ) : tab === "assemblies" ? (
        assemblies.length === 0 ? (
          <AddCard
            label="Crear primer sistema constructivo"
            description="Agrupá insumos base para crear muros, aberturas, vigas, etc."
            onClick={() => setCreatingAssembly(true)}
          />
        ) : (
          <ul className="space-y-3">
            <li>
              <AddCardInline
                label="Nuevo sistema"
                onClick={() => setCreatingAssembly(true)}
              />
            </li>
            {filteredAssemblies.map((a) => (
              <li
                key={a.id}
                className="group rounded-xl border border-slate-200 bg-white p-4 transition hover:border-brand-300 hover:shadow-surface dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-500/40"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">
                        {a.name}
                      </h3>
                      <span className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">
                        {appliesLabel(a.applies_to)}
                      </span>
                    </div>

                    {a.assembly_materials.length > 0 ? (
                      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {a.assembly_materials.map((am) => (
                          <div
                            key={am.id}
                            className="flex flex-col rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-800 dark:bg-slate-950"
                          >
                            <span className="font-semibold text-slate-700 dark:text-slate-200">
                              {am.material.name}
                            </span>
                            <span className="mt-1 text-slate-500 dark:text-slate-400">
                              Consumo: {am.consumption} {am.material.unit} <br/>
                              Merma: {(am.waste_factor * 100).toFixed(0)}%
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="mt-3 text-xs italic text-slate-400">Sin insumos asignados.</p>
                    )}
                  </div>

                  <div className="flex shrink-0 items-center gap-1 opacity-0 transition group-hover:opacity-100">
                    <button
                      onClick={() => setEditingAssembly(a)}
                      className="rounded-md p-2 text-slate-400 hover:bg-slate-100 hover:text-brand-600 dark:hover:bg-slate-800 dark:hover:text-brand-400"
                    >
                      <EditIcon />
                    </button>
                    <button
                      onClick={() => setDeletingAssembly(a)}
                      className="rounded-md p-2 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                </div>
              </li>
            ))}
            {filteredAssemblies.length === 0 && filter.trim() && (
              <p className="text-slate-500">No se encontraron sistemas.</p>
            )}
          </ul>
        )
      ) : (
        // MATERIALS TAB
        materials.length === 0 ? (
          <AddCard
            label="Crear primer insumo base"
            description="Cargá insumos como cemento, ladrillos o arena con su precio y unidad."
            onClick={() => setCreatingMaterial(true)}
          />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <li>
              <AddCardInline
                label="Nuevo insumo"
                onClick={() => setCreatingMaterial(true)}
              />
            </li>
            {filteredMaterials.map((m) => (
              <li
                key={m.id}
                className="group flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-4 transition hover:border-brand-300 hover:shadow-surface dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-500/40"
              >
                <div>
                  <div className="flex justify-between gap-2">
                    <h3 className="font-semibold text-slate-800 dark:text-slate-100">{m.name}</h3>
                    <div className="flex shrink-0 items-center opacity-0 transition group-hover:opacity-100">
                      <button onClick={() => setEditingMaterial(m)} className="p-1 text-slate-400 hover:text-brand-600"><EditIcon size={14}/></button>
                      <button onClick={() => setDeletingMaterial(m)} className="p-1 text-slate-400 hover:text-red-600"><TrashIcon size={14}/></button>
                    </div>
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-xs">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {m.category}
                    </span>
                  </div>
                </div>
                <div className="mt-4 flex items-center justify-between text-sm text-slate-500 dark:text-slate-400">
                  <span>Precio: <strong>${m.unit_price}</strong> / {m.unit}</span>
                </div>
              </li>
            ))}
            {filteredMaterials.length === 0 && filter.trim() && (
              <p className="col-span-full text-slate-500">No se encontraron insumos.</p>
            )}
          </ul>
        )
      )}

      {/* Modals */}
      {(creatingMaterial || editingMaterial) && (
        <MaterialModal
          material={editingMaterial}
          onCancel={() => { setCreatingMaterial(false); setEditingMaterial(null); }}
          onSaved={editingMaterial ? handleMaterialUpdated : handleMaterialCreated}
        />
      )}
      {deletingMaterial && (
        <DeleteModal
          title="Eliminar insumo"
          message={`¿Eliminar ${deletingMaterial.name}? Esto podría afectar a los sistemas constructivos que lo utilicen.`}
          onCancel={() => setDeletingMaterial(null)}
          onConfirm={async () => {
            await api.deleteMaterial(deletingMaterial.id);
            handleMaterialDeleted(deletingMaterial.id);
          }}
        />
      )}

      {(creatingAssembly || editingAssembly) && (
        <AssemblyModal
          assembly={editingAssembly}
          allMaterials={materials}
          onCancel={() => { setCreatingAssembly(false); setEditingAssembly(null); }}
          onSaved={editingAssembly ? handleAssemblyUpdated : handleAssemblyCreated}
        />
      )}
      {deletingAssembly && (
        <DeleteModal
          title="Eliminar sistema"
          message={`¿Eliminar el sistema constructivo ${deletingAssembly.name}? Se quitará de todos los elementos de los planos.`}
          onCancel={() => setDeletingAssembly(null)}
          onConfirm={async () => {
            await api.deleteAssembly(deletingAssembly.id);
            handleAssemblyDeleted(deletingAssembly.id);
          }}
        />
      )}

      {selectedExcelFile && (
        <ExcelMapperModal
          file={selectedExcelFile}
          onCancel={() => setSelectedExcelFile(null)}
          onMap={handleMapComplete}
        />
      )}
    </main>
  );
}

// ============================================================================
// COMPONENTS
// ============================================================================

function AddCard({
  label,
  description,
  onClick,
}: {
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group block w-full rounded-2xl border-2 border-dashed border-slate-300 bg-white px-6 py-16 text-center transition hover:border-brand-400 hover:bg-brand-50/30 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5"
    >
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400 transition group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-slate-800 dark:group-hover:bg-brand-500/10 dark:group-hover:text-brand-400">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
      </div>
      <p className="mb-1 text-base font-semibold text-slate-700 group-hover:text-brand-700 dark:text-slate-200 dark:group-hover:text-brand-300">
        {label}
      </p>
      <p className="text-sm text-slate-500 dark:text-slate-400">{description}</p>
    </button>
  );
}

function AddCardInline({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex h-full min-h-[100px] w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-white p-4 text-center transition hover:border-brand-400 hover:bg-brand-50/30 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5"
    >
      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-400 transition group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-slate-800 dark:group-hover:bg-brand-500/10 dark:group-hover:text-brand-400">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
      </div>
      <span className="text-sm font-semibold text-slate-600 group-hover:text-brand-700 dark:text-slate-300 dark:group-hover:text-brand-300">
        {label}
      </span>
    </button>
  );
}

// --- Modals ---

function MaterialModal({ material, onCancel, onSaved }: { material: Material | null; onCancel: () => void; onSaved: (m: Material) => void; }) {
  const isEdit = material != null;
  const [name, setName] = useState(material?.name ?? "");
  const [category, setCategory] = useState(material?.category ?? "");
  const [unit, setUnit] = useState(material?.unit ?? "");
  const [price, setPrice] = useState(material?.unit_price ?? 0);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const payload = { name: name.trim(), category: category.trim(), unit: unit.trim(), unit_price: price };
      const res = isEdit ? await api.updateMaterial(material!.id, payload as any) : await api.createMaterial(payload as any);
      onSaved(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onClick={onCancel}>
      <form onSubmit={submit} onClick={e => e.stopPropagation()} className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
        <h2 className="mb-4 text-xl font-bold dark:text-white">{isEdit ? "Editar Insumo" : "Nuevo Insumo"}</h2>
        
        <div className="space-y-4">
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Nombre</span>
            <input required value={name} onChange={e => setName(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-600 dark:bg-slate-900 dark:text-white" />
          </label>
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Categoría</span>
            <input required value={category} onChange={e => setCategory(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-600 dark:bg-slate-900 dark:text-white" />
          </label>
          <div className="flex gap-4">
            <label className="block flex-1 text-sm">
              <span className="font-semibold text-slate-700 dark:text-slate-300">Unidad</span>
              <input required list="unit-suggestions" value={unit} onChange={e => setUnit(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-600 dark:bg-slate-900 dark:text-white" />
              <datalist id="unit-suggestions">{UNIT_SUGGESTIONS.map(u => <option key={u} value={u} />)}</datalist>
            </label>
            <label className="block flex-1 text-sm">
              <span className="font-semibold text-slate-700 dark:text-slate-300">Precio</span>
              <input type="number" step="any" min="0" required value={price} onChange={e => setPrice(parseFloat(e.target.value) || 0)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-600 dark:bg-slate-900 dark:text-white" />
            </label>
          </div>
        </div>

        {err && <p className="mt-4 text-sm text-red-600">{err}</p>}

        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onCancel} disabled={saving} className="rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700">Cancelar</button>
          <button type="submit" disabled={saving} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-md hover:bg-brand-700 disabled:opacity-50">Guardar</button>
        </div>
      </form>
    </div>
  );
}

function AssemblyModal({ assembly, allMaterials, onCancel, onSaved }: { assembly: Assembly | null; allMaterials: Material[]; onCancel: () => void; onSaved: (a: Assembly) => void; }) {
  const isEdit = assembly != null;
  const [name, setName] = useState(assembly?.name ?? "");
  const [appliesTo, setAppliesTo] = useState(assembly?.applies_to ?? "wall");
  const [dailyYield, setDailyYield] = useState(assembly?.daily_yield ?? 0.0);
  const [ams, setAms] = useState<AssemblyMaterialInput[]>(
    assembly?.assembly_materials.map(am => ({ material_id: am.material.id, consumption: am.consumption, waste_factor: am.waste_factor })) ?? []
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setErr(null);
    const payload: AssemblyCreatePayload = { name: name.trim(), applies_to: appliesTo, daily_yield: dailyYield, materials: ams };
    const req = isEdit ? api.updateAssembly(assembly!.id, payload) : api.createAssembly(payload);
    req.then(onSaved).catch(err => setErr(err.message)).finally(() => setSaving(false));
  }

  const base = baseUnitFor(appliesTo);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onClick={onCancel}>
      <form onSubmit={submit} onClick={e => e.stopPropagation()} className="flex max-h-[90vh] w-full max-w-2xl flex-col gap-4 overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
        <div>
          <h2 className="text-xl font-bold dark:text-white">{isEdit ? "Editar Sistema" : "Nuevo Sistema"}</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Un sistema es una receta: define qué insumos lleva y cuánto de cada uno por unidad del elemento (muro, viga, abertura, etc.).
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Nombre del sistema</span>
            <input required value={name} onChange={e => setName(e.target.value)} placeholder="Ej: Muro Ladrillo 18cm" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-600 dark:bg-slate-900 dark:text-white" />
          </label>
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Aplica a</span>
            <select value={appliesTo} onChange={e => setAppliesTo(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-600 dark:bg-slate-900 dark:text-white">
              {APPLIES_TO_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        </div>
        
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block text-sm">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Rendimiento diario (Gantt)</span>
            <input type="number" step="any" min="0" value={dailyYield} onChange={e => setDailyYield(parseFloat(e.target.value) || 0)} placeholder="Ej: 15" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-600 dark:bg-slate-900 dark:text-white" />
            <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
              Cuántos <strong>{base.unit}</strong> se ejecutan por día. Usado para estimar tiempos.
            </span>
          </label>
          <div className="block text-sm">
            <span className="font-semibold text-transparent select-none hidden sm:block">.</span>
            <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400 sm:mt-10">
              Los consumos se calcularán por <strong>{base.unit}</strong>.
            </span>
          </div>
        </div>

        <div className="mt-2">
          <div className="mb-2">
            <span className="font-semibold text-slate-700 dark:text-slate-300">Insumos asociados</span>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              {base.hint} Cantidad final = magnitud × consumo × (1 + merma).
            </p>
          </div>
          <div className="space-y-3">
            {ams.map((am, i) => {
              const mat = allMaterials.find(m => m.id === am.material_id);
              const matUnit = mat?.unit ?? "un";
              const mermaPct = Math.round(am.waste_factor * 10000) / 100;
              return (
                <div key={i} className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900">
                  <div className="flex items-center gap-2">
                    <select
                      value={am.material_id}
                      onChange={e => setAms(ams.map((x, idx) => idx === i ? {...x, material_id: parseInt(e.target.value)} : x))}
                      className="flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-white"
                    >
                      {allMaterials.map(m => <option key={m.id} value={m.id}>{m.name} ({m.unit})</option>)}
                    </select>
                    <button
                      type="button"
                      onClick={() => setAms(ams.filter((_, idx) => idx !== i))}
                      className="p-1.5 text-red-500 hover:text-red-700"
                      title="Quitar insumo"
                    >
                      <TrashIcon size={16}/>
                    </button>
                  </div>

                  <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="block text-xs">
                      <span className="font-semibold text-slate-700 dark:text-slate-300">Consumo</span>
                      <div className="mt-1 flex items-center gap-2">
                        <input
                          type="number"
                          step="any"
                          min="0"
                          value={am.consumption}
                          onChange={e => setAms(ams.map((x, idx) => idx === i ? {...x, consumption: parseFloat(e.target.value) || 0} : x))}
                          className="w-24 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-white"
                        />
                        <span className="text-slate-500 dark:text-slate-400">
                          {matUnit} / {base.unit}
                        </span>
                      </div>
                      <span className="mt-1 block text-[10px] text-slate-400">
                        Cuánto se usa por cada {base.unit}.
                      </span>
                    </label>

                    <label className="block text-xs">
                      <span className="font-semibold text-slate-700 dark:text-slate-300">Merma</span>
                      <div className="mt-1 flex items-center gap-2">
                        <input
                          type="number"
                          step="0.5"
                          min="0"
                          max="100"
                          value={mermaPct}
                          onChange={e => setAms(ams.map((x, idx) => idx === i ? {...x, waste_factor: (parseFloat(e.target.value) || 0) / 100} : x))}
                          className="w-20 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-white"
                        />
                        <span className="text-slate-500 dark:text-slate-400">%</span>
                      </div>
                      <span className="mt-1 block text-[10px] text-slate-400">
                        Desperdicio por cortes, roturas, etc.
                      </span>
                    </label>
                  </div>
                </div>
              );
            })}
            {ams.length === 0 && (
              <p className="rounded-lg border border-dashed border-slate-300 px-3 py-4 text-center text-xs italic text-slate-400 dark:border-slate-700">
                Aún no agregaste insumos a este sistema.
              </p>
            )}
            <button
              type="button"
              onClick={() => setAms([...ams, { material_id: allMaterials[0]?.id ?? 0, consumption: 1, waste_factor: 0.05 }])}
              className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-slate-300 px-3 py-2.5 text-sm font-semibold text-brand-600 transition hover:border-brand-400 hover:bg-brand-50 dark:border-slate-700 dark:text-brand-400 dark:hover:border-brand-500/60 dark:hover:bg-brand-500/5"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14"/><path d="M12 5v14"/>
              </svg>
              Agregar insumo
            </button>
          </div>
        </div>

        {err && <p className="mt-4 text-sm text-red-600">{err}</p>}

        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onCancel} disabled={saving} className="rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700">Cancelar</button>
          <button type="submit" disabled={saving} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-md hover:bg-brand-700 disabled:opacity-50">Guardar</button>
        </div>
      </form>
    </div>
  );
}

function DeleteModal({ title, message, onCancel, onConfirm }: { title: string; message: string; onCancel: () => void; onConfirm: () => Promise<void>; }) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setLoading(true); setErr(null);
    try { await onConfirm(); } catch (e) { setErr(e instanceof Error ? e.message : "Error"); setLoading(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onClick={loading ? undefined : onCancel}>
      <div onClick={e => e.stopPropagation()} className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
        <h3 className="text-lg font-bold text-slate-900 dark:text-white">{title}</h3>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{message}</p>
        {err && <p className="mt-4 text-sm text-red-600">{err}</p>}
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onCancel} disabled={loading} className="rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700">Cancelar</button>
          <button onClick={submit} disabled={loading} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-md hover:bg-red-700 disabled:opacity-50">Eliminar</button>
        </div>
      </div>
    </div>
  );
}

function EditIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

function TrashIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  );
}
