import type { Schemas } from '../lib/api/client';
import { fmt } from '../lib/format';

/** The top candidates for an ambiguous mention with their per-feature scores and reasons.
 *  All text is rendered as text nodes (mentions and reasons come from documents). */
export default function CandidateList({ candidates }: { candidates: Schemas['Candidate'][] }) {
  return (
    <table data-testid="candidate-list" className="w-full border-collapse text-left text-sm">
      <caption className="pb-1 text-left font-semibold">Candidates (top {candidates.length})</caption>
      <thead>
        <tr className="border-b border-slate-400">
          <th className="py-1 pr-2">Entity</th>
          <th className="py-1 pr-2">Score</th>
          <th className="py-1 pr-2">Features</th>
          <th className="py-1">Why</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((c) => (
          <tr key={c.entity_id} data-testid="candidate" data-vetoed={c.vetoed ? 'true' : undefined} className="border-b border-slate-200 align-top">
            <td className="py-1 pr-2 font-mono">
              {c.entity_id}
              {c.vetoed ? (
                <span className="ml-1 rounded bg-red-100 px-1 text-xs font-semibold text-red-900">vetoed</span>
              ) : null}
            </td>
            <td className="py-1 pr-2 font-mono">{fmt(c.score)}</td>
            <td className="py-1 pr-2 font-mono text-xs">
              {Object.entries(c.features ?? {})
                .map(([k, v]) => `${k} ${fmt(v)}`)
                .join(' · ')}
            </td>
            <td className="py-1 text-xs">{(c.reasons ?? []).join('; ')}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
