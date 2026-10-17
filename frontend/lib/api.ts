const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type BuildingType = "casa" | "edificio" | "condominio" | "comercial";

export type Project = {
  id: number;
  name: string;
  description: string | null;
  status: string;
  wizard_step: number;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  city: string | null;
  country: string | null;
  building_type: BuildingType | null;
  building_info: Record<string, number> | null;
  allow_training_data: boolean;
  created_at: string;
};

export type User = {
  id: number;
  email: string;
  role: string;
  is_superadmin: boolean;
  created_at: string;
};

export type LocationPayload = {
  address: string;
  latitude: number;
  longitude: number;
  city?: string | null;
  country?: string | null;
};

export type BuildingInfoPayload = {
  building_type: BuildingType;
  building_info: Record<string, number>;
};

export type PageOverride = "recommended" | "rejected";

export type PageRole = "walls" | "openings" | "rooms" | "beams" | "roofs" | "columns" | "riostras" | "cloacas" | "electricidad" | "escaleras" | "cortes";

export type IfcQualityCheck = {
  id: string;
  ok: boolean;
  label: string;
};

export type IfcQuality = {
  level: "green" | "yellow" | "red";
  schema?: string | null;
  has_spaces?: boolean;
  has_base_quantities?: boolean;
  n_storeys?: number;
  n_walls?: number;
  n_elements?: number;
  warnings?: string[];
  checks?: IfcQualityCheck[];
};

export type Plan = {
  id: number;
  project_id: number;
  original_filename: string;
  page: number;
  page_count: number | null;
  status: string;
  dpi: number | null;
  scale_px_per_m: number | null;
  scale_source: string | null;
  page_scales: Record<string, number> | null;
  deleted_pages: number[] | null;
  page_overrides: Record<string, PageOverride> | null;
  page_roles: Record<string, PageRole[]> | null;
  error_message?: string | null;
  parse_progress?: number | null;
  parse_stage?: string | null;
  ifc_quality?: IfcQuality | null;
  created_at: string;
};

export type Material = {
  id: number;
  name: string;
  category: string;
  unit: string;
  unit_price: number;
};

export type MaterialCreatePayload = {
  name: string;
  category: string;
  unit: string;
  unit_price: number;
};

export type MaterialUpdatePayload = Partial<MaterialCreatePayload>;

export type AssemblyMaterial = {
  id: number;
  assembly_id: number;
  material: Material;
  consumption: number;
  waste_factor: number;
};

export type Assembly = {
  id: number;
  name: string;
  applies_to: string;
  daily_yield: number | null;
  assembly_materials: AssemblyMaterial[];
};

export type AssemblyMaterialInput = {
  material_id: number;
  consumption: number;
  waste_factor: number;
};

export type AssemblyCreatePayload = {
  name: string;
  applies_to: string;
  daily_yield: number | null;
  assembly_materials: AssemblyMaterialInput[];
};

export type AssemblyUpdatePayload = {
  name?: string;
  applies_to?: string;
  daily_yield?: number | null;
  assembly_materials?: AssemblyMaterialInput[];
};

// ---- Cronograma + curva de inversión ----

export type WorkTaskAssignee = { user_id: number; email: string };

export type ScheduleTask = {
  assembly: string;
  stage: string;
  stage_order: number;
  quantity: number;
  unit: string;
  duration_days: number;
  cost: number;
  start_date: string;
  end_date: string;
  // Presentes cuando vienen del plan persistido (no del cálculo al vuelo).
  id?: number;
  depends_on?: number[];
  source?: string;
  assembly_id?: number | null;
  level?: string | null;
  level_order?: number | null;
  status?: string;      // pending|in_progress|in_review|completed|blocked|cancelled
  priority?: string;    // low|medium|high|critical
  description?: string | null;
  assignees?: WorkTaskAssignee[];
};

export type WorkTaskHistoryRow = {
  id: number; field: string; old_value: string | null; new_value: string | null;
  note: string | null; author_email: string | null; created_at: string | null;
};

export type ScheduleStage = {
  stage: string;
  stage_order: number;
  start_date: string;
  end_date: string;
  cost: number;
};

