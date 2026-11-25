import { useQuery } from '@tanstack/react-query';
import Nav from '../components/Nav';
import { api, ApiError, unwrap, type Schemas } from '../lib/api/client';
import { fmt } from '../lib/format';
import { keys } from '../lib/query/keys';
import Providers, { ErrorNote } from './Providers';

type Wilson = Schemas['Wilson'];

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function ci(w: Wilson): string {
  return `${pct(w.point)} (95% CI ${pct(w.lower)} to ${pct(w.upper)}, n = ${w.n})`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded border border-slate-400 bg-white p-3">
      <h2 className="mb-2 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Report({ r, superseded }: { r: Schemas['EvalReport']; superseded: boolean }) {
  const calibrated = r.ece_after !== null && r.ece_after !== undefined;
  return (
    <div className="space-y-4" data-testid="report">
      {superseded ? (
        <p role="alert" data-testid="superseded" className="rounded border-2 border-red-700 bg-red-50 p-3 font-semibold text-red-900">
          Superseded: this report was made by another version of the engine than the one running now. Its numbers describe that
          engine, not this one.
        </p>
      ) : null}
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span data-testid="split" className="rounded bg-slate-200 px-1 font-semibold">
          {r.split}
        </span>
        <span className="rounded bg-purple-100 px-1 font-semibold text-purple-900">planted faults</span>
        <span className="rounded bg-amber-100 px-1 font-semibold text-amber-900">
          {calibrated ? 'calibrated' : 'uncalibrated'}
        </span>
        <span>
          run {r.run_id} · config <span className="font-mono">{r.config_hash.slice(0, 12)}</span> · engine{' '}
          <span className="font-mono">{r.engine_sha.slice(0, 12)}</span>
        </span>
      </p>

      <Section title="Conflict detection">
        <p className="mb-2 text-sm" data-testid="overall">
          Overall (planted conflicts): precision {fmt(r.overall.precision)} · recall {fmt(r.overall.recall)} · F1 {fmt(r.overall.f1)} · n {r.overall.n}
        </p>
        <table className="w-full border-collapse text-left text-sm" data-testid="per-fault">
          <caption className="pb-1 text-left font-semibold">Per fault type</caption>
          <thead>
            <tr className="border-b border-slate-400">
              <th className="py-1">Fault</th>
              <th>Precision</th>
              <th>Recall</th>
              <th>F1</th>
              <th>n</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(r.per_fault).map(([name, p]) => (
              <tr key={name} className="border-b border-slate-200" data-testid="fault-row">
                <td className="py-1">{name}</td>
                <td className="font-mono">{fmt(p.precision)}</td>
                <td className="font-mono">{fmt(p.recall)}</td>
                <td className="font-mono">{fmt(p.f1)}</td>
                <td className="font-mono">{p.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Rates, with Wilson 95% intervals">
        <ul className="space-y-1 text-sm">
          <li data-testid="false-conflicts">False conflicts on non-comparable pairs: {ci(r.false_conflict_rate)}</li>
          <li data-testid="false-alarm">Quiet-day false alarms: {ci(r.quiet_day_false_alarm)}</li>
          <li>
            Entity linking: accuracy@1 {pct(r.entity_accuracy_at1)} · accuracy@3 {pct(r.entity_accuracy_at3)}
          </li>
          <li>
            Extraction accuracy:{' '}
            {Object.entries(r.extraction_accuracy)
              .map(([m, v]) => `${m} ${pct(v)}`)
              .join(' · ')}
          </li>
          <li>Provenance that re-resolves: {pct(r.provenance_reresolve_rate)}</li>
          <li data-testid="invariants">
            Gaps read as normal: <strong>{r.gaps_read_as_normal}</strong> · averaged outputs: <strong>{r.averaged_outputs}</strong>
          </li>
        </ul>
      </Section>

      <Section title="Confidence and calibration">
        <p className="mb-2 text-sm" data-testid="calibration">
          ECE {fmt(r.ece_before)} before calibration, {calibrated ? fmt(r.ece_after) : 'not fitted yet'} after · Brier {fmt(r.brier_before)} before,{' '}
          {calibrated ? fmt(r.brier_after) : 'not fitted yet'} after. Scores are uncalibrated until a calibration fit exists.
        </p>
        <table className="w-full border-collapse text-left text-sm" data-testid="bins">
          <caption className="pb-1 text-left font-semibold">Accuracy per confidence bin (empty bins are shown, not filled)</caption>
          <thead>
            <tr className="border-b border-slate-400">
              <th className="py-1">Bin</th>
              <th>n</th>
              <th>Mean confidence</th>
              <th>Accuracy</th>
            </tr>
          </thead>
          <tbody>
            {r.bins.map((b) => (
              <tr key={b.lo} className="border-b border-slate-200" data-testid="bin-row" data-n={b.n}>
                <td className="py-1 font-mono">
                  {fmt(b.lo)} to {fmt(b.hi)}
                </td>
                <td className="font-mono">{b.n}</td>
                <td className="font-mono">{b.n > 0 ? fmt(b.mean_confidence) : 'no data'}</td>
                <td className="font-mono">{b.n > 0 ? fmt(b.accuracy) : 'no data'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Baselines on the same planted faults (their actual output)">
        <ul className="space-y-2 text-sm" data-testid="baselines">
          {r.baselines.map((b) => (
            <li key={b.name} data-testid="baseline" data-name={b.name} className="rounded border border-slate-300 p-2">
              <strong>{b.name}</strong>: <span>{b.answer_text}</span>
              <br />
              <span className="text-xs">
                score {fmt(b.score)} · {b.surfaced_conflict ? 'surfaced the conflict' : 'did not surface the conflict'} ·{' '}
                {b.provenance_correct ? 'provenance correct' : 'provenance not correct'}
              </span>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

function Dashboard() {
  const report = useQuery({
    queryKey: keys.evalReport(),
    queryFn: async () => {
      const res = await api.GET('/api/v1/eval/report');
      return { report: unwrap(res), superseded: res.response.headers.get('x-report-superseded') === 'true' };
    },
  });
  const none = report.error instanceof ApiError && report.error.status === 404;
  const denied = report.error instanceof ApiError && report.error.status === 403;
  return (
    <div>
      <Nav />
      <h1 className="mb-3 text-2xl font-bold">Evaluation</h1>
      {none ? (
        <p data-testid="no-report" className="rounded border border-slate-400 bg-white p-3">
          No evaluation has been run yet. Dev results appear here after <code>make eval-dev</code> or a run from the API; the holdout is run once, at the end.
        </p>
      ) : denied ? (
        <p data-testid="eval-denied" role="alert" className="rounded border border-slate-400 bg-white p-3">
          The evaluation report is for the evaluator role.
        </p>
      ) : report.error ? (
        <ErrorNote error={report.error} />
      ) : null}
      {report.data ? <Report r={report.data.report} superseded={report.data.superseded} /> : null}
    </div>
  );
}

export default function EvalDashboard() {
  return (
    <Providers>
      <Dashboard />
    </Providers>
  );
}
