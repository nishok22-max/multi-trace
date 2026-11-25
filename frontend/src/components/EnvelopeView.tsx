import type { Schemas } from '../lib/api/client';
import { fmt } from '../lib/format';

/** The learned envelope behind a sensor verdict: quiet days, n, per-channel median and MAD, T*.
 *  Every figure is read from the engine's record; nothing is computed here. */
export default function EnvelopeView({ envelope }: { envelope: Schemas['Envelope'] }) {
  const thin = envelope.pooled !== 'none';
  return (
    <section aria-label="Envelope" data-testid="envelope-view" className="card card-pad stack-sm">
      <div>
        <p className="eyebrow">Learned envelope</p>
        <h2 className="title" style={{ margin: 0 }}>
          {envelope.machine} <span className="muted" style={{ fontWeight: 400 }}>· scope {envelope.scope.join(', ')}</span>
        </h2>
      </div>
      <dl className="kv kv-wide">
        <dt>Quiet days (n)</dt>
        <dd data-testid="env-n">{envelope.n}</dd>
        <dt>T* (threshold)</dt>
        <dd data-testid="env-tstar">{fmt(envelope.T_star)}</dd>
        <dt>Statistic</dt>
        <dd>
          {envelope.statistic}/{envelope.granularity}
        </dd>
        <dt>Pooling</dt>
        <dd>{thin ? `thin history / model-level (${envelope.pooled})` : 'own history'}</dd>
      </dl>
      {envelope.degenerate_channels.length > 0 ? (
        <p className="callout callout-warn">Degenerate scale (excluded): {envelope.degenerate_channels.join(', ')}</p>
      ) : null}
      <div className="table-wrap">
        <table className="t">
          <thead>
            <tr>
              <th>Channel</th>
              <th className="n">Median</th>
              <th className="n">MAD</th>
            </tr>
          </thead>
          <tbody>
            {envelope.scope.map((c) => (
              <tr key={c}>
                <td className="m">{c}</td>
                <td className="n">{fmt(envelope.med[c])}</td>
                <td className="n">{fmt(envelope.mad[c])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details>
        <summary>Quiet-day list ({envelope.quiet_days.length})</summary>
        <ul className="mono small" style={{ maxHeight: 192, overflow: 'auto', margin: '8px 0 0', paddingLeft: 18 }} data-testid="quiet-days">
          {envelope.quiet_days.map((d) => (
            <li key={d.date}>
              {d.date} · T_d {fmt(d.t_d)}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
