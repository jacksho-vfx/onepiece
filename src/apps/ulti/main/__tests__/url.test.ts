import { describe, expect, it } from 'vitest';
import { ensureSafeExternalUrl } from '../url';

describe('ensureSafeExternalUrl', () => {
  it('allows http URLs', () => {
    expect(ensureSafeExternalUrl('http://example.com')).toBe('http://example.com/');
  });

  it('allows https URLs', () => {
    expect(ensureSafeExternalUrl('https://example.com/path')).toBe(
      'https://example.com/path'
    );
  });

  it('rejects missing URLs', () => {
    expect(() => ensureSafeExternalUrl('')).toThrowError('No URL provided');
  });

  it('rejects malformed URLs', () => {
    expect(() => ensureSafeExternalUrl('not a url')).toThrowError('Invalid URL format');
  });

  it('rejects unsupported protocols', () => {
    expect(() => ensureSafeExternalUrl('ftp://example.com')).toThrowError(
      'Unsupported URL protocol: ftp:'
    );
  });
});
