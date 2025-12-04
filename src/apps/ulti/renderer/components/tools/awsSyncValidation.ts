export type AwsSyncValidationInput = {
  localPath: string;
  remotePath: string;
};

export type AwsSyncValidatedPaths = {
  localPath: string;
  remotePath: string;
};

export const validateAwsSyncPaths = ({
  localPath,
  remotePath,
}: AwsSyncValidationInput): AwsSyncValidatedPaths => {
  const trimmedLocalPath = localPath.trim();
  const trimmedRemotePath = remotePath.trim();

  if (!trimmedLocalPath) {
    throw new Error('Enter a local path to sync.');
  }

  if (!trimmedRemotePath) {
    throw new Error("Enter a remote path like 's3://bucket/show/path'.");
  }

  const withoutScheme = trimmedRemotePath.replace(/^s3:\/\//i, '');
  const [bucket, showCode, ...remainingSegments] = withoutScheme.split('/').filter(Boolean);

  if (!bucket) {
    throw new Error("Remote path must include an S3 bucket, e.g. 's3://bucket/show/path'.");
  }

  if (!showCode) {
    throw new Error(
      "Remote path must include a show code after the bucket, e.g. 's3://bucket/show/path'.",
    );
  }

  if (remainingSegments.length === 0) {
    throw new Error(
      "Remote path must include a folder/prefix after the show code, e.g. 's3://bucket/show/path'.",
    );
  }

  return { localPath: trimmedLocalPath, remotePath: trimmedRemotePath };
};