export type ScheduleResponse = {
  start_date: string;
  end_date: string;
  total_days: number;
  total_cost: number;
  stages: ScheduleStage[];
  tasks: ScheduleTask[];
};

export type CashflowPoint = {
  month: string;
  amount: number;
  accumulated: number;
};

// ---- Plan de obra persistido (módulo Obra) ----

export type WorkPlanData = ScheduleResponse & {
  plan_id: number;
  version: number;
  status: "draft" | "active" | "superseded" | "closed";
  frozen_at: string | null;
  crews: number;
  overlap_pct: number;
  price_snapshot_count?: number;
  hide_money?: boolean;   // capataz/comitente: el backend ya quitó los importes
  progress_migration?: {
    migrated_tasks: number;
    unmatched_old: number;
    new_tasks: number;
    entries_moved: number;
    costs_moved: number;
    capped_tasks: number;
  };
};

// Rol de permiso del usuario DENTRO de un proyecto (distinto del oficio).
export type ProjectRole = "admin" | "jefe_obra" | "capataz" | "comitente" | "none";

export type ProjectMember = {
  user_id: number;
  email: string | null;
  role: "jefe_obra" | "capataz" | "comitente";
  role_label: string;
  job_roles: string[];
};

export type ProjectMembersState = {
  members: ProjectMember[];
  my_role: ProjectRole;
  can_manage_members: boolean;
};

export type WorkPlanComputeDiffRow = {
  name: string;
  assembly_id: number | null;
  level: string | null;
  unit: string | null;
  qty_plan: number | null;
  qty_compute: number | null;
  cost_plan: number | null;
  cost_compute: number | null;
  duration_plan: number | null;
  duration_compute: number | null;
  source: string | null;
  status: "same" | "changed" | "added" | "removed";
};

export type WorkPlanComputeDiff = {
  plan_id: number | null;
  plan_status: string | null;
  plan_version: number | null;
  plan_total: number;
  compute_total: number;
  delta_cost: number;
  n_changed: number;
  tasks: WorkPlanComputeDiffRow[];
};

export type ProjectChangesPriceRow = {
  material_id: number;
  name: string;
  unit: string | null;
  price_baseline: number;
  price_live: number | null;
  delta: number | null;
  delta_pct: number | null;
  status: "same" | "changed" | "missing_live";
};

export type ProjectChangesPrices = {
  baseline_plan_id: number | null;
  baseline_version: number | null;
  frozen_at: string | null;
  n_changed: number;
  materials: ProjectChangesPriceRow[];
};

export type ProjectChangesVersion = {
  plan_id: number;
  version: number;
  status: string;
  frozen_at: string | null;
  created_at: string | null;
  total_cost: number;
  task_count: number;
};

export type ProjectChanges = {
  summary: {
    budget_direct: number | null;
    plan_total: number | null;
    compute_total: number | null;
    n_compute_changed: number;
    n_price_changed: number;
    active_version: number | null;
    draft_version: number | null;
  };
  compute: WorkPlanComputeDiff;
  prices: ProjectChangesPrices;
  versions: ProjectChangesVersion[];
};

export type WorkPlanVersion = {
  plan_id: number; version: number; status: string;
  frozen_at: string | null; created_at: string | null;
};

export type WorkPlanState = {
  plan: WorkPlanData | null;
  my_role?: ProjectRole;
  can_view_financials?: boolean;
  can_edit_plan?: boolean;
  can_register_progress?: boolean;
  versions: WorkPlanVersion[];
};

export type TaskProgress = {
  task_id: number; name: string; stage: string; stage_order: number;
  qty_planned: number; qty_done: number; unit: string; pct: number;
  planned_start: string; planned_end: string; projected_end: string;
  delay_days: number; real_yield: number | null; cost_planned: number;
  status: string; n_entries: number;
};

export type WorkProgress = {
  plan_id: number; version: number; as_of: string;
  tasks: TaskProgress[];
  stages: { stage: string; stage_order: number; pct: number; ev: number;
            cost_planned: number; delay_days: number; n_tareas: number }[];
  totals: { pct_fisico: number; ev: number; pv: number; bac: number;
            spi: number | null; delay_days: number;
            planned_end: string; projected_end: string };
};

