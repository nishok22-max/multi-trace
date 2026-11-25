import type { Schemas } from '../lib/api/client';

/** The five-step story. Texts are written by the engine from computed values. */
export default function StorySteps({ story }: { story: Schemas['Story'] }) {
  return (
    <section className="card card-pad" aria-label="How the engine got here">
      <p className="eyebrow">How the engine got here</p>
      <ol data-testid="story" className="steps">
        {story.steps.map((step) => (
          <li key={step.n}>
            <span className="step-n" aria-hidden="true">
              {step.n}
            </span>
            <div>
              <h3>
                <span className="muted">Step {step.n}:</span> {step.title}
              </h3>
              <p>{step.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
