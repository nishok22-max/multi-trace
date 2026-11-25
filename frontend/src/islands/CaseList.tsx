import { useQuery } from '@tanstack/react-query';
import Nav from '../components/Nav';
import { api, unwrap } from '../lib/api/client';
import { localDateTime } from '../lib/format';
import { keys } from '../lib/query/keys';
import Providers, { ErrorNote, Loading } from './Providers';

function List() {
  const cases = useQuery({
    queryKey: keys.cases(),
    queryFn: async () => unwrap(await api.GET('/api/v1/cases')),
  });
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Cases</h1>
          <p className="sub">Each case joins documents, tables, photos and sensor data into one inspectable state.</p>
        </div>
      </div>
      {cases.error ? <ErrorNote error={cases.error} /> : null}
      {cases.isLoading ? <Loading what="cases" /> : null}
      {cases.data && cases.data.cases.length === 0 ? (
        <p data-testid="no-cases" className="card empty">
          No cases yet.
        </p>
      ) : null}
      {cases.data && cases.data.cases.length > 0 ? (
        <section className="card" aria-label="Cases">
          <ul className="rowlist" data-testid="case-list">
            {cases.data.cases.map((c) => (
              <li key={c.case_id}>
                <a className="case-row" href={`/case/?id=${encodeURIComponent(c.case_id)}`}>
                  <span className="t" data-testid="case-link">
                    {c.title}
                  </span>
                  <span className="go">Open →</span>
                  <span className="d">
                    {c.entities.join(', ')} · {localDateTime(c.window_start, c.plant_tz)} to {localDateTime(c.window_end, c.plant_tz)} (plant-local)
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

export default function CaseList() {
  return (
    <Providers>
      <Nav />
      <List />
    </Providers>
  );
}
