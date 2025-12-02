export type ProjectActivitySummary = {
  ingests: number;
  publishes: number;
  renders: number;
  deliveries: number;
};

export type NextStepRecommendation =
  | { step: 'ingest'; title: string; description: string; ctaLabel: string }
  | { step: 'publish'; title: string; description: string; ctaLabel: string }
  | { step: 'render'; title: string; description: string; ctaLabel: string }
  | { step: 'deliver'; title: string; description: string; ctaLabel: string }
  | { step: 'diagnostics'; title: string; description: string; ctaLabel: string };

export function getNextStep(summary: ProjectActivitySummary): NextStepRecommendation {
  if (summary.ingests === 0) {
    return {
      step: 'ingest',
      title: 'Start by ingesting vendor media',
      description: 'Bring plates or assets into the project to kick off the pipeline.',
      ctaLabel: 'Open vendor ingest',
    };
  }

  if (summary.publishes === 0) {
    return {
      step: 'publish',
      title: 'Publish your first scene',
      description: 'Send a scene from your DCC to the pipeline so it can be tracked.',
      ctaLabel: 'Open DCC publish',
    };
  }

  if (summary.renders === 0) {
    return {
      step: 'render',
      title: 'Submit a render',
      description: 'Create a render submission to validate rendering works for this project.',
      ctaLabel: 'Open render submit',
    };
  }

  if (summary.deliveries === 0) {
    return {
      step: 'deliver',
      title: 'Package a client delivery',
      description: 'Bundle outputs into a delivery package for review or handoff.',
      ctaLabel: 'Open delivery wizard',
    };
  }

  return {
    step: 'diagnostics',
    title: 'Review diagnostics',
    description: 'Everything looks active—run diagnostics to ensure the stack is healthy.',
    ctaLabel: 'Open diagnostics',
  };
}
