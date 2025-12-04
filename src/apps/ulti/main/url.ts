const ALLOWED_PROTOCOLS = new Set(['http:', 'https:']);

export function ensureSafeExternalUrl(input: string | undefined | null): string {
  if (!input || input.trim().length === 0) {
    throw new Error('No URL provided');
  }

  let parsed: URL;
  try {
    parsed = new URL(input);
  } catch {
    throw new Error('Invalid URL format');
  }

  if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) {
    throw new Error(`Unsupported URL protocol: ${parsed.protocol}`);
  }

  return parsed.toString();
}
