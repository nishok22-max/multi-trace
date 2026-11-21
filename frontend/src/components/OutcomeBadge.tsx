import type { Schemas } from '../lib/api/client';

type Outcome = Schemas['ComparisonRecord']['outcome'];

/** The outcome is always a text label; colour only reinforces it. */
const LABEL: Record<Outcome, string> = {
  agree: 'They agree',
  disagree: 'They disagree',
  cant_compare: "They can't be compared",
  cant_tell: "We can't tell",
};

const STYLE: Record<Outcome, string> = {
  agree: 'bg-green-100 text-green-900 border-green-700',
  disagree: 'bg-red-600 text-white border-red-800',
  cant_compare: 'bg-slate-200 text-slate-900 border-slate-600',
  cant_tell: 'bg-amber-100 text-amber-900 border-amber-700',
};

export function outcomeLabel(outcome: Outcome): string {
  return LABEL[outcome];
}

export default function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return (
    <span
      data-testid="outcome-badge"
      data-outcome={outcome}
      className={`inline-block rounded border px-3 py-1 text-lg font-bold ${STYLE[outcome]}`}
    >
      {LABEL[outcome]}
    </span>
  );
}
