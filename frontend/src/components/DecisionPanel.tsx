import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { api, ApiError, CSRF, unwrap, type Schemas } from '../lib/api/client';
import {
  allowedChoices,
  buildDecision,
  conflictMessage,
  reasonProblem,
  type Choice,
  type ChoiceKind,
} from '../lib/decision';

const LABEL: Record<ChoiceKind, string> = {
  entity: 'Link to a machine',
  reading: 'Accept or reject the reading',
  explain: 'Mark conflict explained',
  escalate: 'Escalate to a senior reviewer',
};

interface Props {
  caseId: string;
  baseVersion: number;
  item: Schemas['ReviewItem'];
  onDecided: (result: Schemas['DecisionResponse']) => void;
}

/** Typed choices per item, a reason of at least 15 characters, and the exact evidence hash the
 *  reviewer was shown. The reviewer is never sent: the server takes it from the session. */
export default function DecisionPanel({ caseId, baseVersion, item, onDecided }: Props) {
  const kinds = allowedChoices(item.type);
  const [kind, setKind] = useState<ChoiceKind>(kinds[0] ?? 'escalate');
  const [entity, setEntity] = useState<string>(item.candidates?.find((c) => !c.vetoed)?.entity_id ?? '');
  const [verdict, setVerdict] = useState<'accept' | 'reject'>('accept');
  const [explanation, setExplanation] = useState('');
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);

  const mutation = useMutation({
    mutationFn: async (): Promise<Schemas['DecisionResponse']> => {
      const choice: Choice =
        kind === 'entity'
          ? { type: 'entity', entity_id: entity }
          : kind === 'reading'
            ? { type: 'reading', verdict }
            : kind === 'explain'
              ? { type: 'explain', explanation: explanation.trim() || null }
              : { type: 'escalate' };
      const body = buildDecision(choice, reason, baseVersion, item.evidence_hash);
      return unwrap(
        await api.POST('/api/v1/cases/{cid}/review/{rid}/decision', {
          params: { header: CSRF, path: { cid: caseId, rid: item.review_id } },
          body,
        }),
      );
    },
    onSuccess: onDecided,
  });

  const problem = reasonProblem(reason);
  const needsEntity = kind === 'entity' && entity === '';
  const error = mutation.error;
  return (
    <form
      aria-label="Your decision"
      data-testid="decision-panel"
      className="space-y-3 rounded border-2 border-slate-600 bg-white p-3"
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (!problem && !needsEntity) mutation.mutate();
      }}
    >
      <h3 className="font-bold">Your decision</h3>
      <fieldset className="space-y-1">
        <legend className="text-sm font-semibold">What do you decide?</legend>
        {kinds.map((k) => (
          <label key={k} className="block text-sm">
            <input type="radio" name="choice" className="mr-2" checked={kind === k} onChange={() => setKind(k)} data-testid={`choice-${k}`} />
            {LABEL[k]}
          </label>
        ))}
      </fieldset>
      {kind === 'entity' ? (
        <label className="block text-sm">
          Machine
          <select
            data-testid="entity-select"
            className="ml-2 rounded border border-slate-500 px-1"
            value={entity}
            onChange={(e) => setEntity(e.target.value)}
          >
            <option value="">Choose...</option>
            {(item.candidates ?? []).map((c) => (
              <option key={c.entity_id} value={c.entity_id}>
                {c.entity_id}
                {c.vetoed ? ' (vetoed)' : ''}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {kind === 'reading' ? (
        <label className="block text-sm">
          Verdict
          <select data-testid="verdict-select" className="ml-2 rounded border border-slate-500 px-1" value={verdict} onChange={(e) => setVerdict(e.target.value as 'accept' | 'reject')}>
            <option value="accept">Accept the reading</option>
            <option value="reject">Reject the reading</option>
          </select>
        </label>
      ) : null}
      {kind === 'explain' ? (
        <label className="block text-sm">
          Explanation
          <input className="ml-2 w-80 rounded border border-slate-500 px-1" value={explanation} onChange={(e) => setExplanation(e.target.value)} />
        </label>
      ) : null}
      <label className="block text-sm">
        Reason (at least 15 characters)
        <textarea
          data-testid="reason"
          className="mt-1 block w-full rounded border border-slate-500 p-1"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          aria-invalid={touched && problem ? true : undefined}
        />
      </label>
      {touched && problem ? (
        <p role="alert" data-testid="reason-error" className="text-sm text-red-800">
          {problem}
        </p>
      ) : null}
      {touched && needsEntity ? (
        <p role="alert" className="text-sm text-red-800">
          Choose a machine.
        </p>
      ) : null}
      {error ? (
        <p role="alert" data-testid="decision-error" className="text-sm font-semibold text-red-800">
          {error instanceof ApiError && error.status === 409 ? conflictMessage(error.problemType) : error.message}
        </p>
      ) : null}
      <button type="submit" data-testid="decide" disabled={mutation.isPending} className="rounded bg-slate-800 px-3 py-1 font-semibold text-white">
        {mutation.isPending ? 'Saving...' : kind === 'escalate' ? 'Escalate' : 'Save decision'}
      </button>
    </form>
  );
}
