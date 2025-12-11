import { describe, expect, it } from 'vitest';

import {
  buildRemoteFromParts,
  normalizeAwsSyncPresets,
  parseRemoteParts,
  validatePresetPayload,
} from './awsSyncPresets';

describe('awsSyncPresets helpers', () => {
  it('builds a remote path from bucket, show code, and prefix', () => {
    const remote = buildRemoteFromParts({
      bucketUrl: 'my-bucket/',
      showCode: '/OP/',
      remotePath: '/renders/v001/',
    });

    expect(remote).toBe('s3://my-bucket/OP/renders/v001');
  });

  it('parses an existing remote path into parts', () => {
    const parts = parseRemoteParts('s3://bucket/show/path/to/files');

    expect(parts).toEqual({
      bucketUrl: 's3://bucket',
      showCode: 'show',
      remotePath: 'path/to/files',
    });
  });

  it('normalizes presets with default buckets and directions', () => {
    const presets = normalizeAwsSyncPresets(
      [
        {
          id: 'p1',
          name: 'Upload renders',
          direction: 'to',
          localPath: '/tmp/files',
          remotePath: 'renders/latest',
          showCode: 'OP',
        },
      ],
      'demo-bucket',
    );

    expect(presets[0]).toMatchObject({
      id: 'p1',
      direction: 'upload',
      remote: 's3://demo-bucket/OP/renders/latest',
      bucketUrl: 's3://demo-bucket',
    });
  });

  it('validates preset payloads for IPC calls', () => {
    const payload = validatePresetPayload({
      id: 'p2',
      name: 'Download cache',
      direction: 'download',
      localPath: '  ./cache  ',
      remote: ' s3://bucket/show/cache ',
    });

    expect(payload).toEqual({
      localPath: './cache',
      remote: 's3://bucket/show/cache',
    });
  });
});
