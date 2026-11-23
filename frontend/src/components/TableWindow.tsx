import { useEffect, useRef } from 'react';

type Row = Record<string, string | number | null>;

/** The cited log rows (+/-25) with the cited cell highlighted and scrolled into view. */
export default function TableWindow({ rows, citedRow, citedColumn }: { rows: Row[]; citedRow: number; citedColumn: string }) {
  const target = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    target.current?.scrollIntoView({ block: 'center' });
  }, [rows, citedRow]);
  const columns = rows[0] ? Object.keys(rows[0]) : [];
  return (
    <div className="max-h-72 overflow-auto border border-slate-400" data-testid="table-window">
      <table className="w-full border-collapse text-left font-mono text-xs">
        <thead className="sticky top-0 bg-slate-100">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-2 py-1">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const cited = row['row'] === citedRow;
            return (
              <tr key={String(row['row'])} ref={cited ? target : null} data-cited={cited ? 'true' : undefined}>
                {columns.map((c) => (
                  <td
                    key={c}
                    data-cited-cell={cited && c === citedColumn ? 'true' : undefined}
                    className={`px-2 py-0.5 ${cited ? 'bg-amber-100' : ''} ${cited && c === citedColumn ? 'font-bold outline outline-2 outline-red-600' : ''}`}
                  >
                    {String(row[c] ?? '')}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
