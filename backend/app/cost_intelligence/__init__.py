"""Bounded context: Motor de Inteligencia de Costos.

Evoluciona el cómputo estático (materiales + presupuesto) hacia una plataforma
de simulación: comparación de materiales alternativos, escenarios constructivos
y proyección de costos futuros.

Arquitectura limpia en capas (ver docs/cost-intelligence/README.md):
    domain/         reglas y value objects puros (sin SQLAlchemy)
    application/    casos de uso + puertos (interfaces)
    infrastructure/ adapters: repos SQLAlchemy, forecasting, feeds, anti-corruption
    interface/      routers FastAPI + DTOs

La app actual (Material/Assembly/_get_materials_summary_data/schedule.py) se
integra por la capa anti-corrupción; NO se reescribe.
"""
