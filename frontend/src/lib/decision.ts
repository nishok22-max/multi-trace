/** Decision rules the form enforces before it sends (the server checks them again). */
export const MIN_REASON = 15;

export type ReviewType =
  | 'ambiguous_entity'
  | 'reader_disagreement'
  | 'implausible_value'
  | 'hidden_text'
  | 'envelope_drift'
  | 'low_confidence'
  | 'unknown_unit'
  | 'llm_only_interpretation'
  | 'no_text_layer'
  | 'unsupported_page'
  | 'pdf_page_cap'
  | 'conflict_explain';

export type ChoiceKind = 'entity' | 'reading' | 'explain' | 'escalate';

/** Mirrors the backend's `choice_allowed`: escalate anywhere, an entity choice only on an
 *  ambiguous entity, an explanation only on a conflict, a reading verdict on everything else. */
export function allowedChoices(type: ReviewType): ChoiceKind[] {
  if (type === 'ambiguous_entity') return ['entity', 'escalate'];
  if (type === 'conflict_explain') return ['explain', 'escalate'];
  return ['reading', 'escalate'];
}

export function reasonProblem(reason: string): string | null {
  const trimmed = reason.trim();
  if (trimmed.length < MIN_REASON) return `Give a reason of at least ${MIN_REASON} characters (${trimmed.length} so far).`;
  return null;
}

export type Choice =
  | { type: 'entity'; entity_id: string }
  | { type: 'reading'; verdict: 'accept' | 'reject' }
  | { type: 'explain'; explanation: string | null }
  | { type: 'escalate' };

export interface DecisionBody {
  choice: Choice;
  reason: string;
  base_version: number;
  shown_evidence_hash: string;
  supersedes?: string;
}

/** The body never contains a reviewer: identity comes from the session. */
export function buildDecision(
  choice: Choice,
  reason: string,
  baseVersion: number,
  shownEvidenceHash: string,
  supersedes?: string,
): DecisionBody {
  const body: DecisionBody = {
    choice,
    reason: reason.trim(),
    base_version: baseVersion,
    shown_evidence_hash: shownEvidenceHash,
  };
  if (supersedes !== undefined) body.supersedes = supersedes;
  return body;
}

export function conflictMessage(problemType: string | undefined): string {
  switch (problemType) {
    case '/problems/already-decided':
      return 'This item was already decided by someone else. Reload to see the decision.';
    case '/problems/evidence-changed':
      return 'The evidence changed since you opened it. Reload and look again before deciding.';
    case '/problems/build-in-progress':
      return 'A build is running for this case. Try again in a few seconds.';
    default:
      return 'The decision could not be saved.';
  }
}
