"use client";

/**
 * Calculadora de cotización de la landing.
 *
 * El precio se arma en vivo desde factores simples (usuarios, volumen de
 * proyectos, módulos, facturación). Los montos viven en QUOTE_PRICING para
 * ajustarlos sin tocar la UI. El CTA manda el resumen prellenado a WhatsApp.
 */

import { useMemo, useState } from "react";
import {
  ArrowRight, Box, CalendarRange, Check, LineChart, Minus, Plus, Users,
} from "lucide-react";

// ---------------------------------------------------------------- pricing
// Todos los montos en ARS/mes. Editar acá para recalibrar la oferta.
const QUOTE_PRICING = {
  base: 49_000,            // plataforma: cómputo + presupuesto (PDF/DXF/DWG), 2 usuarios
  includedUsers: 2,
  extraUser: 15_000,       // por usuario adicional / mes
  projects: {              // proyectos activos por mes
    "3": { label: "Hasta 3", price: 0 },
    "10": { label: "Hasta 10", price: 30_000 },
    "unlimited": { label: "Ilimitados", price: 70_000 },
  } as Record<string, { label: string; price: number }>,
  modules: [
    {
      key: "bim", icon: Box, price: 35_000,
      name: "Import BIM (IFC)",
      desc: "Del modelo Revit/ArchiCAD al presupuesto directo: fundaciones, armaduras y artefactos incluidos.",
    },
    {
      key: "gantt", icon: CalendarRange, price: 19_000,
      name: "Cronograma + curva de inversión",
      desc: "Gantt por etapas de obra y flujo de fondos mensual (curva S).",
    },
    {
      key: "precios", icon: LineChart, price: 24_000,
      name: "Precios de mercado Pro",
      desc: "Histórico de precios relevados de proveedores y comparación contra inflación.",
    },
  ],
  annualDiscount: 0.2,     // -20% pagando anual
  enterpriseUsersFrom: 11, // desde acá sugerimos plan Empresa (precio a medida)
};

const fmt = (n: number) =>
  new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(Math.round(n));

