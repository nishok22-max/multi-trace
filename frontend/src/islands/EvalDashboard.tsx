import { useQuery } from '@tanstack/react-query';
import Nav from '../components/Nav';
import { api, ApiError, unwrap, type Schemas } from '../lib/api/client';
import { fmt } from '../lib/format';
import { keys } from '../lib/query/keys';
import Providers, { ErrorNote, Loading } from './Providers';

type Wilson = Schemas['Wilson'];

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function ci(w: Wilson): string {
  return `${pct(w.point)} (95% CI ${pct(w.lower)} to ${pct(w.upper)}, n = ${w.n})`;
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2>{title}</h2>
        {note ? <span className="aside small muted">{note}</span> : null}
      </div>
      <div className="card-body stack-sm">{children}</div>
    </section>
  );
}

function Stat({ label, value, detail, testId }: { label: string; value: string; detail: string; testId?: string }) {
  return (
    <div className="stat" data-testid={testId}>
      <div className="v">{value}</div>
      <div className="l">{label}</div>
      <div className="ci">{detail}</div>
    </div>
  );
}

function Report({ r, superseded }: { r: Schemas['EvalReport']; superseded: boolean }) {
  const calibrated = r.ece_after !== null && r.ece_after !== undefined;
  return (
    <div className="stack" data-testid="report">
      {superseded ? (
        <p role="alert" data-testid="superseded" className="callout callout-bad">
          Superseded: this report was made by another version of the engine than the one running now. Its numbers describe that engine, not this one.
        </p>
      ) : null}
      <div className="actions">
        <span data-testid="split" className="badge badge-info">
          {r.split}
        </span>
        <span className="badge badge-note">planted faults</span>
        <span className={`badge ${calibrated ? 'badge-ok' : 'badge-warn'}`}>{calibrated ? 'calibrated' : 'uncalibrated'}</span>
        <span className="small muted">
          run {r.run_id} · config <span className="mono">{r.config_hash.slice(0, 12)}</span> · engine <span className="mono">{r.engine_sha.slice(0, 12)}</span>
        </span>
      </div>

      <Section title="Conflict detection" note="Planted conflicts, scored per fault type">
        <p className="small" style={{ margin: 0 }} data-testid="overall">
          Overall (planted conflicts): precision {fmt(r.overall.precision)} · recall {fmt(r.overall.recall)} · F1 {fmt(r.overall.f1)} · n {r.overall.n}
        </p>
        <div className="table-wrap">
          <table className="t" data-testid="per-fault">
            <caption className="sr-only">Per fault type</caption>
            <thead>
              <tr>
                <th>Fault</th>
                <th className="n">Precision</th>
                <th className="n">Recall</th>
                <th className="n">F1</th>
                <th className="n">n</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(r.per_fault).map(([name, p]) => (
                <tr key={name} data-testid="fault-row">
                  <td>{name}</td>
                  <td className="n">{fmt(p.precision)}</td>
                  <td className="n">{fmt(p.recall)}</td>
                  <td className="n">{fmt(p.f1)}</td>
                  <td className="n">{p.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Rates" note="Every rate carries its Wilson 95% interval">
        <div className="stats">
          <Stat testId="false-conflicts" label="False conflicts on non-comparable pairs" value={pct(r.false_conflict_rate.point)} detail={ci(r.false_conflict_rate)} />
          <Stat testId="false-alarm" label="Quiet-day false alarms" value={pct(r.quiet_day_false_alarm.point)} detail={ci(r.quiet_day_false_alarm)} />
          <Stat label="Entity linking, top 1" value={pct(r.entity_accuracy_at1)} detail={`top 3: ${pct(r.entity_accuracy_at3)}`} />
          <Stat label="Provenance that re-resolves" value={pct(r.provenance_reresolve_rate)} detail="every pointer re-checked" />
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          Extraction accuracy:{' '}
          {Object.entries(r.extraction_accuracy)
            .map(([m, v]) => `${m} ${pct(v)}`)
            .join(' · ')}
        </p>
        <p className="callout" data-testid="invariants" style={{ margin: 0 }}>
          Invariants: Gaps read as normal: <strong>{r.gaps_read_as_normal}</strong> · averaged outputs: <strong>{r.averaged_outputs}</strong>
        </p>
      </Section>

      <Section title="Confidence and calibration">
        <p className="small" style={{ margin: 0 }} data-testid="calibration">
          ECE {fmt(r.ece_before)} before calibration, {calibrated ? fmt(r.ece_after) : 'not fitted yet'} after · Brier {fmt(r.brier_before)} before,{' '}
          {calibrated ? fmt(r.brier_after) : 'not fitted yet'} after. Scores are uncalibrated until a calibration fit exists.
        </p>
        <div className="table-wrap">
          <table className="t" data-testid="bins">
            <caption className="sr-only">Accuracy per confidence bin (empty bins are shown, not filled)</caption>
            <thead>
              <tr>
                <th>Confidence bin</th>
                <th className="n">n</th>
                <th className="n">Mean confidence</th>
                <th className="n">Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {r.bins.map((b) => (
                <tr key={b.lo} data-testid="bin-row" data-n={b.n}>
                  <td className="m">
                    {fmt(b.lo)} to {fmt(b.hi)}
                  </td>
                  <td className="n">{b.n}</td>
                  <td className="n">{b.n > 0 ? fmt(b.mean_confidence) : 'no data'}</td>
                  <td className="n">{b.n > 0 ? fmt(b.accuracy) : 'no data'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          Empty bins are shown, not filled.
        </p>
      </Section>

      <Section title="Baselines" note="Their actual output on the same planted faults">
        <ul className="stack-sm" style={{ listStyle: 'none', margin: 0, padding: 0 }} data-testid="baselines">
          {r.baselines.map((b) => (
            <li key={b.name} data-testid="baseline" data-name={b.name} className="claim">
              <h3>{b.name}</h3>
              <p style={{ margin: '0 0 8px' }}>{b.answer_text}</p>
              <p className="small muted" style={{ margin: 0 }}>
                score {fmt(b.score)} · {b.surfaced_conflict ? 'surfaced the conflict' : 'did not surface the conflict'} ·{' '}
                {b.provenance_correct ? 'provenance correct' : 'provenance not correct'}
              </p>
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
    <>
      <div className="page-head">
        <div>
          <h1>Evaluation</h1>
          <p className="sub">How well the engine finds planted conflicts, and how honest its confidence is.</p>
        </div>
      </div>
      {report.isLoading ? <Loading what="evaluation" /> : null}
      {none ? (
        <p data-testid="no-report" className="card empty">
          No evaluation has been run yet. Dev results appear here after <code>make eval-dev</code> or a run from the API; the holdout is run once, at the end.
        </p>
      ) : denied ? (
        <p data-testid="eval-denied" role="alert" className="card empty">
          The evaluation report is for the evaluator role.
        </p>
      ) : report.error ? (
        <ErrorNote error={report.error} />
      ) : null}
      {report.data ? <Report r={report.data.report} superseded={report.data.superseded} /> : null}
    </>
  );
}

export default function EvalDashboard() {
  return (
    <Providers>
      <Nav />
      <Dashboard />
    </Providers>
  );
}
