"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, isUnauthorized, type User } from "@/lib/api";

export default function ProfilePage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    api
      .getMe()
      .then((u) => {
        setUser(u);
        setEmail(u.email);
      })
      .catch((err) => {
        if (isUnauthorized(err)) {
          router.push("/login");
        } else {
          setError("Error cargando perfil: " + (err instanceof Error ? err.message : String(err)));
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    setSaving(true);

    try {
      const payload: { email?: string; password?: string } = {};
      if (email && email !== user?.email) {
        payload.email = email;
      }
      if (password) {
        payload.password = password;
      }

      if (Object.keys(payload).length > 0) {
        const updatedUser = await api.updateProfile(payload);
        setUser(updatedUser);
      }
      setSuccess(true);
      setPassword(""); // Clear password field after successful save
    } catch (err: any) {
      setError(err.message || "Error al actualizar perfil");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-200 border-t-brand dark:border-slate-800 dark:border-t-brand-500"></div>
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-12 animate-fade-in">
      <header className="mb-10 text-center">
        <h1 className="text-3xl font-black tracking-tight text-slate-900 dark:text-white">
          Mi Perfil
        </h1>
        <p className="mt-2 text-slate-500 dark:text-slate-400">
          Actualizá tus datos personales y credenciales de acceso.
        </p>
      </header>

      <div className="glass-panel p-8">
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-400">
            {error}
          </div>
        )}

        {success && (
          <div className="mb-6 rounded-lg bg-emerald-50 p-4 text-sm text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400">
            ¡Perfil actualizado correctamente!
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="space-y-4 rounded-xl border border-slate-100 bg-slate-50/50 p-6 dark:border-white/[0.05] dark:bg-zinc-900/50">
            <h2 className="text-lg font-bold text-slate-800 dark:text-slate-200">
              Datos Personales
            </h2>
            
            <div className="space-y-2">
              <label className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                Rol actual
              </label>
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-brand-100 px-3 py-1 text-xs font-medium text-brand-700 dark:bg-brand-950/50 dark:text-brand-400">
                  {user?.role === "admin" ? "Administrador" : "Miembro"}
                </span>
                {user?.is_superadmin && (
                  <span className="inline-flex items-center rounded-full bg-purple-100 px-3 py-1 text-xs font-medium text-purple-700 dark:bg-purple-950/50 dark:text-purple-400">
                    SuperAdmin
                  </span>
                )}
              </div>
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="email"
                className="text-sm font-semibold text-slate-700 dark:text-slate-300"
              >
                Correo Electrónico
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-slate-900 focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand dark:border-slate-700 dark:bg-zinc-950 dark:text-slate-100 dark:focus:border-brand-500 dark:focus:ring-brand-500 transition-colors"
              />
            </div>
          </div>

          <div className="space-y-4 rounded-xl border border-slate-100 bg-slate-50/50 p-6 dark:border-white/[0.05] dark:bg-zinc-900/50">
            <h2 className="text-lg font-bold text-slate-800 dark:text-slate-200">
              Seguridad
            </h2>
            
            <div className="space-y-1.5">
              <label
                htmlFor="password"
                className="text-sm font-semibold text-slate-700 dark:text-slate-300"
              >
                Nueva Contraseña
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Dejar en blanco para no cambiarla"
                minLength={8}
                className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-slate-900 focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand dark:border-slate-700 dark:bg-zinc-950 dark:text-slate-100 dark:focus:border-brand-500 dark:focus:ring-brand-500 transition-colors placeholder:text-slate-400 dark:placeholder:text-slate-600"
              />
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Mínimo 8 caracteres.
              </p>
            </div>
          </div>

          <div className="flex justify-end pt-4">
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-brand px-8 py-3 font-bold text-white shadow-premium transition-all hover:-translate-y-0.5 hover:bg-brand-600 hover:shadow-lg hover:shadow-brand-500/30 disabled:opacity-70 dark:bg-brand-600 dark:hover:bg-brand-500"
            >
              {saving ? "Guardando..." : "Guardar Cambios"}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}