export function QuoteCalculator() {
  const [users, setUsers] = useState(3);
  const [projects, setProjects] = useState<"3" | "10" | "unlimited">("3");
  const [modules, setModules] = useState<Record<string, boolean>>({ bim: true });
  const [annual, setAnnual] = useState(true);

  const P = QUOTE_PRICING;
  const quote = useMemo(() => {
    const extraUsers = Math.max(0, users - P.includedUsers);
    const moduleItems = P.modules.filter((m) => modules[m.key]);
    const monthlyList =
      P.base +
      extraUsers * P.extraUser +
      P.projects[projects].price +
      moduleItems.reduce((s, m) => s + m.price, 0);
    const monthly = annual ? monthlyList * (1 - P.annualDiscount) : monthlyList;
    const enterprise = users >= P.enterpriseUsersFrom;
    const plan = enterprise
      ? "Empresa"
      : projects !== "3" || moduleItems.length >= 2
        ? "Profesional"
        : "Estudio";
    return { extraUsers, moduleItems, monthlyList, monthly, enterprise, plan };
  }, [users, projects, modules, annual, P]);

  const waText = encodeURIComponent(
    `Hola! Cotizé ScalistAI online:\n` +
    `• Plan ${quote.plan}\n` +
    `• ${users} usuario${users !== 1 ? "s" : ""}\n` +
    `• Proyectos: ${P.projects[projects].label.toLowerCase()}\n` +
    `• Módulos: cómputo y presupuesto${quote.moduleItems.map((m) => ", " + m.name.toLowerCase()).join("")}\n` +
    (quote.enterprise
      ? `Me gustaría coordinar una propuesta a medida.`
      : `• Estimado: $${fmt(quote.monthly)}/mes (${annual ? "anual" : "mensual"})\nMe gustaría coordinar una demo.`),
  );

  const toggleModule = (key: string) =>
    setModules((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-5">
      {/* -------- Configurador -------- */}
      <div className="space-y-6 lg:col-span-3">
        {/* Usuarios */}
        <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <div className="mb-1 flex items-center gap-2 text-white">
            <Users className="h-4 w-4 text-brand-400" />
            <h3 className="font-semibold">¿Cuántas personas lo van a usar?</h3>
          </div>
          <p className="mb-4 text-xs text-slate-500">
            Arquitectos, cómputistas y administración. Incluye {P.includedUsers} usuarios;
            cada adicional ${fmt(P.extraUser)}/mes. Roles y permisos incluidos en todos los planes.
          </p>
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => setUsers((u) => Math.max(1, u - 1))}
              className="flex h-10 w-10 items-center justify-center rounded-full border border-slate-700 text-slate-300 transition hover:border-brand-500 hover:text-white"
              aria-label="Menos usuarios"
            >
              <Minus className="h-4 w-4" />
            </button>
            <span className="w-16 text-center text-3xl font-bold text-white tabular-nums">{users}</span>
            <button
              type="button"
              onClick={() => setUsers((u) => Math.min(50, u + 1))}
              className="flex h-10 w-10 items-center justify-center rounded-full border border-slate-700 text-slate-300 transition hover:border-brand-500 hover:text-white"
              aria-label="Más usuarios"
            >
              <Plus className="h-4 w-4" />
            </button>
            {quote.enterprise && (
              <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-300">
                Equipos grandes → precio a medida
              </span>
            )}
          </div>
        </div>

        {/* Proyectos */}
        <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <h3 className="mb-1 font-semibold text-white">¿Cuántos proyectos activos por mes?</h3>
          <p className="mb-4 text-xs text-slate-500">
            Un proyecto = una obra con sus planos, presupuesto y cronograma. El almacenamiento está incluido.
          </p>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(P.projects) as Array<"3" | "10" | "unlimited">).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setProjects(k)}
                className={`rounded-full border px-5 py-2 text-sm font-medium transition ${
                  projects === k
                    ? "border-brand-500 bg-brand-500/15 text-brand-200"
                    : "border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200"
                }`}
              >
                {P.projects[k].label}
                {P.projects[k].price > 0 && (
                  <span className="ml-1.5 text-xs opacity-70">+${fmt(P.projects[k].price)}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Módulos */}
        <div className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <h3 className="mb-1 font-semibold text-white">¿Qué módulos necesitás?</h3>
          <p className="mb-4 text-xs text-slate-500">
            El cómputo y presupuesto desde PDF, DXF y DWG viene incluido siempre.
          </p>
          <div className="space-y-3">
            {/* Base, siempre incluido */}
            <div className="flex items-start gap-4 rounded-2xl border border-brand-500/25 bg-brand-500/[0.06] p-4">
              <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-500">
                <Check className="h-3 w-3 text-white" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-white">Cómputo y presupuesto</span>
                  <span className="text-xs font-medium text-brand-300">Incluido</span>
                </div>
                <p className="mt-0.5 text-xs leading-relaxed text-slate-400">
                  Cantidades exactas desde PDF, DXF y DWG, presupuesto por rubro con precios de mercado y export a Excel.
                </p>
              </div>
            </div>

            {P.modules.map((m) => {
              const on = Boolean(modules[m.key]);
              return (
                <button
                  key={m.key}
                  type="button"
                  onClick={() => toggleModule(m.key)}
                  aria-pressed={on}
                  className={`flex w-full items-start gap-4 rounded-2xl border p-4 text-left transition ${
                    on
                      ? "border-brand-500/50 bg-brand-500/[0.08]"
                      : "border-slate-800 bg-slate-900/60 hover:border-slate-600"
                  }`}
                >
                  <div
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition ${
                      on ? "border-brand-500 bg-brand-500" : "border-slate-600"
                    }`}
                  >
                    {on && <Check className="h-3 w-3 text-white" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2 text-sm font-semibold text-white">
                        <m.icon className="h-4 w-4 text-brand-400" /> {m.name}
                      </span>
                      <span className="shrink-0 text-xs font-medium text-slate-400">
                        +${fmt(m.price)}/mes
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{m.desc}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Facturación */}
        <div className="flex items-center justify-between rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <div>
            <h3 className="font-semibold text-white">Facturación</h3>
            <p className="text-xs text-slate-500">
              Pagando anual ahorrás un {Math.round(P.annualDiscount * 100)}%.
            </p>
          </div>
          <div className="flex rounded-full border border-slate-700 p-1">
            {([["Mensual", false], ["Anual", true]] as const).map(([label, val]) => (
              <button
                key={label}
                type="button"
                onClick={() => setAnnual(val)}
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
                  annual === val ? "bg-brand-600 text-white" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {label}
                {val && <span className="ml-1 text-[10px] opacity-80">-20%</span>}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* -------- Resumen -------- */}
      <div className="lg:col-span-2">
        <div className="sticky top-24 rounded-3xl border border-brand-500/30 bg-gradient-to-b from-slate-900 to-slate-950 p-7 shadow-2xl shadow-brand-500/10">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-brand-400">
            Tu cotización
          </div>
          <div className="mb-5 flex items-baseline justify-between">
            <h3 className="text-2xl font-bold text-white">Plan {quote.plan}</h3>
            {annual && !quote.enterprise && (
              <span className="rounded-full bg-green-500/10 px-2.5 py-1 text-xs font-semibold text-green-400">
                Ahorrás ${fmt((quote.monthlyList - quote.monthly) * 12)}/año
              </span>
            )}
          </div>

          <ul className="mb-6 space-y-2.5 text-sm">
            {[
              `${users} usuario${users !== 1 ? "s" : ""} con roles y permisos`,
              `Proyectos activos: ${P.projects[projects].label.toLowerCase()}`,
              "Cómputo y presupuesto (PDF · DXF · DWG)",
              ...quote.moduleItems.map((m) => m.name),
              "Precios de mercado actualizados",
              "Export a Excel · soporte por WhatsApp",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2.5 text-slate-300">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-400" />
                {item}
              </li>
            ))}
          </ul>

          <div className="mb-6 rounded-2xl border border-slate-800 bg-slate-950/80 p-5 text-center">
            {quote.enterprise ? (
              <>
                <div className="text-3xl font-extrabold text-white">A medida</div>
                <div className="mt-1 text-xs text-slate-500">
                  Para equipos de {P.enterpriseUsersFrom}+ usuarios armamos una propuesta con
                  onboarding y soporte dedicado.
                </div>
              </>
            ) : (
              <>
                <div className="flex items-baseline justify-center gap-1.5">
                  <span className="text-4xl font-extrabold tracking-tight text-white">
                    ${fmt(quote.monthly)}
                  </span>
                  <span className="text-sm text-slate-400">/mes</span>
                </div>
                {annual && (
                  <div className="mt-1 text-xs text-slate-500">
                    <span className="line-through">${fmt(quote.monthlyList)}</span> pagando anual
                  </div>
                )}
              </>
            )}
          </div>

          <a
            href={`https://wa.me/549357161909?text=${waText}`}
            target="_blank"
            rel="noreferrer"
            className="group flex w-full items-center justify-center gap-2 rounded-full bg-brand-600 px-6 py-3.5 text-base font-semibold text-white transition hover:bg-brand-500 hover:shadow-[0_0_30px_rgba(14,165,233,0.35)]"
          >
            {quote.enterprise ? "Pedir propuesta a medida" : "Solicitar esta cotización"}
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
          </a>
          <p className="mt-3 text-center text-[11px] leading-relaxed text-slate-500">
            Precio estimado en ARS + IVA, sujeto a confirmación comercial.
            Incluye demo con tus propios planos, sin compromiso.
          </p>
        </div>
      </div>
    </div>
  );
}
