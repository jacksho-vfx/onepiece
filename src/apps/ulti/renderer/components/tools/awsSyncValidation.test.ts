import { describe, expect, it } from 'vitest';

import { validateAwsSyncPaths } from './awsSyncValidation';

describe('validateAwsSyncPaths', () => {
  it('returns trimmed paths when valid', () => {
    const result = validateAwsSyncPaths({
      localPath: '  ./local ',
      remotePath: '  s3://bucket/show/folder  ',
    });

    expect(result).toEqual({ localPath: './local', remotePath: 's3://bucket/show/folder' });
  });

  it('rejects missing local path', () => {
    expect(() =>
      validateAwsSyncPaths({ localPath: '   ', remotePath: 's3://bucket/show/folder' }),
    ).toThrowError('Enter a local path to sync.');
  });

  it('rejects missing remote path', () => {
    expect(() => validateAwsSyncPaths({ localPath: './local', remotePath: '   ' })).toThrowError(
      "Enter a remote path like 's3://bucket/show/path'.",
    );
  });

  it('rejects remote without bucket', () => {
    expect(() => validateAwsSyncPaths({ localPath: './local', remotePath: 's3://' })).toThrowError(
      "Remote path must include an S3 bucket, e.g. 's3://bucket/show/path'.",
    );
  });

  it('rejects remote without show code', () => {
    expect(() =>
      validateAwsSyncPaths({ localPath: './local', remotePath: 's3://bucket' }),
    ).toThrowError("Remote path must include a show code after the bucket, e.g. 's3://bucket/show/path'.");
  });

  it('rejects remote without folder/prefix', () => {
    expect(() =>
      validateAwsSyncPaths({ localPath: './local', remotePath: 's3://bucket/show' }),
    ).toThrowError(
      "Remote path must include a folder/prefix after the show code, e.g. 's3://bucket/show/path'.",
    );
  });
});
