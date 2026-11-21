import type { Schemas } from '../lib/api/client';

/** The five-step story. Texts are written by the engine from computed values. */
export default function StorySteps({ story }: { story: Schemas['Story'] }) {
  return (
    <ol data-testid="story" className="mb-6 space-y-2">
      {story.steps.map((step) => (
        <li key={step.n} className="rounded border border-slate-300 bg-white p-3">
          <h2 className="font-semibold">
            Step {step.n}: {step.title}
          </h2>
          <p className="text-sm text-slate-800">{step.text}</p>
        </li>
      ))}
    </ol>
  );
}
