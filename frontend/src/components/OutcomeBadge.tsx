import type { Schemas } from '../lib/api/client';

type Outcome = Schemas['ComparisonRecord']['outcome'];

/** The outcome is always a text label; colour only reinforces it. */
const LABEL: Record<Outcome, string> = {
  agree: 'They agree',
  disagree: 'They disagree',
  cant_compare: "They can't be compared",
  cant_tell: "We can't tell",
};

export function outcomeLabel(outcome: Outcome): string {
  return LABEL[outcome];
}

export default function OutcomeBadge({ outcome, small }: { outcome: Outcome; small?: boolean }) {
  return (
    <span data-testid="outcome-badge" data-outcome={outcome} className={`outcome outcome-${outcome}${small ? ' outcome-sm' : ''}`}>
      {LABEL[outcome]}
    </span>
  );
}
