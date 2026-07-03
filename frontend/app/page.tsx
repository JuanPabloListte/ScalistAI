"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Zap, Layers, FileSpreadsheet, Lock, Mail, Phone, Upload, ScanLine, Download, Check, ChevronDown, Ruler, DoorOpen, PencilRuler, ChevronLeft, Folder, Package, Users, Building2, Globe, Trash2, Box, CalendarRange, LineChart, Scale } from "lucide-react";

import { QuoteCalculator } from "@/components/landing/quote-calculator";

const STEPS = [
  {
    icon: Upload,
    title: "Subí el plano o el modelo",
    desc: "PDF, DXF, DWG o directamente el modelo BIM (IFC) exportado de Revit/ArchiCAD. Sin configuración, sin escalímetro.",
  },
  {
    icon: ScanLine,
    title: "Cómputo exacto, no estimado",
    desc: "La geometría del CAD/BIM se convierte en cantidades reales: muros, aberturas, estructura, fundaciones y hasta el acero en kilos. La IA asiste donde el archivo no alcanza — y vos aprobás.",
  },
  {
    icon: Download,
    title: "Presupuesto y cronograma",
    desc: "Presupuesto de obra llave en mano con precios reales de mercado, cronograma Gantt y curva de inversión. Exportá a Excel en un clic.",
  },
];

