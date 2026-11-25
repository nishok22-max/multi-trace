import type { Schemas } from '../lib/api/client';
import { fmt } from '../lib/format';

/** The top candidates for an ambiguous mention with their per-feature scores and reasons.
 *  All text is rendered as text nodes (mentions and reasons come from documents). */
export default function CandidateList({ candidates }: { candidates: Schemas['Candidate'][] }) {
  return (
    <section className="card card-pad" aria-label="Candidates">
      <p className="eyebrow">Candidate machines (top {candidates.length})</p>
      <div className="table-wrap">
        <table data-testid="candidate-list" className="t">
          <thead>
            <tr>
              <th>Machine</th>
              <th className="n">Score</th>
              <th>Features</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={c.entity_id} data-testid="candidate" data-vetoed={c.vetoed ? 'true' : undefined}>
                <td className="m">
                  {c.entity_id} {c.vetoed ? <span className="badge badge-bad">vetoed</span> : null}
                </td>
                <td className="n">{fmt(c.score)}</td>
                <td className="m muted">
                  {Object.entries(c.features ?? {})
                    .map(([k, v]) => `${k} ${fmt(v)}`)
                    .join(' · ')}
                </td>
                <td className="small">{(c.reasons ?? []).join('; ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
