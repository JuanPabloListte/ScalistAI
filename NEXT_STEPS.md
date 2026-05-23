# Próximos pasos (post-revert, post-Etapas 1–5)

Backlog de lo que queda pendiente después del restablecimiento del visor y las 5 etapas de refactor del frontend (sidebar + dibujo persistente + multi-selección + materiales + cómputo + eliminar página).

Los items **no están priorizados** entre sí — son grupos accionables. Cada uno se puede tomar como una sub-tarea independiente.

> **Nota**: el [README.md](README.md) describe "Sprint 9" (selección múltiple con `Shift+click`/`Ctrl+A`/rubber-band) y "Sprint 10" (visor 3D con Three.js) como completados, pero esos features fueron escritos por una IA anterior y se revirtieron al inicio de esta sesión. Lo que figura en `main` hoy es la implementación del visor + materiales descrita más abajo, no esos sprints. El README necesita una pasada de actualización aparte.

---

## A. UX del visor — interacción con elementos en el canvas

Actualmente solo se interactúa con los elementos desde la lista del panel izquierdo. Lo natural es poder hacerlo también sobre el canvas.

- **Click en un elemento del canvas** → selecciona ese elemento (single).
- **Shift+click en el canvas** → agrega/quita de la selección múltiple.
- **Doble-click en un elemento del canvas** → abre su `InlineEditForm` (equivalente al chevron de la lista).
- **Cuadro de selección por drag** (rubber-band) cuando el tool es "pan" o un nuevo tool "select".
- **`Ctrl+A`** selecciona todos los elementos visibles de la página actual.
- **`Delete` / `Backspace`** elimina la selección activa (con la confirmación que ya existe).
- **Mover/editar vértices** de un elemento ya dibujado: drag handles sobre cada vértice cuando el elemento está seleccionado, persistir nueva geometría con `PATCH /elements/{id}`.

## B. Detección automática (IA)

Los endpoints ya existen en el backend pero el frontend no los usa todavía:

- `GET /api/v1/plans/{id}/detect-walls` — detección de muros (probablemente por OpenCV).
- `GET /api/v1/plans/{id}/detect-rooms` — detección de recintos.
- `GET /api/v1/plans/{id}/detect-openings` — detecta candidatos a puerta/ventana.
- `POST /api/v1/plans/{id}/openings-bulk` — crea N aberturas a partir de candidatos aceptados.

**UI propuesta**: bloque "Detección con IA" en el panel izquierdo o en un acordeón del visor con tres botones (Muros / Recintos / Aberturas). Cada uno trae candidatos como overlay con checkboxes; el usuario marca los que quiere y los crea en lote.

## C. Sincronización de datos

- **Catálogo de materiales en el visor** no se refresca si se crea un material desde `/materials` en otra pestaña. Opciones: revalidación on focus, o un broadcast simple con `localStorage` events.
- **Recalcular dimensiones desde geometría** después de re-calibrar una página: si hay elementos dibujados antes de la calibración correcta, sus `length_m`/`area_m2` están con la escala vieja. Ofrecer un botón "Recalcular dimensiones de esta página" después del re-calibrate.
- **Debounce de `PATCH /elements/{id}`** al editar inline: hoy cada `onBlur` dispara un fetch. Si el usuario tipea-blur-tipea-blur seguido, hay spam.
- **Optimistic updates** al asignar/desasignar material: hoy esperamos la respuesta del backend antes de actualizar el panel derecho.

## D. Auth / perfil

- **Página `/profile`** real (hoy el botón "Editar perfil" del ProfileMenu hace `alert("Editar perfil — próximamente")`). El backend ya tiene `GET /api/v1/auth/me` y `PATCH /api/v1/auth/update`.
- **Protección de rutas a nivel layout**: hoy cada página hace su propio `useEffect` + check 401. Centralizar en un guard (middleware Next.js o componente wrapper) que redirija a `/login` cuando no hay token.
- **Confirmación antes de "Cerrar sesión"** en el ProfileMenu (opcional — la mayoría de las apps no lo piden, decidir).

## E. Exportación

- **Botón "Exportar PDF"** en el visor: el endpoint `GET /api/v1/plans/{id}/export/pdf` existe pero no se usa. Hoy solo está el botón XLSX.
- **Import / Export Excel desde `/materials`**: endpoints `POST /api/v1/materials/import/excel` y `GET /api/v1/materials/export/xlsx` existen. Agregar dos botones en el header de la página de catálogo.

## F. Visor 3D

Era la feature original que arrancó toda esta refactorización (y que rompió el frontend cuando se intentó implementar la primera vez).

- Decidir si se re-introduce desde cero limpio (Three.js + `@react-three/fiber` v8 — `react-dom@18` compatible) o si se importa el componente del intento previo (preservado en `stash@{0}`).
- Punto de entrada: botón "Vista 3D" en la barra flotante del visor, alterna entre 2D y 3D.
- Renderizado: muros extruidos con `height_m`, aberturas como vacíos (puertas) o vidrios translúcidos (ventanas), suelos de recintos.
- Modos visuales sugeridos: "Blueprint" (oscuro con bordes cian) y "Render Blanco" (materiales blancos + iluminación suave).
- Necesita agregar deps: `three`, `@react-three/fiber@^8.17`, `@react-three/drei@^9.122`, `@types/three`.

## G. UX de carga / performance

- **Skeleton loaders** en lugar de los `Cargando...` actuales (lista de elementos, lista de materiales, summary).
- **Indicador de actividad** en el panel derecho cuando se recalcula el summary (hoy aparece `Calculando...` pero solo cubre el caso vacío).
- **Cache** del summary entre páginas: hoy cada cambio de página dispara un nuevo `GET /materials-summary`.

## H. Limpieza / mantenimiento

- **Actualizar el README.md**: hay desfasaje grande con la realidad del código (ver nota al principio de este archivo).
- **El `stash@{0}` con el backup pre-revert** sigue ahí (creado el 2026-05-23). Cuando confirmemos que no necesitamos rescatar nada, descartar con `git stash drop stash@{0}`.
- **Plan para el código del backend que no se usa desde el frontend nuevo**: services `wall_room_detection`, `opening_detection`, `dimension_text` — usados solo por endpoints que el frontend nuevo no consume todavía (se usarán en B y C).

---

## Decisiones pendientes — qué hablar antes de implementar

- ¿Vista 3D se reintroduce ya (alta visibilidad pero alto riesgo de regresión) o se posterga hasta tener los items A-D estables?
- Para "mover vértices" (A) — ¿drag handles visibles solo en el elemento seleccionado, o un modo dedicado "Editar geometría"?
- Para detección IA (B) — ¿confirmación visual (checkboxes sobre el plano) o acepta-todo + el usuario borra lo que sobra?
- Para recalcular dimensiones (C) — ¿automático al recalibrar, o opt-in con un botón explícito (más seguro contra perder ediciones manuales con badge "editado")?
