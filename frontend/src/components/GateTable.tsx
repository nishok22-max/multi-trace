import type { Schemas } from '../lib/api/client';

const NAMES: Record<Schemas['GateCheck']['name'], string> = {
  same_entity: 'Same entity',
  same_attribute: 'Same attribute',
  time_overlap: 'Same time',
  comparable_terms: 'Comparable terms',
  data_both_sides: 'Data on both sides',
  beyond_variation: 'Beyond normal variation',
};
const ORDER = Object.keys(NAMES) as Schemas['GateCheck']['name'][];
const MARK = { Passed: '✓', Failed: '✕', 'Not run': '–' } as const;

/** All six checks in order. A check the gate never reached is shown as "not run". */
export default function GateTable({ checks }: { checks: Schemas['GateCheck'][] }) {
  return (
    <div className="table-wrap">
      <table data-testid="gate-table" className="t">
        <caption className="sr-only">Comparability gate, six checks</caption>
        <thead>
          <tr>
            <th className="n">#</th>
            <th>Check</th>
            <th>Result</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {ORDER.map((name, index) => {
            const check = checks.find((c) => c.name === name);
            const result = check === undefined ? 'Not run' : check.pass ? 'Passed' : 'Failed';
            return (
              <tr key={name}>
                <td className="n">{index + 1}</td>
                <td>{NAMES[name]}</td>
                <td>
                  <span className="result" data-result={result}>
                    <span aria-hidden="true">{MARK[result]}</span>
                    {result}
                  </span>
                </td>
                <td className="muted">{check?.detail ?? ''}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
