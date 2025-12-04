export type CostInsightsResponse = {
  insights?: unknown;
  stdout?: string | null;
  stderr?: string | null;
  code?: number;
  rawText?: string | null;
  parseError?: {
    message?: string | null;
    stderr?: string | null;
    code?: number | null;
  } | null;
};

export type NormalizedCostInsight = { title: string; summary?: string | null };

export type NormalizedCostInsights = {
  recommendations: NormalizedCostInsight[];
  rawText: string | null;
  errorMessage: string | null;
  exitCode: number | null;
};

const cleanText = (value?: string | number | null): string | null => {
  if (value === undefined || value === null) {
    return null;
  }

  const text = typeof value === 'string' ? value : String(value);
  const trimmed = text.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
};

const tryParseJson = (candidate: string): unknown | null => {
  try {
    return JSON.parse(candidate);
  } catch (error) {
    console.warn('Failed to parse cost insights JSON', error);
    return null;
  }
};

const pickInsightArray = (value: unknown): unknown[] | null => {
  if (Array.isArray(value)) {
    return value;
  }

  if (value && typeof value === 'object') {
    const typed = value as Record<string, unknown>;
    const candidate = typed.recommendations ?? typed.insights ?? typed.suggestions;

    if (Array.isArray(candidate)) {
      return candidate as unknown[];
    }
  }

  return null;
};

const normalizeRecommendation = (value: unknown, index: number): NormalizedCostInsight => {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return { title: trimmed || `Insight ${index + 1}`, summary: trimmed || undefined };
  }

  if (value && typeof value === 'object') {
    const typed = value as Record<string, unknown>;
    const titleCandidate = typed.title ?? typed.name ?? typed.id;
    const title = cleanText(titleCandidate) || `Insight ${index + 1}`;
    const summary =
      cleanText(typed.summary as string) ||
      cleanText(typed.description as string) ||
      cleanText(typed.detail as string) ||
      cleanText(typed.reason as string) ||
      null;

    return { title, summary };
  }

  const fallback = String(value ?? `Insight ${index + 1}`).trim();
  return { title: fallback || `Insight ${index + 1}`, summary: fallback || undefined };
};

export const normalizeCostInsights = (response: CostInsightsResponse): NormalizedCostInsights => {
  const rawText = cleanText(response?.rawText ?? response?.stdout ?? response?.parseError?.stderr);

  const exitCode =
    typeof response?.parseError?.code === 'number'
      ? response.parseError.code
      : typeof response?.code === 'number'
        ? response.code
        : null;

  const errorMessage =
    cleanText(response?.parseError?.message) ??
    cleanText(response?.parseError?.stderr) ??
    cleanText(response?.stderr) ??
    (exitCode !== null && exitCode !== 0
      ? `Perona cost insights exited with code ${exitCode}`
      : null);

  const insightsArray = pickInsightArray(response?.insights);
  if (insightsArray) {
    return {
      recommendations: insightsArray.map(normalizeRecommendation),
      rawText,
      errorMessage,
      exitCode,
    };
  }

  if (rawText && (rawText.startsWith('{') || rawText.startsWith('['))) {
    const parsed = tryParseJson(rawText);
    const parsedArray = pickInsightArray(parsed);
    if (parsedArray) {
      return {
        recommendations: parsedArray.map(normalizeRecommendation),
        rawText,
        errorMessage,
        exitCode,
      };
    }
  }

  if (rawText) {
    const recommendations = rawText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line, index) => ({ title: line, summary: line || `Insight ${index + 1}` }));

    return { recommendations, rawText, errorMessage, exitCode };
  }

  return { recommendations: [], rawText, errorMessage, exitCode };
};
