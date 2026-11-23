import { describe, expect, it } from 'vitest';
import { allowedChoices, buildDecision, conflictMessage, MIN_REASON, reasonProblem } from './decision';

describe('allowedChoices', () => {
  it('mirrors the server: entity only on an ambiguous entity, explain only on a conflict', () => {
    expect(allowedChoices('ambiguous_entity')).toEqual(['entity', 'escalate']);
    expect(allowedChoices('conflict_explain')).toEqual(['explain', 'escalate']);
    for (const t of ['hidden_text', 'reader_disagreement', 'low_confidence', 'implausible_value'] as const) {
      expect(allowedChoices(t)).toEqual(['reading', 'escalate']);
    }
  });
});

describe('reasonProblem', () => {
  it('needs at least 15 characters after trimming', () => {
    expect(MIN_REASON).toBe(15);
    expect(reasonProblem('too short')).toMatch(/at least 15/);
    expect(reasonProblem('   ' + 'x'.repeat(14) + '   ')).not.toBeNull();
    expect(reasonProblem('x'.repeat(15))).toBeNull();
  });
});

describe('buildDecision', () => {
  it('never carries a reviewer and keeps the evidence hash it was shown', () => {
    const body = buildDecision({ type: 'entity', entity_id: 'machine:21' }, '  a long enough reason here  ', 3, 'h'.repeat(64));
    expect(Object.keys(body).sort()).toEqual(['base_version', 'choice', 'reason', 'shown_evidence_hash']);
    expect(body.reason).toBe('a long enough reason here');
    expect(body.base_version).toBe(3);
    expect(buildDecision({ type: 'escalate' }, 'x'.repeat(15), 1, 'h', 'dec_1').supersedes).toBe('dec_1');
  });
});

describe('conflictMessage', () => {
  it('names only the three 409 causes', () => {
    expect(conflictMessage('/problems/already-decided')).toMatch(/already decided/);
    expect(conflictMessage('/problems/evidence-changed')).toMatch(/evidence changed/);
    expect(conflictMessage('/problems/build-in-progress')).toMatch(/build/);
    expect(conflictMessage(undefined)).toMatch(/could not be saved/);
  });
});
