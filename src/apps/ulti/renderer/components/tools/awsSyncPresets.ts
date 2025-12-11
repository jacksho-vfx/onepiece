import { validateAwsSyncPaths } from './awsSyncValidation';

export type AwsSyncDirection = 'download' | 'upload';

export type AwsSyncPresetInput = {
  id: string;
  name: string;
  direction: AwsSyncDirection | 'from' | 'to';
  localPath: string;
  remote?: string;
  bucketUrl?: string;
  showCode?: string;
  remotePath?: string;
};

export type NormalizedAwsSyncPreset = AwsSyncPresetInput & {
  direction: AwsSyncDirection;
  remote: string;
  bucketUrl?: string;
  showCode?: string;
  remotePath?: string;
};

const trimSlashes = (value: string): string => value.replace(/^\/+|\/+$/g, '');

export const normalizeBucketUrl = (value?: string): string => {
  const trimmed = value?.trim();
  if (!trimmed) {
    return '';
  }

  const withoutScheme = trimmed.replace(/^s3:\/\//i, '');
  const withoutTrailingSlash = withoutScheme.replace(/\/+$/, '');
  return withoutTrailingSlash ? `s3://${withoutTrailingSlash}` : '';
};

export const parseRemoteParts = (
  remote?: string,
): { bucketUrl?: string; showCode?: string; remotePath?: string } => {
  if (!remote?.trim()) {
    return {};
  }

  const withoutScheme = remote.replace(/^s3:\/\//i, '');
  const [bucket, showCode, ...rest] = withoutScheme.split('/').filter(Boolean);
  const remotePath = trimSlashes(rest.join('/'));

  return {
    bucketUrl: bucket ? `s3://${bucket}` : undefined,
    showCode: showCode || undefined,
    remotePath: remotePath || undefined,
  };
};

export const buildRemoteFromParts = ({
  bucketUrl,
  showCode,
  remotePath,
}: {
  bucketUrl?: string;
  showCode?: string;
  remotePath?: string;
}): string => {
  const normalizedBucket = normalizeBucketUrl(bucketUrl);
  const normalizedShow = trimSlashes(showCode?.trim() ?? '');
  const normalizedPath = trimSlashes(remotePath?.trim() ?? '');

  const segments = [
    normalizedBucket.replace(/^s3:\/\//i, ''),
    normalizedShow,
    normalizedPath,
  ].filter(Boolean);

  return segments.length ? `s3://${segments.join('/')}` : '';
};

export const normalizeAwsSyncPresets = (
  presets: AwsSyncPresetInput[] | undefined,
  defaultBucket?: string,
): NormalizedAwsSyncPreset[] => {
  return (presets ?? []).map((preset) => {
    const direction: AwsSyncDirection = preset.direction === 'from'
      ? 'download'
      : preset.direction === 'to'
        ? 'upload'
        : preset.direction;

    const parsed = parseRemoteParts(preset.remote);
    const bucketUrl = normalizeBucketUrl(preset.bucketUrl ?? parsed.bucketUrl ?? defaultBucket);
    const showCode = preset.showCode ?? parsed.showCode ?? '';
    const remotePath = preset.remotePath ?? parsed.remotePath ?? '';
    const remote =
      buildRemoteFromParts({ bucketUrl, showCode, remotePath }) || preset.remote || '';

    return {
      ...preset,
      direction,
      bucketUrl: bucketUrl || undefined,
      showCode: showCode || undefined,
      remotePath: remotePath || undefined,
      remote,
    } satisfies NormalizedAwsSyncPreset;
  });
};

export const validatePresetPayload = (preset: NormalizedAwsSyncPreset): { localPath: string; remote: string } => {
  const { localPath, remotePath } = validateAwsSyncPaths({
    localPath: preset.localPath,
    remotePath: preset.remote,
  });

  return { localPath, remote: remotePath };
};
