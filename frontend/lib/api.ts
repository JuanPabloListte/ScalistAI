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

export type TrainingStats = {
  total_samples: number;
  total_batches: number;
  plans_contributing: number;
  projects_contributing: number;
  latest_snapshot_at: string | null;
  ready_to_train: boolean;
  recommended_min_samples: number;
};

export type User = {
  id: number;
  email: string;
  role: string;
  is_superadmin: boolean;
  created_at: string;
};

export type TrainingStatusResponse = {
  status: {
    status: "idle" | "running" | "success" | "failed";
    mode?: "train" | "procedural";
    current_epoch: number;
    total_epochs: number;
    progress_percent: number;
    train_loss: number | null;
    val_loss: number | null;
    holdout_miou: number | null;
    error: string | null;
    started_at: string | null;
    completed_at: string | null;
    is_initial: boolean;
    logs_count: number;
  };
  logs: string[];
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

export type AiStage = "pending" | "running" | "done" | "failed";

export type AiStatus = {
  scales: AiStage;
  walls: AiStage;
  rooms: AiStage;
  openings: AiStage;
  columns: AiStage;
  beams: AiStage;
  roofs: AiStage;
  ml: AiStage;
  started_at: number | null;
};

export type MlModelStatus = {
  available: boolean;
  enabled: boolean;
  model_path: string;
  model_exists: boolean;
  model_loaded: boolean;
  model_size_mb: number | null;
  device: string | null;
  model_hash: string | null;
  active_version: number | null;
  active_holdout_miou: number | null;
  active_created_at: string | null;
};

export type PageOverride = "recommended" | "rejected";

export type PageRole = "walls" | "openings" | "rooms" | "beams" | "roofs" | "columns" | "riostras" | "cloacas" | "electricidad" | "escaleras" | "cortes";

export type PageClassification = {
  page: number;
  view_type: "planta" | "corte" | "planilla" | "estructura" | "instalacion" | "techos" | "otro";
  suggested_roles: PageRole[];
  reason: string;
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
  created_at: string;
};

export type PageRecommendation = {
  page: number;
  score: number;
  recommended: boolean;
  reason: string;
  override: PageOverride | null;
};

export type ElementType = "wall" | "room" | "opening" | "beam" | "roof" | "column" | "riostra" | "cloaca" | "electricidad" | "escalera";

export type DxfLayer = {
  name: string;
  color_rgb: [number, number, number];
  entity_count: number;
  suggested_type: ElementType | null;
};

export type DxfInfo = {
  layers: DxfLayer[];
  width_units: number;
  height_units: number;
  suggested_unit: "mm" | "cm" | "m";
  overview: {
    /** Marco del contenido en unidades de dibujo: [x1, y1, x2, y2] (y crece hacia arriba) */
    bounds: [number, number, number, number];
    /** Recortes ya aplicados (re-edición) */
    regions: number[][];
    /** Tipo de cada recorte, paralelo a regions: "planta" | "corte" */
    region_types: DxfRegionType[];
  };
};

export type DxfRegionType = "planta" | "corte";

export type ElementGeometry = {
  points: number[]; // flat [x1, y1, x2, y2, ...]
  label?: string;
  subtype?: string;
};

export type MaterialYield = {
  id: number;
  material_id: number;
  applies_to: string;
  consumption: number;
  waste_factor: number;
  unit_price: number;
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

export type DetectedElement = {
  id: number;
  plan_id: number;
  page: number;
  type: ElementType;
  geometry: ElementGeometry;
  length_m: number | null;
  area_m2: number | null;
  height_m: number | null;
  source: "manual" | "ai" | "ai_ml" | "dxf" | "llm";
  is_candidate: boolean;
  confidence: number;
  materials?: any[];
  created_at: string;
  updated_at: string;
  assemblies: Assembly[];
};

export type ElementCreatePayload = {
  page: number;
  type: ElementType;
  geometry: ElementGeometry;
  length_m?: number | null;
  area_m2?: number | null;
  height_m?: number | null;
  source?: "manual" | "ai";
};

export type ElementUpdatePayload = {
  geometry?: ElementGeometry;
  length_m?: number | null;
  area_m2?: number | null;
  height_m?: number | null;
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
  materials: {
    material_id: number;
    consumption: number;
    waste_factor: number;
  }[];
};

export type AssemblyUpdatePayload = {
  name?: string;
  applies_to?: string;
  assembly_materials?: AssemblyMaterialInput[];
};

export type MaterialSummaryItem = {
  material: Material;
  quantity: number;
  unit: string;
  unit_price: number;
  subtotal: number;
};

// ---- Admin / Team ----

export type OrgUser = {
  id: number;
  email: string;
  role: string;
  is_superadmin: boolean;
  created_at: string;
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
};

export type AdminUserUpdatePayload = {
  email?: string;
  password?: string;
  role?: "admin" | "member";
};

export type AiConfigRead = {
  ai_provider: string;
  ai_model_name: string | null;
  has_api_key: boolean;
};

export type AiConfigUpdate = {
  ai_provider?: string;
  ai_api_key?: string;
  ai_model_name?: string;
};

export type ProviderModelInfo = {
  id: string;
  name: string;
};

export type PlanAiContextInfo = {
  provider: string;
  messages: Array<{ role: string; content: string }>;
};

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("scalistai_token");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(init.body instanceof FormData) && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  register: (email: string, password: string) =>
    request<{ id: number; email: string }>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: async (email: string, password: string) => {
    const body = new URLSearchParams({ username: email, password });
    const res = await fetch(`${API_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!res.ok) throw new Error("Credenciales inválidas");
    const data = (await res.json()) as { access_token: string };
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
  getAiStatus: (planId: number) =>
    request<AiStatus>(`/api/v1/plans/${planId}/ai-status`),
  getAiContext: (planId: number) =>
    request<PlanAiContextInfo>(`/api/v1/plans/${planId}/ai-context`),
  getMlStatus: () => request<MlModelStatus>(`/api/v1/plans/ml-status`),
  getTrainingStats: () => request<TrainingStats>(`/api/v1/plans/training-stats`),
  async getMe(): Promise<User> {
    return request<User>("/api/v1/auth/me");
  },

  async updateProfile(payload: { email?: string; password?: string }): Promise<User> {
    return request<User>("/api/v1/auth/profile", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  triggerTraining: (epochs: number = 10) =>
    request<{ success: boolean; message: string; is_initial: boolean }>(
      `/api/v1/admin/train-now?epochs=${epochs}`,
      { method: "POST" },
    ),
  generateProcedural: (count: number = 3000) =>
    request<{ success: boolean; message: string }>(
      `/api/v1/admin/gen-procedural?count=${count}`,
      { method: "POST" },
    ),
  getTrainingStatus: () =>
    request<TrainingStatusResponse>("/api/v1/admin/train-status"),
  setTrainingConsent: (projectId: number, allow: boolean) =>
    request<Project>(`/api/v1/projects/${projectId}/training-consent`, {
      method: "PATCH",
      body: JSON.stringify({ allow_training_data: allow }),
    }),
  generateSynthetic: (planId: number, page: number, numVariations: number = 50) =>
    request<{
      plan_id: number;
      page: number;
      variations_generated: number;
      sample: Array<{
        variation_id: string;
        rotation: number;
        flip: string | null;
        style_ops: string[];
        image_size: number;
        image_path: string;
        mask_path: string;
      }>;
    }>(`/api/v1/plans/${planId}/generate-synthetic`, {
      method: "POST",
      body: JSON.stringify({ page, num_variations: numVariations }),
    }),
  regenerateAllSynthetic: () =>
    request<{
      projects_processed: number;
      plans_processed: number;
      pages_processed: number;
      variations_generated: number;
      details: Array<{
        project_id: number;
        plan_id: number;
        page: number;
        variations: number;
        ok: boolean;
        error?: string;
      }>;
      message?: string;
    }>(`/api/v1/projects/regenerate-synthetic`, {
      method: "POST",
    }),
  deleteProject: async (id: number): Promise<void> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/projects/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok && res.status !== 204) {
      throw new Error(`No se pudo eliminar (HTTP ${res.status})`);
    }
  },

  listPlans: (projectId: number) =>
    request<Plan[]>(`/api/v1/projects/${projectId}/plans`),

  uploadPlan: (projectId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<Plan>(
      `/api/v1/projects/${projectId}/plans`,
      { method: "POST", body: formData },
    );
  },
  
  uploadDxf: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<{ success: boolean; project_id: number; plan_id: number; elements_imported: number }>(
      "/api/v1/integrations/dxf/upload",
      { method: "POST", body: formData },
    );
  },

  getRenderStatus: (planId: number) =>
    request<{ rendered: number; total: number }>(
      `/api/v1/plans/${planId}/render-status`,
    ),

  startPrewarm: (planId: number) =>
    request<{ status: string; page_count: number }>(
      `/api/v1/plans/${planId}/prewarm`,
      { method: "POST", body: "{}" },
    ),

  calibrateScale: (
    planId: number,
    p1: { x: number; y: number },
    p2: { x: number; y: number },
    real_distance_m: number,
    page = 1,
  ) =>
    request<Plan>(`/api/v1/plans/${planId}/scale`, {
      method: "POST",
      body: JSON.stringify({ p1, p2, real_distance_m, page }),
    }),

  autoDetectScales: (planId: number) =>
    request<Plan>(`/api/v1/plans/${planId}/auto-detect-scale`, {
      method: "POST",
      body: "{}",
    }),

  previewAutoDetectScales: (planId: number) =>
    request<Record<string, number>>(`/api/v1/plans/${planId}/preview-auto-detect`),

  setBulkScaleRatios: (planId: number, scales: Record<string, number>) =>
    request<Plan>(`/api/v1/plans/${planId}/bulk-scale-ratio`, {
      method: "POST",
      body: JSON.stringify(scales),
    }),

  setScaleRatio: (planId: number, page: number, denominator: number) =>
    request<Plan>(`/api/v1/plans/${planId}/scale-ratio`, {
      method: "POST",
      body: JSON.stringify({ page, denominator }),
    }),

  clearPageScale: (planId: number, page: number) =>
    request<Plan>(`/api/v1/plans/${planId}/scale/${page}`, {
      method: "DELETE",
    }),

  deletePage: (planId: number, page: number) =>
    request<Plan>(`/api/v1/plans/${planId}/delete-page/${page}`, {
      method: "POST",
      body: "{}",
    }),


  fetchPlanRaster: async (planId: number, page = 1): Promise<Blob> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/plans/${planId}/raster?page=${page}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`No se pudo cargar el raster (HTTP ${res.status})`);
    return res.blob();
  },

  listElements: (planId: number, page?: number) => {
    const qs = page !== undefined ? `?page=${page}` : "";
    return request<DetectedElement[]>(`/api/v1/plans/${planId}/elements${qs}`);
  },

  createElement: (planId: number, payload: ElementCreatePayload) =>
    request<DetectedElement>(`/api/v1/plans/${planId}/elements`, {
      method: "POST",
      body: JSON.stringify({
        source: "manual",
        height_m: 2.8,
        ...payload,
      }),
    }),

  updateElement: (planId: number, elementId: number, patch: ElementUpdatePayload) =>
    request<DetectedElement>(`/api/v1/plans/${planId}/elements/${elementId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  candidatesBulkAction: (
    planId: number,
    action: "accept" | "discard",
    elementIds?: number[],
    page?: number,
  ) =>
    request<DetectedElement[]>(
      `/api/v1/plans/${planId}/elements/candidates/bulk-action`,
      {
        method: "POST",
        body: JSON.stringify({
          action,
          element_ids: elementIds ?? null,
          page: page ?? null,
        }),
      },
    ),

  deleteElement: async (planId: number, elementId: number): Promise<void> => {
    const token = getToken();
    const res = await fetch(
      `${API_URL}/api/v1/plans/${planId}/elements/${elementId}`,
      {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
    );
    if (!res.ok && res.status !== 204) {
      throw new Error(`No se pudo eliminar (HTTP ${res.status})`);
    }
  },

  bulkDeleteElements: async (planId: number, ids: number[]): Promise<void> => {
    if (ids.length === 0) return;
    const token = getToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(
      `${API_URL}/api/v1/plans/${planId}/elements/bulk/delete`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(ids),
      },
    );
    if (!res.ok && res.status !== 204) {
      throw new Error(`No se pudo eliminar en lote (HTTP ${res.status})`);
    }
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

  deleteMaterial: async (id: number): Promise<void> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/materials/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok && res.status !== 204) {
      throw new Error(`No se pudo eliminar el material (HTTP ${res.status})`);
    }
  },

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

  deleteAssembly: async (id: number): Promise<void> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/assemblies/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok && res.status !== 204) {
      throw new Error(`No se pudo eliminar el sistema constructivo (HTTP ${res.status})`);
    }
  },

  // ----- Asignación elemento ↔ assembly -----
  assignAssembly: (planId: number, elementId: number, assemblyId: number) =>
    request<DetectedElement>(
      `/api/v1/plans/${planId}/elements/${elementId}/assemblies`,
      {
        method: "POST",
        body: JSON.stringify({ assembly_id: assemblyId }),
      },
    ),

  removeAssembly: async (
    planId: number,
    elementId: number,
    assemblyId: number,
  ): Promise<DetectedElement> => {
    const token = getToken();
    const res = await fetch(
      `${API_URL}/api/v1/plans/${planId}/elements/${elementId}/assemblies/${assemblyId}`,
      {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
    );
    if (!res.ok) throw new Error(`No se pudo quitar el sistema constructivo (HTTP ${res.status})`);
    return res.json() as Promise<DetectedElement>;
  },

  bulkAssignAssembly: (planId: number, elementIds: number[], assemblyId: number) =>
    request<DetectedElement[]>(
      `/api/v1/plans/${planId}/elements/bulk/assemblies`,
      {
        method: "POST",
        body: JSON.stringify({ element_ids: elementIds, assembly_id: assemblyId }),
      },
    ),

  bulkRemoveAssembly: (planId: number, elementIds: number[], assemblyId: number) =>
    request<DetectedElement[]>(
      `/api/v1/plans/${planId}/elements/bulk/assemblies/remove`,
      {
        method: "POST",
        body: JSON.stringify({ element_ids: elementIds, assembly_id: assemblyId }),
      },
    ),

  // ----- Cómputo agregado -----
  getMaterialsSummary: (planId: number, page?: number) => {
    const qs = page !== undefined ? `?page=${page}` : "";
    return request<MaterialSummaryItem[]>(
      `/api/v1/plans/${planId}/materials-summary${qs}`,
    );
  },

  detectWalls: (planId: number, page: number) =>
    request<any[]>(`/api/v1/plans/${planId}/detect-walls?page=${page}`),

  detectRooms: (planId: number, page: number) =>
    request<any[]>(`/api/v1/plans/${planId}/detect-rooms?page=${page}`),

  detectOpenings: (planId: number, page: number) =>
    request<any[]>(`/api/v1/plans/${planId}/detect-openings?page=${page}`),

  recommendPages: (planId: number) =>
    request<PageRecommendation[]>(`/api/v1/plans/${planId}/recommend-pages`),

  suggestRoles: (planId: number) =>
    request<PageClassification[]>(`/api/v1/plans/${planId}/suggest-roles`),

  setPageOverride: (
    planId: number,
    page: number,
    override: PageOverride | null,
  ) =>
    request<Plan>(`/api/v1/plans/${planId}/page-override`, {
      method: "POST",
      body: JSON.stringify({ page, override }),
    }),

  setPageRoles: (
    planId: number,
    pageRoles: Record<string, PageRole[]>,
    skipAiDetection?: boolean,
  ) =>
    request<Plan>(`/api/v1/plans/${planId}/page-roles`, {
      method: "PATCH",
      body: JSON.stringify({ page_roles: pageRoles, skip_ai_detection: skipAiDetection }),
    }),

  getDxfInfo: (planId: number) =>
    request<DxfInfo>(`/api/v1/plans/${planId}/dxf-info`),

  setDxfScale: (planId: number, unit: "mm" | "cm" | "m") =>
    request<{ success: boolean }>(`/api/v1/plans/${planId}/dxf-scale`, {
      method: "POST",
      body: JSON.stringify({ unit }),
    }),

  fetchDxfOverview: async (planId: number): Promise<Blob> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/plans/${planId}/dxf-overview`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`No se pudo cargar la vista de la lámina (HTTP ${res.status})`);
    return res.blob();
  },

  fetchDxfLayerPreview: async (planId: number, layer: string): Promise<Blob> => {
    const token = getToken();
    const res = await fetch(
      `${API_URL}/api/v1/plans/${planId}/dxf-layer-preview?layer=${encodeURIComponent(layer)}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
    if (!res.ok) throw new Error(`No se pudo cargar la vista previa de la capa (HTTP ${res.status})`);
    return res.blob();
  },

  applyDxfLayers: (
    planId: number,
    mapping: Record<string, string | null>,
    regions?: number[][],
    regionTypes?: DxfRegionType[],
  ) =>
    request<{ created: number }>(`/api/v1/plans/${planId}/dxf-layers/apply`, {
      method: "POST",
      body: JSON.stringify({
        mapping,
        regions: regions ?? null,
        region_types: regionTypes ?? null,
      }),
    }),

  createElementsBulk: (planId: number, payload: any[]) =>
    request<DetectedElement[]>(`/api/v1/plans/${planId}/elements-bulk`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  createOpeningsBulk: (planId: number, payload: any[]) =>
    request<DetectedElement[]>(`/api/v1/plans/${planId}/openings-bulk`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  exportXlsx: async (planId: number, page?: number): Promise<Blob> => {
    const token = getToken();
    const qs = page !== undefined ? `?page=${page}` : "";
    const res = await fetch(`${API_URL}/api/v1/plans/${planId}/export/xlsx${qs}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`No se pudo exportar (HTTP ${res.status})`);
    return res.blob();
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
  deleteOrganization: async (id: number): Promise<void> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/admin/organizations/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok && res.status !== 204) throw new Error("No se pudo eliminar la organización");
  },

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
  deleteOrgUser: async (userId: number): Promise<void> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/admin/users/${userId}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  },

  // ---- Team (org admin / member) ----
  listTeam: () => request<OrgUser[]>(`/api/v1/team/users`),
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
  deleteTeamUser: async (userId: number): Promise<void> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/team/users/${userId}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  },

  // ---- Organization AI Config (BYOK) ----
  getAiConfig: () => request<AiConfigRead>("/api/v1/organization/ai-config"),
  updateAiConfig: (payload: AiConfigUpdate) =>
    request<AiConfigRead>("/api/v1/organization/ai-config", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  listProviderModels: (provider: string, api_key?: string) =>
    request<ProviderModelInfo[]>("/api/v1/ai-providers/list-models", {
      method: "POST",
      body: JSON.stringify({ provider, api_key }),
    }),

  async uploadMaterialsJson(items: any[]): Promise<{imported: number, updated: number}> {
    return request<{imported: number, updated: number}>("/api/v1/materials/import-json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(items),
    });
  },
};

