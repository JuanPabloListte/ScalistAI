export default function TermsAndConditions() {
  return (
    <div className="min-h-screen bg-slate-50 py-12 px-4 sm:px-6 lg:px-8 dark:bg-slate-950">
      <div className="mx-auto max-w-3xl rounded-xl bg-white p-8 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
        <h1 className="mb-6 text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
          Términos y Condiciones de Uso de Datos
        </h1>
        
        <div className="space-y-6 text-slate-600 dark:text-slate-300">
          <p>
            Última actualización: {new Date().toLocaleDateString('es-AR')}
          </p>

          <section>
            <h2 className="mb-3 text-xl font-semibold text-slate-800 dark:text-slate-100">
              1. Privacidad y Propiedad Intelectual
            </h2>
            <p className="mb-3">
              En Scalist entendemos que los planos arquitectónicos y los diseños son propiedad intelectual confidencial de tu estudio y tus clientes (usualmente protegidos bajo NDAs). Mantenemos la confidencialidad estricta de todos los documentos originales subidos a la plataforma.
            </p>
          </section>

          <section>
            <h2 className="mb-3 text-xl font-semibold text-slate-800 dark:text-slate-100">
              2. Uso de los datos
            </h2>
            <p>
              Los modelos BIM y los presupuestos de proveedores que subís se usan únicamente para calcular el cómputo y el presupuesto de tu proyecto. No los usamos para otros fines.
            </p>
          </section>

          <div className="mt-8 border-t border-slate-200 pt-8 dark:border-slate-800">
            <p className="text-sm">
              Al usar Scalist, aceptás que estos términos puedan actualizarse periódicamente. Te notificaremos de cambios sustanciales a través de la plataforma.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
