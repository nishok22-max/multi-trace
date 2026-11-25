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
    <div className="table-wrap" style={{ maxHeight: 288 }} data-testid="table-window">
      <table className="t">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
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
                    className={`m ${cited ? 'cell-cited' : ''} ${cited && c === citedColumn ? 'cell-hit' : ''}`}
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
