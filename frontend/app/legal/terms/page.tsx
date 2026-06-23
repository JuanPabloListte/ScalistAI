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
              En ScalistAI entendemos que los planos arquitectónicos y los diseños son propiedad intelectual confidencial de tu estudio y tus clientes (usualmente protegidos bajo NDAs). Mantenemos la confidencialidad estricta de todos los documentos originales subidos a la plataforma.
            </p>
          </section>

          <section>
            <h2 className="mb-3 text-xl font-semibold text-slate-800 dark:text-slate-100">
              2. Entrenamiento del Modelo (Opt-Out)
            </h2>
            <p className="mb-3">
              Si elegís dejarnos usar tus datos para entrenamiento (mediante la casilla correspondiente al crear un proyecto), ScalistAI procesará la geometría básica (líneas de muros, recintos y aberturas) para generar "variaciones sintéticas".
            </p>
            <p>
              <strong>¿Qué significa esto?</strong> Significa que nunca usaremos tus planos reales ni tu nombre. Extraemos exclusivamente las coordenadas geométricas puras, las distorsionamos aleatoriamente, y las usamos como casos de prueba anónimos para enseñarle a la Inteligencia Artificial a reconocer muros con mayor precisión.
            </p>
          </section>

          <section>
            <h2 className="mb-3 text-xl font-semibold text-slate-800 dark:text-slate-100">
              3. Anonimización Garantizada
            </h2>
            <p>
              Toda la información que pueda identificar a un cliente, como los cajetines, rótulos, direcciones, nombres de proyectos, textos descriptivos, y cotas numéricas, <strong>es ignorada y destruida</strong> antes de que la geometría entre al motor de entrenamiento. El modelo solo ve "líneas blancas sobre fondo negro".
            </p>
          </section>

          <section>
            <h2 className="mb-3 text-xl font-semibold text-slate-800 dark:text-slate-100">
              4. Revocación del Consentimiento
            </h2>
            <p>
              Podés elegir no participar en este programa en cualquier momento desmarcando la casilla de entrenamiento al crear un proyecto, o desactivándolo desde la configuración del proyecto. Si lo hacés, tus planos quedarán en un entorno aislado (Sandboxed) y no contribuirán al modelo global de ScalistAI.
            </p>
          </section>

          <div className="mt-8 border-t border-slate-200 pt-8 dark:border-slate-800">
            <p className="text-sm">
              Al usar ScalistAI, aceptás que estos términos puedan actualizarse periódicamente. Te notificaremos de cambios sustanciales a través de la plataforma.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
