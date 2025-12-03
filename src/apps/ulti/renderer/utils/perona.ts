export type CostInsightsResponse = {
  insights?: unknown;
  stdout?: string | null;
  stderr?: string | null;
  code?: number;
};

const toInsightStrings = (input: unknown[]): string[] => {
  return input
    .map((item) => {
      if (typeof item === 'string') {
        return item;
      }

      try {
        return JSON.stringify(item);
      } catch {
        return String(item);
      }
    })
    .filter((value) => Boolean(value?.trim())) as string[];
};

const extractInsightArray = (value: unknown): string[] | null => {
  if (Array.isArray(value)) {
    return toInsightStrings(value);
  }

  if (value && typeof value === 'object') {
    const typed = value as Record<string, unknown>;
    const candidate = typed.recommendations ?? typed.insights ?? typed.suggestions;

    if (Array.isArray(candidate)) {
      return toInsightStrings(candidate as unknown[]);
    }
  }

  return null;
};

export const normalizeCostInsights = (response: CostInsightsResponse): string[] => {
  const { insights, stdout } = response ?? {};

  const fromInsights = extractInsightArray(insights);
  if (fromInsights) {
    return fromInsights;
  }

  const text = stdout?.trim();
  if (!text) {
    return [];
  }

  if (text.startsWith('{') || text.startsWith('[')) {
    try {
      const parsed = JSON.parse(text);
      const parsedInsights = extractInsightArray(parsed);
      if (parsedInsights) {
        return parsedInsights;
      }
    } catch (error) {
      console.warn('Failed to parse cost insights JSON from stdout', error);
    }
  }

  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
};