export type ProgressEntryRow = {
  id: number; date: string; qty_done: number; note: string | null;
  created_at: string | null;
};

export type WorkCost = {
  plan_id: number; version: number; as_of: string; n_costs: number;
  evm: {
    bac: number; pv: number; ev: number; ac: number; cv: number;
    cpi: number | null; spi: number | null; eac: number;
    over_budget_at_completion: number;
  };
  inflation: null | {
    ipc_base: number; ipc_now: number; ipc_base_date: string; ipc_now_date: string;
    accum_pct: number; ev_now: number; inflation_gap: number; real_variance: number;
  };
  by_kind: Record<string, number>;
  stages: { stage: string; planned: number; real: number }[];
  curve: { month: string; plan: number; real?: number; projected?: number }[];
};

export type ActualCostRow = {
  id: number; date: string; amount: number; kind: string;
  work_task_id: number | null; stage: string | null; note: string | null;
};

// ---- Admin / Team ----

export type JobRole = {
  id: number;
  name: string;
  is_default?: boolean;
};

export type OrgUser = {
  id: number;
  email: string;
  role: string;
  is_superadmin: boolean;
  created_at: string;
  job_roles?: JobRole[];
};

export type Organization = {
  id: number;
  name: string;
  subscription_status: string;
  stripe_customer_id: string | null;
  created_at: string;
  updated_at: string;
};

export type OrganizationListItem = Organization & {
  user_count: number;
  project_count: number;
};

export type OrganizationDetail = Organization & {
  users: OrgUser[];
};

export type OrganizationCreatePayload = {
  name: string;
  subscription_status?: string;
  admin_email?: string;
  admin_password?: string;
};

export type OrganizationUpdatePayload = {
  name?: string;
  subscription_status?: string;
};

export type AdminUserCreatePayload = {
  email: string;
  password: string;
  role: "admin" | "member";
  job_role_ids?: number[];
};

export type AdminUserUpdatePayload = {
  email?: string;
  password?: string;
  role?: "admin" | "member";
  job_role_ids?: number[];
};

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("scalistai_token");
}

/** Error de API con status HTTP (para 401/402/403 sin parsear el mensaje). */
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isUnauthorized(err: unknown): boolean {
  if (err instanceof ApiError) return err.status === 401;
  return err instanceof Error && /\b401\b/.test(err.message);
}

export function isForbidden(err: unknown): boolean {
  if (err instanceof ApiError) return err.status === 403 || err.status === 402;
  return err instanceof Error && /\b40[23]\b/.test(err.message);
}

function parseFastApiDetail(raw: string, status: number): string {
  if (!raw) return `HTTP ${status}`;
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed?.detail === "string") return parsed.detail;
    if (Array.isArray(parsed?.detail)) {
      const parts = parsed.detail.map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.join(".")
            : "";
          const msg = String((item as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return JSON.stringify(item);
      });
      return parts.filter(Boolean).join("; ") || `HTTP ${status}`;
    }
    if (parsed?.detail != null) return JSON.stringify(parsed.detail);
  } catch {
    /* body no era JSON */
  }
  return raw;
}

/** fetch al backend con el token; si la respuesta no es OK lanza ApiError
 *  (y ante un 401 limpia la sesión y manda al login). */
async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Los body string son JSON; FormData / URLSearchParams ponen su propio Content-Type.
  if (typeof init.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const raw = await res.text();
    const message = parseFastApiDetail(raw, res.status);
    // Sesión inválida/expirada: limpiar token y volver al login (salvo el propio login).
    if (
      res.status === 401 &&
      typeof window !== "undefined" &&
      !path.includes("/auth/login")
    ) {
      window.localStorage.removeItem("scalistai_token");
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    throw new ApiError(message, res.status);
  }
  return res;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(path, init);
  // DELETE / acciones que responden 204 No Content: no hay body que parsear.
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

/** Igual que request() pero devuelve el archivo (Excel, PDF, imagen). */
async function requestBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  return (await send(path, init)).blob();
}