const FAQS = [
  {
    q: "¿Qué formatos acepta?",
    a: "PDF, DXF, DWG y modelos BIM en formato IFC (el export estándar de Revit, ArchiCAD y Tekla). Con un IFC ni siquiera hace falta revisar el plano: el modelo va directo al presupuesto con fundaciones, armaduras y artefactos incluidos.",
  },
  {
    q: "¿Qué tan preciso es el cómputo?",
    a: "Depende de la fuente, y te lo decimos con honestidad: lo que viene de un CAD o BIM es la geometría exacta del archivo (no una estimación). Donde hay que estimar —por ejemplo instalaciones que el plano no trae— el presupuesto lo marca explícitamente como estimado y podés ajustar los porcentajes. Nunca te mezclamos las dos cosas sin avisarte.",
  },
  {
    q: "¿De dónde salen los precios?",
    a: "De relevamientos reales de proveedores argentinos, con historial de evolución y comparación contra la inflación. Nada de índices inventados: cada material tiene su fuente. Además podés cargar tus propios precios y recetas constructivas, que quedan privados de tu organización.",
  },
  {
    q: "¿Mis planos están seguros?",
    a: "Sí. Cada organización tiene sus datos aislados (multi-tenant) y tus planos no se comparten ni se usan sin tu permiso. El control de roles te permite definir quién accede a qué.",
  },
  {
    q: "¿Reemplaza al profesional que computa?",
    a: "No, lo potencia. ScalistAI elimina el trabajo manual y repetitivo de medir, para que tu equipo se enfoque en revisar, decidir y presupuestar más rápido.",
  },
  {
    q: "¿Cómo empiezo?",
    a: "Armá tu cotización online acá arriba y escribinos: coordinamos una demo con tus propios planos para que veas el resultado sobre tu trabajo real, sin compromiso.",
  },
];

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 transition hover:border-slate-700">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left"
      >
        <span className="text-base font-semibold text-white">{q}</span>
        <ChevronDown className={`h-5 w-5 shrink-0 text-brand-400 transition-transform duration-300 ${open ? "rotate-180" : ""}`} />
      </button>
      <div className={`grid transition-all duration-300 ease-out ${open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
        <div className="overflow-hidden">
          <p className="px-6 pb-5 text-sm leading-relaxed text-slate-400">{a}</p>
        </div>
      </div>
    </div>
  );
}

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-slate-950 selection:bg-brand-500/30 text-slate-100 font-sans">

      {/* Background Glow Effects & Blueprint Grid */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:40px_40px] opacity-30 pointer-events-none"></div>
      <div className="absolute top-0 -left-4 w-72 h-72 bg-brand-500 rounded-full mix-blend-multiply filter blur-[128px] opacity-20 animate-blob pointer-events-none"></div>
      <div className="absolute top-0 -right-4 w-72 h-72 bg-sky-400 rounded-full mix-blend-multiply filter blur-[128px] opacity-20 animate-blob animation-delay-2000 pointer-events-none"></div>
      <div className="absolute -bottom-8 left-20 w-72 h-72 bg-indigo-500 rounded-full mix-blend-multiply filter blur-[128px] opacity-20 animate-blob animation-delay-4000 pointer-events-none"></div>

      {/* Navbar Minimalista */}
      <nav className="absolute top-0 left-0 right-0 z-50 flex items-center justify-between px-6 py-6 md:px-12 lg:px-24">
        <div className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
          <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-md">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="ScalistAI Logo" className="h-full w-full object-contain" />
          </div>
          ScalistAI
        </div>
        <div className="hidden md:flex items-center gap-8 text-sm font-medium text-slate-300">
          <a href="#how" className="transition hover:text-white">Cómo funciona</a>
          <a href="#features" className="transition hover:text-white">Funciones</a>
          <a href="#cotizacion" className="transition hover:text-white">Precios</a>
          <a href="#faq" className="transition hover:text-white">Preguntas</a>
        </div>
        <div className="flex gap-4">
          <a href="#cotizacion" className="hidden sm:inline-flex items-center justify-center rounded-full bg-brand-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-brand-500 hover:shadow-lg hover:shadow-brand-500/25">
            Calcular precio
          </a>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative z-10 mx-auto max-w-7xl px-6 pt-32 pb-12 md:px-12 lg:px-24 lg:pt-44 text-center flex flex-col items-center">

        <div className="inline-flex items-center gap-2 rounded-full border border-brand-500/30 bg-brand-500/10 px-3 py-1 text-xs font-semibold text-brand-300 mb-8 animate-fade-in">
          <Zap className="h-3 w-3" />
          <span>PDF · DXF · DWG · BIM (IFC) — con precios reales de mercado</span>
        </div>

        <h1 className="max-w-4xl text-5xl font-extrabold tracking-tight text-white sm:text-6xl md:text-7xl lg:text-8xl animate-slide-up" style={{ animationDelay: '0.1s', animationFillMode: 'both' }}>
          Del plano al <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-400 to-sky-300">presupuesto de obra</span> en minutos.
        </h1>

        <p className="mt-8 max-w-2xl text-lg text-slate-400 sm:text-xl animate-slide-up" style={{ animationDelay: '0.2s', animationFillMode: 'both' }}>
          ScalistAI computa tu proyecto desde el plano o el modelo BIM —muros, aberturas, estructura, fundaciones, hasta el acero en kilos— y genera el presupuesto llave en mano con precios reales, cronograma y curva de inversión.
        </p>

        <div className="mt-10 flex flex-col sm:flex-row gap-4 justify-center animate-slide-up" style={{ animationDelay: '0.3s', animationFillMode: 'both' }}>
          <a href="#cotizacion" className="group relative inline-flex items-center justify-center overflow-hidden rounded-full bg-brand-600 px-8 py-3.5 text-base font-semibold text-white transition hover:bg-brand-500 hover:shadow-[0_0_40px_rgba(14,165,233,0.4)]">
            <span>Calcular mi precio</span>
            <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-1" />
          </a>
          <a href="#how" className="inline-flex items-center justify-center rounded-full border border-slate-700 bg-slate-800/50 backdrop-blur-sm px-8 py-3.5 text-base font-semibold text-slate-200 transition hover:bg-slate-800 hover:border-slate-600">
            Ver cómo funciona
          </a>
        </div>

        {/* Product Mockup — réplica del layout de la app */}
        <div className="mt-20 w-full max-w-6xl animate-slide-up" style={{ animationDelay: '0.45s', animationFillMode: 'both' }}>
          <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-left shadow-2xl shadow-brand-500/10">
            {/* Window chrome */}
            <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900/90 px-4 py-3">
              <span className="h-3 w-3 rounded-full bg-red-400/70"></span>
              <span className="h-3 w-3 rounded-full bg-yellow-400/70"></span>
              <span className="h-3 w-3 rounded-full bg-green-400/70"></span>
              <span className="ml-4 text-xs text-slate-500">app.scalistai.com</span>
            </div>

            <div className="flex">
              {/* Icon rail */}
              <div className="hidden w-12 shrink-0 flex-col items-center gap-5 border-r border-slate-800 bg-slate-900/60 py-4 sm:flex">
                <div className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src="/logo.png" alt="Logo" className="h-full w-full object-contain brightness-0 invert opacity-90" />
                </div>
                <Folder className="h-5 w-5 text-brand-400" />
                <Package className="h-5 w-5 text-slate-500" />
                <Users className="h-5 w-5 text-slate-500" />
                <Building2 className="h-5 w-5 text-slate-500" />
                <Globe className="h-5 w-5 text-slate-500" />
              </div>

              {/* Main column */}
              <div className="min-w-0 flex-1">
                {/* Project header */}
                <div className="border-b border-slate-800 px-5 py-4">
                  <div className="flex items-center gap-1 text-xs text-slate-500">
                    <ChevronLeft className="h-3.5 w-3.5" /> Volver a proyectos
                  </div>
                  <div className="mt-2 flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h3 className="text-lg font-bold text-white">Vivienda Dúplex Norte</h3>
                      <p className="truncate text-xs text-slate-500">DX_2026_PLANTA-EJECUTIVO.pdf · 150 DPI · 24 páginas</p>
                    </div>
                    <div className="hidden shrink-0 gap-2 md:flex">
                      <span className="rounded-md border border-slate-700 px-2.5 py-1.5 text-[11px] font-medium text-slate-300">Tabla de escalas · 22</span>
                      <span className="rounded-md border border-brand-500/40 bg-brand-500/10 px-2.5 py-1.5 text-[11px] font-medium text-brand-300">Ver Cronograma (Gantt)</span>
                    </div>
                  </div>
                  {/* Tabs */}
                  <div className="mt-4 flex gap-5 overflow-x-auto text-xs">
                    {[
                      { label: "Muros", count: 1, active: true },
                      { label: "Recinto", count: 1 },
                      { label: "Abertura", count: 1 },
                      { label: "Viga", count: 2 },
                      { label: "Techo / Losa", count: 1 },
                      { label: "Columna", count: 1 },
                    ].map((t) => (
                      <span key={t.label} className={`flex shrink-0 items-center gap-1.5 border-b-2 pb-2 font-medium ${t.active ? "border-brand-500 text-white" : "border-transparent text-slate-500"}`}>
                        {t.label}
                        <span className={`rounded px-1 text-[10px] ${t.active ? "bg-brand-500/20 text-brand-300" : "bg-slate-800 text-slate-400"}`}>{t.count}</span>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Body: Elementos · Canvas · Cómputo */}
                <div className="flex">
                  {/* Elementos panel */}
                  <div className="hidden w-60 shrink-0 border-r border-slate-800 p-4 lg:block">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-sm font-semibold text-white">Elementos</span>
                      <span className="text-[10px] text-slate-500">Todos</span>
                    </div>
                    <p className="mb-3 text-[10px] text-slate-500">Página 2 · 28 dibujados</p>

                    <div className="mb-3 grid grid-cols-3 gap-2 rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-center">
                      {[
                        { v: "142.0 m", l: "Muros" },
                        { v: "312.5 m²", l: "Recintos" },
                        { v: "14", l: "Abert." },
                        { v: "0.0 m", l: "Vigas" },
                        { v: "0.0 m²", l: "Techos" },
                        { v: "0", l: "Cols." },
                      ].map((s) => (
                        <div key={s.l}>
                          <div className="text-[11px] font-bold text-brand-300">{s.v}</div>
                          <div className="text-[9px] text-slate-500">{s.l}</div>
                        </div>
                      ))}
                    </div>

                    <div className="mb-3 rounded-lg border border-slate-800 bg-slate-900/60 p-2.5">
                      <div className="mb-2 text-[11px] font-semibold text-slate-300">Detección con IA</div>
                      <div className="mb-2 grid grid-cols-3 gap-1.5">
                        {["Muros", "Recintos", "Abert."].map((b) => (
                          <span key={b} className="rounded border border-brand-500/30 bg-brand-500/10 py-1 text-center text-[9px] font-medium text-brand-300">{b}</span>
                        ))}
                      </div>
                      <div className="rounded border border-slate-700 py-1 text-center text-[9px] text-slate-400">Ocultar dibujos IA</div>
                    </div>

                    <div className="space-y-1.5">
                      {[
                        { n: "Muro 1", d: "4.64 m · alt 2.80 m" },
                        { n: "Muro 2", d: "5.40 m · alt 2.80 m" },
                        { n: "Muro 3", d: "4.59 m · alt 2.80 m" },
                        { n: "Muro 4", d: "3.27 m · alt 2.80 m" },
                        { n: "Muro 5", d: "1.95 m · alt 2.80 m" },
                      ].map((m) => (
                        <div key={m.n} className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900/40 px-2 py-1.5">
                          <span className="h-3 w-3 shrink-0 rounded-sm border border-slate-600"></span>
                          <span className="h-2 w-2 shrink-0 rounded-full bg-green-500"></span>
                          <div className="min-w-0 flex-1">
                            <div className="text-[11px] font-medium text-slate-200">{m.n}</div>
                            <div className="text-[9px] text-slate-500">{m.d}</div>
                          </div>
                          <Trash2 className="h-3 w-3 shrink-0 text-slate-600" />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Canvas */}
                  <div className="relative min-w-0 flex-1 bg-slate-950 p-5">
                    <div className="absolute inset-0 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:24px_24px] opacity-40"></div>
                    <svg viewBox="0 0 400 300" className="relative w-full" role="img" aria-label="Plano analizado con detecciones de IA">
                      {/* Recintos (áreas detectadas) */}
                      <rect x="40" y="40" width="150" height="110" fill="rgba(14,165,233,0.10)" />
                      <rect x="40" y="150" width="150" height="110" fill="rgba(99,102,241,0.10)" />
                      <rect x="190" y="40" width="170" height="100" fill="rgba(56,189,248,0.10)" />
                      <rect x="190" y="140" width="170" height="120" fill="rgba(14,165,233,0.08)" />
                      {/* Muros detectados */}
                      <g stroke="#38bdf8" strokeWidth="3" fill="none" strokeLinecap="round">
                        <rect x="40" y="40" width="320" height="220" />
                        <line x1="190" y1="40" x2="190" y2="260" />
                        <line x1="40" y1="150" x2="190" y2="150" />
                        <line x1="190" y1="140" x2="360" y2="140" />
                      </g>
                      {/* Aberturas (puertas/ventanas) */}
                      <g stroke="#fbbf24" strokeWidth="3" strokeLinecap="round">
                        <line x1="95" y1="40" x2="135" y2="40" />
                        <line x1="190" y1="80" x2="190" y2="115" />
                        <line x1="115" y1="150" x2="150" y2="150" />
                        <line x1="260" y1="260" x2="300" y2="260" />
                      </g>
                      {/* Cotas */}
                      <g stroke="#64748b" strokeWidth="1" strokeDasharray="3 3">
                        <line x1="40" y1="278" x2="190" y2="278" />
                      </g>
                      <text x="95" y="292" fill="#94a3b8" fontSize="10">6.40 m</text>
                    </svg>

                    <div className="absolute left-9 top-9 flex items-center gap-1.5 rounded-md border border-brand-500/40 bg-brand-500/20 px-2 py-1 text-[10px] font-semibold text-brand-200 backdrop-blur-sm animate-float">
                      <span className="h-1.5 w-1.5 rounded-full bg-brand-400"></span> Muro · 4.64 m
                    </div>
                    <div className="absolute right-7 top-20 flex items-center gap-1.5 rounded-md border border-yellow-500/40 bg-yellow-500/20 px-2 py-1 text-[10px] font-semibold text-yellow-200 backdrop-blur-sm animate-float" style={{ animationDelay: '1.5s' }}>
                      <DoorOpen className="h-3 w-3" /> Abertura
                    </div>

                    {/* Bottom toolbar */}
                    <div className="absolute bottom-3 left-1/2 hidden -translate-x-1/2 items-center gap-3 rounded-full border border-slate-700 bg-slate-900/90 px-3 py-1.5 backdrop-blur-sm md:flex">
                      <Ruler className="h-3.5 w-3.5 text-slate-400" />
                      <PencilRuler className="h-3.5 w-3.5 text-brand-400" />
                      <DoorOpen className="h-3.5 w-3.5 text-slate-400" />
                      <span className="h-3 w-px bg-slate-700"></span>
                      <span className="text-[10px] text-slate-400">23%</span>
                    </div>
                  </div>

                  {/* Cómputo panel */}
                  <div className="hidden w-56 shrink-0 border-l border-slate-800 p-4 xl:block">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-sm font-semibold text-white">Cómputo</span>
                      <span className="rounded border border-green-500/30 bg-green-500/10 px-1.5 py-0.5 text-[9px] font-bold text-green-400">XLSX</span>
                    </div>
                    <p className="mb-3 text-[10px] text-slate-500">Página 2 · cantidades por material</p>

                    <div className="space-y-2">
                      {[
                        { icon: Layers, l: "Superficie", v: "312,5 m²" },
                        { icon: Ruler, l: "Mampostería", v: "142,0 ml" },
                        { icon: DoorOpen, l: "Aberturas", v: "14 u" },
                      ].map((row) => (
                        <div key={row.l} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                          <span className="flex items-center gap-2 text-[11px] text-slate-400">
                            <row.icon className="h-3.5 w-3.5 text-slate-500" /> {row.l}
                          </span>
                          <span className="text-xs font-semibold text-white">{row.v}</span>
                        </div>
                      ))}
                    </div>

                    <div className="mt-4 flex items-center gap-2 rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-[11px] font-semibold text-green-300">
                      <Check className="h-3.5 w-3.5" /> Listo para exportar
                    </div>
                    <button className="mt-2.5 flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-3 py-2 text-xs font-semibold text-white">
                      <Download className="h-3.5 w-3.5" /> Exportar
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="relative z-10 mx-auto max-w-7xl px-6 py-24 md:px-12 lg:px-24">
        <div className="text-center mb-16">
          <span className="text-sm font-semibold uppercase tracking-wider text-brand-400">Cómo funciona</span>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">De un PDF a tu presupuesto en 3 pasos</h2>
          <p className="mt-4 text-slate-400">Sin instalaciones, sin curva de aprendizaje.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 relative">
          {/* Connecting line (desktop) */}
          <div className="hidden md:block absolute top-8 left-[16.66%] right-[16.66%] h-px bg-gradient-to-r from-transparent via-slate-700 to-transparent"></div>

          {STEPS.map((step, i) => (
            <div key={step.title} className="relative flex flex-col items-center text-center">
              <div className="relative z-10 mb-6 flex h-16 w-16 items-center justify-center rounded-2xl border border-brand-500/30 bg-slate-900 shadow-lg shadow-brand-500/10">
                <step.icon className="h-7 w-7 text-brand-400" />
                <span className="absolute -top-2 -right-2 flex h-6 w-6 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">{i + 1}</span>
              </div>
              <h3 className="text-lg font-semibold text-white mb-2">{step.title}</h3>
              <p className="max-w-xs text-sm leading-relaxed text-slate-400">{step.desc}</p>
            </div>
          ))}
        </div>

        {/* Control manual / human-in-the-loop */}
        <div className="mt-16 flex flex-col items-center gap-5 rounded-3xl border border-brand-500/20 bg-brand-500/[0.04] p-8 text-center sm:flex-row sm:gap-6 sm:p-10 sm:text-left">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-brand-500/30 bg-slate-900">
            <PencilRuler className="h-7 w-7 text-brand-400" />
          </div>
          <div>
            <h3 className="text-xl font-semibold text-white">Vos tenés siempre la última palabra</h3>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-400">
              La IA hace el trabajo pesado, pero ningún resultado se exporta sin tu visto bueno. Si algo no quedó perfecto, podés ajustar cada muro, abertura o área a mano antes de generar el cómputo. Cero cajas negras: el control siempre es tuyo.
            </p>
          </div>
        </div>
      </section>

      {/* Feature Grids */}
      <section id="features" className="relative z-10 border-t border-slate-800/50 bg-slate-900/50 backdrop-blur-xl">
        <div className="mx-auto max-w-7xl px-6 py-24 md:px-12 lg:px-24">
          <div className="text-center mb-16">
            <span className="text-sm font-semibold uppercase tracking-wider text-brand-400">Por qué ScalistAI</span>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">No solo medís más rápido. Decidís mejor.</h2>
            <p className="mt-4 text-slate-400">El impacto real en tu estudio va más allá de automatizar tareas.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div className="group rounded-3xl border border-slate-800 bg-slate-900 p-8 transition hover:border-brand-500/50 hover:bg-slate-800/50">
              <div className="h-12 w-12 rounded-xl bg-brand-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                <Box className="h-6 w-6 text-brand-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-3">BIM nativo (IFC)</h3>
              <p className="text-slate-400 text-sm leading-relaxed">
                Subí el modelo de Revit o ArchiCAD y salteá el visor: el presupuesto sale directo del modelo, con fundaciones, armaduras en kilos, sanitarios y equipos incluidos. Nadie dibuja nada dos veces.
              </p>
            </div>

            <div className="group rounded-3xl border border-slate-800 bg-slate-900 p-8 transition hover:border-sky-500/50 hover:bg-slate-800/50">
              <div className="h-12 w-12 rounded-xl bg-sky-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                <Scale className="h-6 w-6 text-sky-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-3">Presupuesto honesto</h3>
              <p className="text-slate-400 text-sm leading-relaxed">
                El desglose separa lo que se computó <span className="text-slate-200 font-medium">exacto</span> del plano de lo que se <span className="text-slate-200 font-medium">estimó</span> — y te lo dice. Sin cajas negras ni doble conteo: sabés exactamente qué estás presentando.
              </p>
            </div>

            <div className="group rounded-3xl border border-slate-800 bg-slate-900 p-8 transition hover:border-indigo-500/50 hover:bg-slate-800/50">
              <div className="h-12 w-12 rounded-xl bg-indigo-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                <LineChart className="h-6 w-6 text-indigo-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-3">Precios reales, no índices</h3>
              <p className="text-slate-400 text-sm leading-relaxed">
                Relevamiento de precios de proveedores argentinos con historial y comparación contra la inflación. Cada material tiene fuente y fecha. Y podés cargar tus propios precios y recetas.
              </p>
            </div>

            <div className="group rounded-3xl border border-slate-800 bg-slate-900 p-8 transition hover:border-brand-500/50 hover:bg-slate-800/50">
              <div className="h-12 w-12 rounded-xl bg-brand-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                <Zap className="h-6 w-6 text-brand-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-3">De semanas a minutos</h3>
              <p className="text-slate-400 text-sm leading-relaxed">
                Lo que antes eran días de medición con escalímetro se resuelve en una sesión. Tu equipo dedica el tiempo a decidir y negociar, no a contar ladrillos.
              </p>
            </div>

            <div className="group rounded-3xl border border-slate-800 bg-slate-900 p-8 transition hover:border-sky-500/50 hover:bg-slate-800/50">
              <div className="h-12 w-12 rounded-xl bg-sky-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                <CalendarRange className="h-6 w-6 text-sky-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-3">Cronograma y curva de inversión</h3>
              <p className="text-slate-400 text-sm leading-relaxed">
                Del mismo cómputo sale el Gantt por etapas de obra y el flujo de fondos mensual (curva S), consistente al peso con el presupuesto. Ideal para bancos y fideicomisos.
              </p>
            </div>

            <div className="group rounded-3xl border border-slate-800 bg-slate-900 p-8 transition hover:border-indigo-500/50 hover:bg-slate-800/50">
              <div className="h-12 w-12 rounded-xl bg-indigo-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                <Lock className="h-6 w-6 text-indigo-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-3">Pensado para equipos</h3>
              <p className="text-slate-400 text-sm leading-relaxed">
                Multi-organización con datos aislados, control de roles y permisos, y catálogos de precios privados. Cada estudio con sus datos y su control.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Cotización */}
      <section id="cotizacion" className="relative z-10 mx-auto max-w-7xl scroll-mt-24 px-6 py-24 md:px-12 lg:px-24">
        <div className="text-center mb-14">
          <span className="text-sm font-semibold uppercase tracking-wider text-brand-400">Precios</span>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Armá tu cotización en 30 segundos
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-slate-400">
            Elegí usuarios, volumen y módulos: el precio se calcula al instante.
            Sin formularios eternos ni &quot;consultar precio&quot;.
          </p>
        </div>
        <QuoteCalculator />
      </section>

      {/* FAQ */}
      <section id="faq" className="relative z-10 mx-auto max-w-3xl px-6 py-24 md:px-12">
        <div className="text-center mb-12">
          <span className="text-sm font-semibold uppercase tracking-wider text-brand-400">Preguntas frecuentes</span>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">¿Tenés dudas? Las despejamos.</h2>
        </div>
        <div className="space-y-4">
          {FAQS.map((f) => (
            <FaqItem key={f.q} q={f.q} a={f.a} />
          ))}
        </div>
      </section>

      {/* CTA Bottom */}
      <section className="relative z-10 border-t border-slate-800 bg-slate-950 overflow-hidden">
        <div className="absolute inset-0 bg-brand-500/5"></div>
        <div className="mx-auto max-w-7xl px-6 py-24 md:px-12 lg:px-24 text-center">
          <h2 className="text-4xl font-bold tracking-tight text-white sm:text-5xl">Tu próximo presupuesto, en minutos</h2>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-slate-400">
            Traé un plano o un modelo BIM real de tu estudio y armamos la demo sobre tu propio proyecto. Vas a ver el presupuesto completo antes de que termine la reunión.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <a href="#cotizacion" className="inline-flex items-center justify-center rounded-full bg-white px-8 py-4 text-base font-bold text-slate-900 transition hover:bg-slate-200 hover:scale-105">
              Calcular mi precio
            </a>
            <a href="https://wa.me/549357161909" target="_blank" rel="noreferrer" className="inline-flex items-center justify-center rounded-full border border-slate-600 px-8 py-4 text-base font-semibold text-slate-200 transition hover:border-slate-400 hover:text-white">
              Hablemos por WhatsApp
            </a>
          </div>
        </div>
      </section>

      {/* Footer & Contact */}
      <footer className="relative z-10 border-t border-slate-800 bg-slate-950 pt-16 pb-8">
        <div className="mx-auto max-w-7xl px-6 md:px-12 lg:px-24">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 mb-12">
            <div>
              <div className="flex items-center gap-2 text-white font-bold text-xl mb-4">
                <div className="flex h-8 w-8 items-center justify-center overflow-hidden rounded">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src="/logo.png" alt="ScalistAI Logo" className="h-full w-full object-contain" />
                </div>
                ScalistAI
              </div>
              <p className="text-slate-400 max-w-sm">
                Cómputo y presupuesto de obra automático desde planos y modelos BIM,
                con precios reales de mercado. Para estudios y constructoras de Argentina.
              </p>
            </div>

            <div className="flex flex-col md:items-end gap-4">
              <h4 className="text-white font-semibold mb-2">Hablemos</h4>
              <a href="mailto:juanpilistte@gmail.com" className="flex items-center gap-3 text-slate-400 hover:text-brand-400 transition">
                <Mail className="h-5 w-5" />
                juanpilistte@gmail.com
              </a>
              <a href="https://wa.me/549357161909" target="_blank" rel="noreferrer" className="flex items-center gap-3 text-slate-400 hover:text-brand-400 transition">
                <Phone className="h-5 w-5" />
                +54 9 3571-61909
              </a>
              <a href="https://www.linkedin.com/in/juan-pablo-listte/" target="_blank" rel="noreferrer" className="flex items-center gap-3 text-slate-400 hover:text-brand-400 transition">
                <svg className="h-5 w-5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                </svg>
                LinkedIn
              </a>
            </div>
          </div>

          <div className="border-t border-slate-800 pt-8 flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-sm text-slate-500">
              © {new Date().getFullYear()} ScalistAI. Todos los derechos reservados.
            </p>
            <div className="flex gap-6 text-sm text-slate-500">
              <Link href="#" className="hover:text-slate-300">Términos</Link>
              <Link href="#" className="hover:text-slate-300">Privacidad</Link>
            </div>
          </div>
        </div>
      </footer>
    </main>
  );
}
