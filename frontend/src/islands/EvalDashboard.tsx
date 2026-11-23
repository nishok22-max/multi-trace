import { useQuery } from '@tanstack/react-query';
import Nav from '../components/Nav';
import { api, ApiError, unwrap } from '../lib/api/client';
import { fmt } from '../lib/format';
import { keys } from '../lib/query/keys';
import Providers, { ErrorNote } from './Providers';

function Dashboard() {
  const report = useQuery({
    queryKey: keys.evalReport(),
    queryFn: async () => unwrap(await api.GET('/api/v1/eval/report')),
  });
  const none = report.error instanceof ApiError && report.error.status === 404;
  const r = report.data;
  return (
    <div>
      <Nav />
      <h1 className="mb-3 text-2xl font-bold">Evaluation</h1>
      {none ? (
        <p data-testid="no-report" className="rounded border border-slate-400 bg-white p-3">
          No evaluation has been run yet. Dev results appear here after <code>make eval-dev</code>; the holdout is run once, at the end.
        </p>
      ) : report.error ? (
        <ErrorNote error={report.error} />
      ) : null}
      {r ? (
        <div className="space-y-3" data-testid="report">
          <p className="text-sm">
            Split <span className="rounded bg-slate-200 px-1 font-semibold">{r.split}</span> · run {r.run_id} · config{' '}
            <span className="font-mono">{r.config_hash.slice(0, 12)}</span>
          </p>
          <table className="w-full border-collapse text-left text-sm">
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
                <tr key={name} className="border-b border-slate-200">
                  <td className="py-1">{name}</td>
                  <td className="font-mono">{fmt(p.precision)}</td>
                  <td className="font-mono">{fmt(p.recall)}</td>
                  <td className="font-mono">{fmt(p.f1)}</td>
                  <td className="font-mono">{p.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-sm" data-testid="false-alarm">
            Quiet-day false alarms: {fmt(r.quiet_day_false_alarm.point)} (95% CI {fmt(r.quiet_day_false_alarm.lower)} to {fmt(r.quiet_day_false_alarm.upper)}, n = {r.quiet_day_false_alarm.n})
          </p>
          <p className="text-sm">
            Entity accuracy @1 {fmt(r.entity_accuracy_at1)} · @3 {fmt(r.entity_accuracy_at3)} · gaps read as normal {r.gaps_read_as_normal} · averaged outputs {r.averaged_outputs}
          </p>
          <p className="text-sm">Scores are uncalibrated until a calibration fit exists.</p>
        </div>
      ) : null}
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