/** Dispara la descarga de un archivo en el navegador. */
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// --- Reglas de cómputo (IFC → productos del presupuesto del proveedor) ---
export type RuleUnit = "kg" | "m3" | "m2" | "m" | "l" | "u";
export type RuleMode = "fixed" | "brick_dims" | "rebar";
export type RuleInput = {
  measure: string;
  label: string;
  keywords: string[];
  exclude_keywords: string[];
  unit: RuleUnit;
  factor: number;
  mode: RuleMode;
  waste_pct: number;
  notes: string | null;
};
export type Rule = RuleInput & { id: number; position: number };
export type RuleSet = {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  /** Juego global "Estándar Argentina": solo lo edita el superadmin. */
  is_system: boolean;
  organization_id: number | null;
  created_at: string;
  updated_at: string;
  rules: Rule[];
};
export type RuleSetsMeta = {
  measures: { key: string; label: string; unit: string }[];
  units: RuleUnit[];
  modes: { key: RuleMode; label: string }[];
};

// --- Presupuesto del proveedor en el proyecto (paso "Precios") ---
export type Presentation = { amount: number; unit: string; attrs: { diameter_mm?: number; dims?: number[] } };
export type PriceLine = {
  row: number;
  code: string | null;
  description: string;
  quantity: number;
  unit_price: number | null;
  total: number | null;
  unit_price_net: number | null;
  presentation: Presentation;
  patched?: boolean;
};
export type PriceLineRef = Pick<PriceLine, "row" | "code" | "description" | "unit_price_net" | "presentation">;
export type BudgetItemStatus = "ok" | "sin_precio" | "sin_medida" | "unidad_incompatible" | "regla_invalida";
export type BudgetItem = {
  key: string;
  rule_id: number | null;
  label: string;
  measure: string;
  measure_label: string;
  measure_unit: string;
  measure_value: number;
  unit: string;
  waste_pct: number;
  notes: string | null;
  factor: number;
  quantity: number | null;
  line: PriceLineRef | null;
  per_sale?: number;
  units_to_buy: number | null;
  subtotal: number | null;
  alternatives: PriceLineRef[];
  status: BudgetItemStatus;
  manual?: boolean;
  diameter_mm?: number;
};
export type ShoppingRow = PriceLineRef & { units: number; units_to_buy: number; subtotal: number; items: string[] };
export type RuleBudget = {
  items: BudgetItem[];
  shopping_list: ShoppingRow[];
  unused_lines: PriceLineRef[];
  totals: { net: number; iva: number; total: number; iva_rate: number };
  counts: { ok: number; sin_precio: number; sin_medida: number };
};
export type ModelMeasures = {
  measures: { key: string; label: string; unit: string; value: number; count: number }[];
  rebar_by_diameter: { diameter_mm: number; kg: number }[];
  warnings: string[];
};
export type IvaMode = "auto" | "included" | "excluded";
export type ProjectPriceList = {
  source: "pdf" | "excel";
  filename: string;
  supplier: string | null;
  document_date: string | null;
  number_format: string;
  iva: { included: boolean; rate: number; method: string };
  totals: { lines_sum: number; document_total: number | null; check: "ok" | "mismatch" | null };
  lines: PriceLine[];
  warnings: string[];
  iva_mode: IvaMode;
  overrides: Record<string, number | null>;
  line_patches: Record<string, { amount: number; unit: string }>;
  updated_at: string | null;
};
export type ProjectBudgetView = {
  rule_set: { id: number; name: string } | null;
  model_status: "ready" | "processing" | "error" | "missing";
  price_list: ProjectPriceList | null;
  measures: ModelMeasures | null;
  budget: RuleBudget | null;
};

// --- Motor de Inteligencia de Costos ---
export type ForecastResult = {
  cost_today: number;
  projected_cost: number;
  variation: number;
  horizon_months: number;
  monthly_rate: number;
  method: string;
};
export type CostSettings = { overhead_pct: number; profit_pct: number; iva_pct: number };
export type PriceSeriesPoint = { date: string; price: number; source: string };
export type PriceSeriesProduct = {
  id: number;
  name: string;
  category: string;
  unit: string;
  points: PriceSeriesPoint[];
  first_price: number;
  last_price: number;
  change_pct: number | null;
  horizon_months: number;
  projected_price: number;
  forecast_rate: number;
  forecast_method: "serie_propia" | "ipc" | "sin_dato";
  forecast_variation_pct: number;
  ipc_monthly_rate: number | null;
  beats_inflation: boolean | null;
};

