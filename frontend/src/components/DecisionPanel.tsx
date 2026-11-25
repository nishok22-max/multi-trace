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
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (!problem && !needsEntity) mutation.mutate();
      }}
    >
      <div className="card-head">
        <h3>Your decision</h3>
        <span className="aside small muted">Recorded under your session, with the evidence you were shown.</span>
      </div>
      <div className="card-body stack-sm">
        <fieldset className="choices">
          <legend>What do you decide?</legend>
          {kinds.map((k) => (
            <label key={k} className="choice">
              <input type="radio" name="choice" checked={kind === k} onChange={() => setKind(k)} data-testid={`choice-${k}`} />
              {LABEL[k]}
            </label>
          ))}
        </fieldset>
        {kind === 'entity' ? (
          <label className="field">
            Machine
            <select data-testid="entity-select" className="input" value={entity} onChange={(e) => setEntity(e.target.value)}>
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
          <label className="field">
            Verdict
            <select data-testid="verdict-select" className="input" value={verdict} onChange={(e) => setVerdict(e.target.value as 'accept' | 'reject')}>
              <option value="accept">Accept the reading</option>
              <option value="reject">Reject the reading</option>
            </select>
          </label>
        ) : null}
        {kind === 'explain' ? (
          <label className="field">
            Explanation
            <input className="input" value={explanation} onChange={(e) => setExplanation(e.target.value)} />
          </label>
        ) : null}
        <label className="field">
          <span>
            Reason <span className="hint">(at least 15 characters)</span>
          </span>
          <textarea
            data-testid="reason"
            className="input"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-invalid={touched && problem ? true : undefined}
          />
        </label>
        {touched && problem ? (
          <p role="alert" data-testid="reason-error" className="field-error">
            {problem}
          </p>
        ) : null}
        {touched && needsEntity ? (
          <p role="alert" className="field-error">
            Choose a machine.
          </p>
        ) : null}
        {error ? (
          <p role="alert" data-testid="decision-error" className="callout callout-bad">
            {error instanceof ApiError && error.status === 409 ? conflictMessage(error.problemType) : error.message}
          </p>
        ) : null}
        <div className="actions">
          <button type="submit" data-testid="decide" disabled={mutation.isPending} className="btn btn-primary">
            {mutation.isPending ? 'Saving...' : kind === 'escalate' ? 'Escalate' : 'Save decision'}
          </button>
        </div>
      </div>
    </form>
  );
}
