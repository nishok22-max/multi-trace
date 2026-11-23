import { useQuery } from '@tanstack/react-query';
import Nav from '../components/Nav';
import { api, unwrap } from '../lib/api/client';
import { localDateTime } from '../lib/format';
import { keys } from '../lib/query/keys';
import Providers, { ErrorNote } from './Providers';

function List() {
  const cases = useQuery({
    queryKey: keys.cases(),
    queryFn: async () => unwrap(await api.GET('/api/v1/cases')),
  });
  return (
    <div>
      <Nav />
      <h1 className="mb-3 text-2xl font-bold">Cases</h1>
      {cases.error ? <ErrorNote error={cases.error} /> : null}
      {cases.isLoading ? <p>Loading cases...</p> : null}
      {cases.data && cases.data.cases.length === 0 ? <p data-testid="no-cases">No cases yet.</p> : null}
      <ul className="space-y-2" data-testid="case-list">
        {(cases.data?.cases ?? []).map((c) => (
          <li key={c.case_id} className="rounded border border-slate-400 bg-white p-3">
            <a className="text-lg font-semibold underline" href={`/case/?id=${encodeURIComponent(c.case_id)}`} data-testid="case-link">
              {c.title}
            </a>
            <p className="text-sm text-slate-700">
              {c.entities.join(', ')} · {localDateTime(c.window_start, c.plant_tz)} to {localDateTime(c.window_end, c.plant_tz)} (plant-local)
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function CaseList() {
  return (
    <Providers>
      <List />
    </Providers>
  );
}