export type BudgetCategory = { name: string; total: number; pct: number; per_m2: number | null; parametric?: boolean };
export type ParametricRubro = { key: string; label: string; pct: number };
export type BudgetTakeoff = {
  wall_ml: number; wall_m2: number; openings: number; doors: number; windows: number;
  columns: number; beams_ml: number; roof_m2: number; cloaca_ml: number;
  electricidad_ml: number; rooms: number; floor_m2: number;
  sanitarios?: number; bocas_electricas?: number; escaleras?: number;
  pilotes?: number; zapatas_ml?: number;
  armaduras?: number; armadura_kg?: number;
  equipos_hvac?: number; cielorrasos?: number;
};
export type SalePriceBreakdown = {
  direct: number; overhead: number; profit: number; iva: number; total: number;
};
export type ProjectBudgetSummary = {
  plan_id: number; project_name: string; area_m2: number; area_estimated?: boolean;
  materials_total: number; labor_total: number; labor_hours: number; duration_days: number;
  obra_gris_direct?: number; parametric_total?: number;
  direct_cost: number; sale_price: number; cost_per_m2: number | null;
  breakdown: SalePriceBreakdown;
  categories: BudgetCategory[]; takeoff: BudgetTakeoff;
};

export const api = {
  // Sin registro público: las cuentas las crea el admin (panel / equipo).

  login: async (email: string, password: string) => {
    let data: { access_token: string };
    try {
      data = await request<{ access_token: string }>("/api/v1/auth/login", {
        method: "POST",
        body: new URLSearchParams({ username: email, password }),
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) throw new Error("Credenciales inválidas");
      throw e;
    }
    window.localStorage.setItem("scalistai_token", data.access_token);
    return data;
  },

  logout: () => window.localStorage.removeItem("scalistai_token"),

  listProjects: () => request<Project[]>("/api/v1/projects"),
  createProject: (name: string, description?: string | null) =>
    request<Project>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify({ name, description: description?.trim() || null }),
    }),
  getProject: (id: number) => request<Project>(`/api/v1/projects/${id}`),
  updateProject: (id: number, patch: { name?: string; description?: string | null }) =>
    request<Project>(`/api/v1/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  updateProjectLocation: (id: number, payload: LocationPayload) =>
    request<Project>(`/api/v1/projects/${id}/location`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  updateProjectBuildingInfo: (id: number, payload: BuildingInfoPayload) =>
    request<Project>(`/api/v1/projects/${id}/building-info`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  activateProject: (id: number) =>
    request<Project>(`/api/v1/projects/${id}/activate`, {
      method: "POST",
      body: "{}",
    }),
  async getMe(): Promise<User> {
    return request<User>("/api/v1/auth/me");
  },

  async updateProfile(payload: { email?: string; password?: string }): Promise<User> {
    return request<User>("/api/v1/auth/profile", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  deleteProject: (id: number) =>
    request<void>(`/api/v1/projects/${id}`, { method: "DELETE" }),

  listPlans: (projectId: number) =>
    request<Plan[]>(`/api/v1/projects/${projectId}/plans`),

  // Motor de Inteligencia de Costos
  /** Proyecta un monto (p.ej. direct_cost del budget-summary) con IPC. */
  forecastCostByAmount: (amount: number, horizonMonths: number) =>
    request<ForecastResult>("/api/v1/forecast", {
      method: "POST",
      body: JSON.stringify({ amount, horizon_months: horizonMonths }),
    }),
  getCostSettings: () => request<CostSettings>("/api/v1/cost-settings"),
  getPriceSeries: () => request<PriceSeriesProduct[]>("/api/v1/price-series"),
  getBudgetSummary: (planId: number) =>
    request<ProjectBudgetSummary>(`/api/v1/plans/${planId}/budget-summary`),
  /** Excel del presupuesto completo (obra gris + paramétricos). Misma fuente que la pantalla. */
  downloadBudgetXlsx: async (planId: number, projectName?: string) => {
    const blob = await requestBlob(`/api/v1/plans/${planId}/budget-export/xlsx`);
    const safe = (projectName || `plan_${planId}`).replace(/[^\w\-]+/g, "_").slice(0, 60);
    saveBlob(blob, `presupuesto_${safe}.xlsx`);
  },
  updateCostSettings: (patch: Partial<CostSettings>) =>
    request<CostSettings>("/api/v1/cost-settings", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  getParametricRubros: () => request<ParametricRubro[]>("/api/v1/parametric-rubros"),
  updateParametricRubros: (rubros: ParametricRubro[]) =>
    request<ParametricRubro[]>("/api/v1/parametric-rubros", {
      method: "PUT",
      body: JSON.stringify({ rubros }),
    }),

  uploadPlan: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<Plan>(
      `/api/v1/projects/${projectId}/plans`,
      { method: "POST", body: formData },
    );
  },

  // ----- Materiales (catálogo) -----
  listMaterials: () => request<Material[]>("/api/v1/materials/"),

  createMaterial: (payload: MaterialCreatePayload) =>
    request<Material>("/api/v1/materials/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateMaterial: (id: number, payload: MaterialUpdatePayload) =>
    request<Material>(`/api/v1/materials/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteMaterial: (id: number) =>
    request<void>(`/api/v1/materials/${id}`, { method: "DELETE" }),

  // ----- Assemblies (Sistemas Constructivos) -----
  listAssemblies: () => request<Assembly[]>("/api/v1/assemblies/"),

  createAssembly: (payload: AssemblyCreatePayload) =>
    request<Assembly>("/api/v1/assemblies/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateAssembly: (id: number, payload: AssemblyUpdatePayload) =>
    request<Assembly>(`/api/v1/assemblies/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteAssembly: (id: number) =>
    request<void>(`/api/v1/assemblies/${id}`, { method: "DELETE" }),

  // ----- Equipo del proyecto (roles de permiso) -----
  getProjectMembers: (projectId: number) =>
    request<ProjectMembersState>(`/api/v1/projects/${projectId}/members`),
  upsertProjectMember: (projectId: number, userId: number, role: string) =>
    request<ProjectMember>(`/api/v1/projects/${projectId}/members`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, role }),
    }),
  removeProjectMember: (projectId: number, userId: number) =>
    request<void>(`/api/v1/projects/${projectId}/members/${userId}`, { method: "DELETE" }),

  // ----- Plan de obra persistido (módulo Obra) -----
  getWorkPlan: (projectId: number) =>
    request<WorkPlanState>(`/api/v1/projects/${projectId}/work-plan`),
  getWorkPlanComputeDiff: (projectId: number) =>
    request<WorkPlanComputeDiff>(`/api/v1/projects/${projectId}/work-plan/compute-diff`),
  getProjectChanges: (projectId: number) =>
    request<ProjectChanges>(`/api/v1/projects/${projectId}/changes`),
  createWorkPlanDraft: (projectId: number, opts: { startDate?: string; crews?: number; overlapPct?: number }) =>
    request<WorkPlanData>(`/api/v1/projects/${projectId}/work-plan/draft`, {
      method: "POST",
      body: JSON.stringify({
        start_date: opts.startDate, crews: opts.crews ?? 1,
        overlap_pct: opts.overlapPct ?? 0,
      }),
    }),
  freezeWorkPlan: (planId: number) =>
    request<WorkPlanData>(`/api/v1/work-plans/${planId}/freeze`, { method: "POST" }),
  rebaselineWorkPlan: (projectId: number) =>
    request<WorkPlanData>(`/api/v1/projects/${projectId}/work-plan/rebaseline`, { method: "POST" }),
  getWorkProgress: (projectId: number) =>
    request<WorkProgress>(`/api/v1/projects/${projectId}/work-progress`),
  addProgress: (taskId: number, data: { qtyDone: number; date?: string; note?: string }) =>
    request<WorkProgress>(`/api/v1/work-tasks/${taskId}/progress`, {
      method: "POST",
      body: JSON.stringify({ qty_done: data.qtyDone, date: data.date, note: data.note }),
    }),
  listProgress: (taskId: number) =>
    request<ProgressEntryRow[]>(`/api/v1/work-tasks/${taskId}/progress`),
  deleteProgress: (entryId: number) =>
    request<void>(`/api/v1/work-progress/${entryId}`, { method: "DELETE" }),
  getWorkCost: (projectId: number) =>
    request<WorkCost>(`/api/v1/projects/${projectId}/work-cost`),
  listActualCosts: (projectId: number) =>
    request<ActualCostRow[]>(`/api/v1/projects/${projectId}/actual-costs`),
  addActualCost: (projectId: number, data: { amount: number; kind: string; date?: string; stage?: string; workTaskId?: number; note?: string }) =>
    request<WorkCost>(`/api/v1/projects/${projectId}/actual-costs`, {
      method: "POST",
      body: JSON.stringify({
        amount: data.amount, kind: data.kind, date: data.date,
        stage: data.stage, work_task_id: data.workTaskId, note: data.note,
      }),
    }),
  deleteActualCost: (costId: number) =>
    request<void>(`/api/v1/actual-costs/${costId}`, { method: "DELETE" }),

  // ----- Cronograma (Gantt) + curva de inversión -----
  getSchedule: (projectId: number, opts?: { startDate?: string; crews?: number; overlapPct?: number }) => {
    const q = new URLSearchParams();
    if (opts?.startDate) q.set("start_date", opts.startDate);
    if (opts?.crews) q.set("crews", String(opts.crews));
    if (opts?.overlapPct) q.set("overlap_pct", String(opts.overlapPct));
    const qs = q.toString() ? `?${q.toString()}` : "";
    return request<ScheduleResponse>(`/api/v1/projects/${projectId}/schedule${qs}`);
  },

  // ---- Admin (superadmin) ----
  listOrganizations: () => request<OrganizationListItem[]>(`/api/v1/admin/organizations`),
  getOrganization: (id: number) =>
    request<OrganizationDetail>(`/api/v1/admin/organizations/${id}`),
  createOrganization: (payload: OrganizationCreatePayload) =>
    request<OrganizationDetail>(`/api/v1/admin/organizations`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateOrganization: (id: number, payload: OrganizationUpdatePayload) =>
    request<OrganizationDetail>(`/api/v1/admin/organizations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteOrganization: (id: number) =>
    request<void>(`/api/v1/admin/organizations/${id}`, { method: "DELETE" }),

  createOrgUser: (orgId: number, payload: AdminUserCreatePayload) =>
    request<OrgUser>(`/api/v1/admin/organizations/${orgId}/users`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateOrgUser: (userId: number, payload: AdminUserUpdatePayload) =>
    request<OrgUser>(`/api/v1/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteOrgUser: (userId: number) =>
    request<void>(`/api/v1/admin/users/${userId}`, { method: "DELETE" }),

  // ---- Presupuesto del proveedor del proyecto ----
  getProjectPriceList: (projectId: number) =>
    request<ProjectBudgetView>(`/api/v1/projects/${projectId}/price-list`),
  uploadProjectPriceList: (projectId: number, file: File, ruleSetId?: number | null) => {
    const fd = new FormData();
    fd.append("file", file);
    if (ruleSetId != null) fd.append("rule_set_id", String(ruleSetId));
    return request<ProjectBudgetView>(`/api/v1/projects/${projectId}/price-list`, {
      method: "POST",
      body: fd,
    });
  },
  patchProjectPriceList: (
    projectId: number,
    payload: {
      rule_set_id?: number;
      iva_mode?: IvaMode;
      overrides?: Record<string, number | null>;
      line_patches?: Record<string, { amount: number; unit: string }>;
    },
  ) =>
    request<ProjectBudgetView>(`/api/v1/projects/${projectId}/price-list`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteProjectPriceList: (projectId: number) =>
    request<void>(`/api/v1/projects/${projectId}/price-list`, { method: "DELETE" }),
  downloadProjectBudgetXlsx: async (projectId: number, projectName?: string) => {
    const blob = await requestBlob(`/api/v1/projects/${projectId}/price-list/export.xlsx`);
    const safe = (projectName || `proyecto_${projectId}`).replace(/[^\w\-]+/g, "_").slice(0, 60);
    saveBlob(blob, `presupuesto_${safe}.xlsx`);
  },

  // ---- Reglas de cómputo ----
  getRuleSetsMeta: () => request<RuleSetsMeta>(`/api/v1/rule-sets/meta`),
  listRuleSets: () => request<RuleSet[]>(`/api/v1/rule-sets`),
  getRuleSet: (id: number) => request<RuleSet>(`/api/v1/rule-sets/${id}`),
  createRuleSet: (payload: { name: string; description?: string | null; copy_from_id?: number | null }) =>
    request<RuleSet>(`/api/v1/rule-sets`, { method: "POST", body: JSON.stringify(payload) }),
  updateRuleSet: (
    id: number,
    payload: { name: string; description: string | null; is_default: boolean; rules: RuleInput[] },
  ) => request<RuleSet>(`/api/v1/rule-sets/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteRuleSet: (id: number) =>
    request<void>(`/api/v1/rule-sets/${id}`, { method: "DELETE" }),

  // ---- Team (org admin / member) ----
  listTeam: () => request<OrgUser[]>(`/api/v1/team/users`),
  listTeamJobRoles: () => request<JobRole[]>(`/api/v1/team/job-roles`),
  createTeamJobRole: (name: string) =>
    request<JobRole>(`/api/v1/team/job-roles`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  listOrgJobRoles: (orgId: number) =>
    request<JobRole[]>(`/api/v1/admin/organizations/${orgId}/job-roles`),
  createOrgJobRole: (orgId: number, name: string) =>
    request<JobRole>(`/api/v1/admin/organizations/${orgId}/job-roles`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  createTeamUser: (payload: AdminUserCreatePayload) =>
    request<OrgUser>(`/api/v1/team/users`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateTeamUser: (userId: number, payload: AdminUserUpdatePayload) =>
    request<OrgUser>(`/api/v1/team/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteTeamUser: (userId: number) =>
    request<void>(`/api/v1/team/users/${userId}`, { method: "DELETE" }),

  async uploadMaterialsJson(items: any[]): Promise<{imported: number, updated: number}> {
    return request<{imported: number, updated: number}>("/api/v1/materials/import-json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(items),
    });
  },
  updateWorkTask: (taskId: number, payload: {
    name?: string; planned_start?: string; duration_days?: number; depends_on?: number[];
    status?: string; priority?: string; assignee_ids?: number[];
    description?: string | null; note?: string;
  }) =>
    request<WorkPlanData>(`/api/v1/work-tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  createWorkTask: (planId: number, payload: {
    name: string; stage?: string; stage_order?: number; planned_start?: string;
    duration_days?: number; unit?: string; qty_planned?: number; cost_planned?: number;
    depends_on?: number[]; priority?: string; status?: string;
    assignee_ids?: number[]; description?: string | null; note?: string;
  }) =>
    request<WorkPlanData>(`/api/v1/work-plans/${planId}/work-tasks`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getTaskHistory: (taskId: number) =>
    request<WorkTaskHistoryRow[]>(`/api/v1/work-tasks/${taskId}/history`),
  deleteWorkTask: (taskId: number) =>
    request<void>(`/api/v1/work-tasks/${taskId}`, { method: "DELETE" }),
  parseInvoice: (projectId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{
      ok: boolean; reason?: string;
      amount: number | null; date: string | null; vendor: string | null; cuit: string | null;
      amount_candidates: number[]; date_candidates: string[]; note?: string;
    }>(`/api/v1/projects/${projectId}/invoices/parse`, { method: "POST", body: form });
  },
  // Descarga directa del reporte PDF al disco del usuario (sin generar un link).
  // audience="comitente" arma la versión sin financieros, para reenviarla vos
  // mismo (mail/WhatsApp) sin exponer una URL pública.
  downloadWorkReport: async (projectId: number, projectName?: string, audience: "interno" | "comitente" = "interno") => {
    const qs = audience === "comitente" ? "?audience=comitente" : "";
    const blob = await requestBlob(`/api/v1/projects/${projectId}/work-report.pdf${qs}`);
    const safe = (projectName || `proyecto_${projectId}`).replace(/[^a-zA-Z0-9-_]/g, "_").slice(0, 60);
    saveBlob(blob, `obra_${safe}${audience === "comitente" ? "_comitente" : ""}.pdf`);
  },
};

