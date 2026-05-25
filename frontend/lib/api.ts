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

export type AiStage = "pending" | "running" | "done" | "failed";

export type AiStatus = {
  scales: AiStage;
  walls: AiStage;
  rooms: AiStage;
  openings: AiStage;
  started_at: number | null;
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
  created_at: string;
};

export type ElementType = "wall" | "room" | "opening";

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
  yields: MaterialYield[];
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
  source: "manual" | "ai";
  created_at: string;
  updated_at: string;
  materials: Material[];
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

export type MaterialYieldInput = {
  applies_to: string; // wall | room_floor | room_wall | room_perimeter | opening | opening_perimeter
  consumption: number;
  waste_factor: number;
  unit_price: number;
};

export type MaterialCreatePayload = {
  name: string;
  category: string;
  unit: string;
  yields: MaterialYieldInput[];
};

export type MaterialUpdatePayload = {
  name?: string;
  category?: string;
  unit?: string;
  yields?: MaterialYieldInput[];
};

export type MaterialSummaryItem = {
  material: Material;
  quantity: number;
  unit: string;
  unit_price: number;
  subtotal: number;
};

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("muroai_token");
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
    window.localStorage.setItem("muroai_token", data.access_token);
    return data;
  },

  logout: () => window.localStorage.removeItem("muroai_token"),

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
    const form = new FormData();
    form.append("file", file);
    return request<Plan>(`/api/v1/projects/${projectId}/plans`, {
      method: "POST",
      body: form,
    });
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

  restorePage: (planId: number, page: number) =>
    request<Plan>(`/api/v1/plans/${planId}/restore-page/${page}`, {
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

  // ----- Asignación elemento ↔ material -----
  assignMaterial: (planId: number, elementId: number, materialId: number) =>
    request<DetectedElement>(
      `/api/v1/plans/${planId}/elements/${elementId}/materials`,
      {
        method: "POST",
        body: JSON.stringify({ material_id: materialId }),
      },
    ),

  removeMaterial: async (
    planId: number,
    elementId: number,
    materialId: number,
  ): Promise<DetectedElement> => {
    const token = getToken();
    const res = await fetch(
      `${API_URL}/api/v1/plans/${planId}/elements/${elementId}/materials/${materialId}`,
      {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
    );
    if (!res.ok) throw new Error(`No se pudo quitar el material (HTTP ${res.status})`);
    return res.json() as Promise<DetectedElement>;
  },

  bulkAssignMaterial: (planId: number, elementIds: number[], materialId: number) =>
    request<DetectedElement[]>(
      `/api/v1/plans/${planId}/elements/bulk/materials`,
      {
        method: "POST",
        body: JSON.stringify({ element_ids: elementIds, material_id: materialId }),
      },
    ),

  bulkRemoveMaterial: (planId: number, elementIds: number[], materialId: number) =>
    request<DetectedElement[]>(
      `/api/v1/plans/${planId}/elements/bulk/materials/remove`,
      {
        method: "POST",
        body: JSON.stringify({ element_ids: elementIds, material_id: materialId }),
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
    request<{ page: number; score: number; recommended: boolean; reason: string }[]>(
      `/api/v1/plans/${planId}/recommend-pages`,
    ),

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
};
