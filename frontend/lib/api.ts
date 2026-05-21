const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Project = {
  id: number;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
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
  created_at: string;
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

  fetchPlanRaster: async (planId: number, page = 1): Promise<Blob> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/v1/plans/${planId}/raster?page=${page}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`No se pudo cargar el raster (HTTP ${res.status})`);
    return res.blob();
  },
};
