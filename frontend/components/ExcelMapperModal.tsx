import { useState, useEffect } from "react";
import * as XLSX from "xlsx";

type MaterialImportItem = {
  name: string;
  category: string;
  unit: string;
  unit_price: number;
};

export function ExcelMapperModal({
  file,
  onCancel,
  onMap,
}: {
  file: File;
  onCancel: () => void;
  onMap: (items: MaterialImportItem[]) => void;
}) {
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<any[][]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Mapeos (index de la columna)
  const [nameCol, setNameCol] = useState<number>(-1);
  const [catCol, setCatCol] = useState<number>(-1);
  const [unitCol, setUnitCol] = useState<number>(-1);
  const [priceCol, setPriceCol] = useState<number>(-1);

  useEffect(() => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = e.target?.result;
        const wb = XLSX.read(data, { type: "binary" });
        const wsName = wb.SheetNames[0];
        const ws = wb.Sheets[wsName];
        const json = XLSX.utils.sheet_to_json(ws, { header: 1 });
        
        if (json.length < 2) {
          setError("El archivo no tiene suficientes datos. Debe tener al menos una fila de encabezados y una de datos.");
          setLoading(false);
          return;
        }

        const head = json[0] as string[];
        const dataRows = json.slice(1) as any[][];
        setHeaders(head.map((h, i) => h ? String(h) : `Columna ${i + 1}`));
        setRows(dataRows.filter(r => r.length > 0 && r[0] != null));

        // Auto-guess columns based on text
        setNameCol(head.findIndex(h => /nombre|name|descrip|articulo|insumo/i.test(String(h))));
        setCatCol(head.findIndex(h => /cat|rubro|tipo/i.test(String(h))));
        setUnitCol(head.findIndex(h => /unid|u\.m\.|medida/i.test(String(h))));
        setPriceCol(head.findIndex(h => /precio|costo|valor|\$/i.test(String(h))));

        setLoading(false);
      } catch (err) {
        setError("Error al procesar el archivo Excel. Asegurate de que sea un .xlsx válido.");
        setLoading(false);
      }
    };
    reader.readAsBinaryString(file);
  }, [file]);

  function handleImport() {
    if (nameCol === -1) {
      setError("Debes seleccionar cuál columna corresponde al Nombre.");
      return;
    }

    const items: MaterialImportItem[] = [];
    for (const row of rows) {
      const name = String(row[nameCol] || "").trim();
      if (!name) continue;

      const category = catCol !== -1 ? String(row[catCol] || "").trim() : "General";
      const unit = unitCol !== -1 ? String(row[unitCol] || "").trim() : "un";
      
      let price = 0;
      if (priceCol !== -1) {
        const val = row[priceCol];
        const parsed = parseFloat(String(val).replace(/[^0-9.-]+/g,""));
        if (!isNaN(parsed)) price = parsed;
      }

      items.push({ name, category, unit, unit_price: price });
    }

    if (items.length === 0) {
      setError("No se encontraron datos válidos para importar.");
      return;
    }

    onMap(items);
  }

  if (loading) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/50 backdrop-blur-sm">
        <div className="rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-800">Cargando Excel...</div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-800 dark:border-slate-700">
        <h2 className="text-xl font-bold dark:text-white mb-1">Mapear Columnas</h2>
        <p className="text-sm text-slate-500 mb-6">Asociá las columnas de tu Excel con los datos del sistema. Mostramos la primera fila como ejemplo.</p>

        {error && <p className="mb-4 rounded bg-red-50 p-2 text-sm text-red-600 border border-red-200">{error}</p>}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <MappingSelect label="Nombre del Insumo *" val={nameCol} setVal={setNameCol} headers={headers} exampleRow={rows[0]} required />
          <MappingSelect label="Categoría" val={catCol} setVal={setCatCol} headers={headers} exampleRow={rows[0]} />
          <MappingSelect label="Unidad" val={unitCol} setVal={setUnitCol} headers={headers} exampleRow={rows[0]} />
          <MappingSelect label="Precio / Costo" val={priceCol} setVal={setPriceCol} headers={headers} exampleRow={rows[0]} />
        </div>

        <div className="mt-8 flex justify-end gap-3 pt-4 border-t border-slate-100 dark:border-slate-700">
          <button onClick={onCancel} className="rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700">Cancelar</button>
          <button onClick={handleImport} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-md hover:bg-brand-700">Importar {rows.length} insumos</button>
        </div>
      </div>
    </div>
  );
}

function MappingSelect({
  label, val, setVal, headers, exampleRow, required = false
}: { label: string, val: number, setVal: (n: number) => void, headers: string[], exampleRow: any[], required?: boolean }) {
  return (
    <div className="block text-sm">
      <span className={`font-semibold ${required ? "text-slate-800 dark:text-slate-200" : "text-slate-600 dark:text-slate-400"}`}>{label}</span>
      <select 
        value={val} 
        onChange={(e) => setVal(Number(e.target.value))}
        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-600 dark:bg-slate-900 dark:text-white"
      >
        <option value={-1}>-- No importar (Usar por defecto) --</option>
        {headers.map((h, i) => (
          <option key={i} value={i}>
            Columna: "{h}"
          </option>
        ))}
      </select>
      {val !== -1 && exampleRow && exampleRow[val] !== undefined && (
        <p className="mt-1 text-xs text-slate-500 italic">
          Ejemplo: {String(exampleRow[val])}
        </p>
      )}
    </div>
  );
}
