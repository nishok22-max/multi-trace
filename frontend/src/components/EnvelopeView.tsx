import type { Schemas } from '../lib/api/client';
import { fmt } from '../lib/format';

/** The learned envelope behind a sensor verdict: quiet days, n, per-channel median and MAD, T*.
 *  Every figure is read from the engine's record; nothing is computed here. */
export default function EnvelopeView({ envelope }: { envelope: Schemas['Envelope'] }) {
  const thin = envelope.pooled !== 'none';
  return (
    <section aria-label="Envelope" data-testid="envelope-view" className="rounded border border-slate-400 bg-white p-3">
      <h3 className="font-semibold">
        Envelope for {envelope.machine} · scope {envelope.scope.join(', ')}
      </h3>
      <dl className="my-2 grid grid-cols-2 gap-x-3 text-sm md:grid-cols-4">
        <dt>Quiet days (n)</dt>
        <dd data-testid="env-n" className="font-mono">{envelope.n}</dd>
        <dt>T* (threshold)</dt>
        <dd data-testid="env-tstar" className="font-mono">{fmt(envelope.T_star)}</dd>
        <dt>Statistic</dt>
        <dd className="font-mono">{envelope.statistic}/{envelope.granularity}</dd>
        <dt>Pooling</dt>
        <dd className="font-mono">{thin ? `thin history / model-level (${envelope.pooled})` : 'own history'}</dd>
      </dl>
      {envelope.degenerate_channels.length > 0 ? (
        <p className="text-sm">Degenerate scale (excluded): {envelope.degenerate_channels.join(', ')}</p>
      ) : null}
      <table className="mb-2 w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-slate-400">
            <th className="py-1 pr-2">Channel</th>
            <th className="py-1 pr-2">Median</th>
            <th className="py-1">MAD</th>
          </tr>
        </thead>
        <tbody>
          {envelope.scope.map((c) => (
            <tr key={c} className="border-b border-slate-200">
              <td className="py-1 pr-2 font-mono">{c}</td>
              <td className="py-1 pr-2 font-mono">{fmt(envelope.med[c])}</td>
              <td className="py-1 font-mono">{fmt(envelope.mad[c])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details>
        <summary className="cursor-pointer text-sm font-semibold">Quiet-day list ({envelope.quiet_days.length})</summary>
        <ul className="max-h-48 overflow-auto font-mono text-xs" data-testid="quiet-days">
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
