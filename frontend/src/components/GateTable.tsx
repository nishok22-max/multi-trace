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

/** All six checks in order. A check the gate never reached is shown as "not run". */
export default function GateTable({ checks }: { checks: Schemas['GateCheck'][] }) {
  return (
    <table data-testid="gate-table" className="w-full border-collapse text-left text-sm">
      <caption className="pb-1 text-left font-semibold">Comparability gate (6 checks)</caption>
      <thead>
        <tr className="border-b border-slate-400">
          <th className="py-1 pr-2">#</th>
          <th className="py-1 pr-2">Check</th>
          <th className="py-1 pr-2">Result</th>
          <th className="py-1">Detail</th>
        </tr>
      </thead>
      <tbody>
        {ORDER.map((name, index) => {
          const check = checks.find((c) => c.name === name);
          const result = check === undefined ? 'Not run' : check.pass ? 'Passed' : 'Failed';
          return (
            <tr key={name} className="border-b border-slate-200 align-top">
              <td className="py-1 pr-2 font-mono">{index + 1}</td>
              <td className="py-1 pr-2">{NAMES[name]}</td>
              <td className="py-1 pr-2 font-semibold" data-result={result}>
                {result}
              </td>
              <td className="py-1">{check?.detail ?? ''}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
