"use client";

import { useEffect, useState } from "react";
import { api, type AiConfigRead, type ProviderModelInfo } from "@/lib/api";

export function AiConfigSection() {
  const [config, setConfig] = useState<AiConfigRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Form State
  const [provider, setProvider] = useState("scalist");
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState("");

  // Models from provider
  const [models, setModels] = useState<ProviderModelInfo[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  useEffect(() => {
    api.getAiConfig()
      .then((data) => {
        setConfig(data);
        setProvider(data.ai_provider);
        setModelName(data.ai_model_name || "");
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (provider === "scalist") {
      setModels([{ id: "scalist-v10", name: "Scalist Native (v10)" }]);
      return;
    }
    
    // Only load models if we have an API key or the config says we already have one
    if (apiKey || (config?.ai_provider === provider && config?.has_api_key)) {
      setLoadingModels(true);
      api.listProviderModels(provider, apiKey || undefined)
        .then((m) => {
          setModels(m);
          // Auto-select if empty or current is not in list
          if (!modelName || !m.find(x => x.id === modelName)) {
            if (m.length > 0) setModelName(m[0].id);
          }
        })
        .catch((err) => setError("Error listando modelos: " + err.message))
        .finally(() => setLoadingModels(false));
    } else {
      setModels([]);
    }
  }, [provider, apiKey, config]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(false);

    try {
      const updated = await api.updateAiConfig({
        ai_provider: provider,
        ai_api_key: apiKey || undefined,
        ai_model_name: modelName || undefined,
      });
      setConfig(updated);
      setApiKey(""); // Clear input on success
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return null;

  return (
    <div className="relative w-full max-w-lg">
      <div className="relative z-10 mb-8">
        <h2 className="bg-gradient-to-br from-slate-900 to-slate-600 bg-clip-text text-2xl font-bold tracking-tight text-transparent dark:from-white dark:to-slate-400">
          Configuración de Inteligencia Artificial (BYOK)
        </h2>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          Usa tu propio proveedor de IA (Bring Your Own Key) para el análisis avanzado de planos y detección de recintos.
        </p>
      </div>

      <form onSubmit={handleSave} className="relative z-10 space-y-6">
        <div>
          <label className="block text-sm font-semibold tracking-wide text-slate-700 dark:text-slate-300">
            Proveedor
          </label>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="mt-2 w-full max-w-md rounded-xl border border-slate-300/50 bg-white/60 px-4 py-3 text-sm font-medium outline-none transition-all duration-300 hover:border-cyan-500/50 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 dark:border-white/10 dark:bg-slate-950/40 dark:text-slate-100 dark:hover:border-cyan-400/50 dark:focus:border-cyan-400 dark:focus:ring-cyan-400"
          >
            <option value="scalist">Scalist Native AI (Recomendado)</option>
            <option value="gemini">Google Gemini</option>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic Claude</option>
          </select>
        </div>

        {provider !== "scalist" && (
          <div className="animate-in fade-in slide-in-from-top-2 duration-300">
            <label className="flex items-center justify-between max-w-md text-sm font-semibold tracking-wide text-slate-700 dark:text-slate-300">
              API Key
              {config?.has_api_key && config.ai_provider === provider && (
                <span className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-bold text-green-700 dark:bg-green-500/20 dark:text-green-400">
                  CONFIGURADA
                </span>
              )}
            </label>
            <input
              type="password"
              placeholder={config?.has_api_key && config.ai_provider === provider ? "••••••••••••••••" : "Ingresá tu API Key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              required={!config?.has_api_key || config.ai_provider !== provider}
              className="mt-2 w-full max-w-md rounded-xl border border-slate-300/50 bg-white/60 px-4 py-3 font-mono text-sm outline-none transition-all duration-300 hover:border-cyan-500/50 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 dark:border-white/10 dark:bg-slate-950/40 dark:text-slate-100 dark:hover:border-cyan-400/50 dark:focus:border-cyan-400 dark:focus:ring-cyan-400"
            />
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              Tu clave se almacena cifrada y solo se usa para procesar tus planos.
            </p>
          </div>
        )}

        <div>
          <label className="block text-sm font-semibold tracking-wide text-slate-700 dark:text-slate-300">
            Modelo
          </label>
          <div className="mt-2 flex items-center gap-3">
            <select
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              disabled={loadingModels || models.length === 0}
              className="w-full max-w-md rounded-xl border border-slate-300/50 bg-white/60 px-4 py-3 text-sm font-medium outline-none transition-all duration-300 hover:border-cyan-500/50 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 disabled:opacity-50 disabled:hover:border-slate-300/50 dark:border-white/10 dark:bg-slate-950/40 dark:text-slate-100 dark:hover:border-cyan-400/50 dark:focus:border-cyan-400 dark:focus:ring-cyan-400 dark:disabled:hover:border-white/10"
            >
              {loadingModels && <option value="">Cargando modelos...</option>}
              {!loadingModels && models.map(m => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
              {!loadingModels && models.length === 0 && <option value="">Ingresá una API Key válida</option>}
            </select>
            {loadingModels && (
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-cyan-500 border-t-transparent" />
            )}
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-red-200/50 bg-red-50/50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-400">
            {error}
          </div>
        )}
        
        {success && (
          <div className="rounded-lg border border-green-200/50 bg-green-50/50 px-4 py-3 text-sm text-green-700 dark:border-green-900/50 dark:bg-green-900/20 dark:text-green-400">
            Configuración guardada correctamente.
          </div>
        )}

        <div className="pt-4">
          <button
            type="submit"
            disabled={saving || (provider !== "scalist" && !apiKey && !(config?.has_api_key && config.ai_provider === provider))}
            className="group relative flex items-center gap-2 rounded-xl bg-cyan-600 px-6 py-3 text-sm font-bold text-white shadow-lg shadow-cyan-500/25 transition-all duration-300 hover:-translate-y-0.5 hover:bg-cyan-500 hover:shadow-cyan-500/40 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-cyan-500/25 dark:focus:ring-offset-slate-900"
          >
            {saving ? (
              <span className="flex items-center gap-2">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Guardando...
              </span>
            ) : (
              "Guardar Configuración"
            )}
            {!saving && (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-70 transition-transform group-hover:translate-x-1">
                <path d="M5 12h14"/><path d="M12 5l7 7-7 7"/>
              </svg>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
