import { promises as fs } from 'fs';
import path from 'path';
import { app } from 'electron';

/**
 * Core wizard inputs required to bootstrap a OnePiece project.
 */
export type WizardConfigInput = {
  profile: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  projectRoot: string;
  pythonPath?: string;
  shotgrid?: { url?: string; scriptName?: string; apiKey?: string };
  aws?: { accessKeyId?: string; secretAccessKey?: string; region?: string; defaultBucket?: string };
  dccs?: {
    maya?: { enabled: boolean; executablePath?: string };
    blender?: { enabled: boolean; executablePath?: string };
    unreal?: { enabled: boolean; executablePath?: string };
  };
};

/**
 * Generate a starter onepiece.toml configuration from the wizard inputs.
 * This focuses on the minimal values required to get a project running and
 * leaves space for future, more advanced configuration (e.g. pipelines, logging, etc.).
 */
export function generateOnepieceToml(input: WizardConfigInput): string {
  const lines: string[] = [];

  lines.push('[core]');
  lines.push(`project_root = "${input.projectRoot}"`);
  if (input.pythonPath) {
    lines.push(`python_path = "${input.pythonPath}"`);
  }

  // Optional integrations.
  if (input.shotgrid && (input.shotgrid.url || input.shotgrid.scriptName || input.shotgrid.apiKey)) {
    lines.push('', '[integrations.shotgrid]');
    if (input.shotgrid.url) lines.push(`url = "${input.shotgrid.url}"`);
    if (input.shotgrid.scriptName) lines.push(`script_name = "${input.shotgrid.scriptName}"`);
    if (input.shotgrid.apiKey) lines.push(`api_key = "${input.shotgrid.apiKey}"`);
  }

  if (input.aws && (input.aws.accessKeyId || input.aws.secretAccessKey || input.aws.region || input.aws.defaultBucket)) {
    lines.push('', '[integrations.aws]');
    if (input.aws.accessKeyId) lines.push(`access_key_id = "${input.aws.accessKeyId}"`);
    if (input.aws.secretAccessKey) lines.push(`secret_access_key = "${input.aws.secretAccessKey}"`);
    if (input.aws.region) lines.push(`region = "${input.aws.region}"`);
    if (input.aws.defaultBucket) lines.push(`default_bucket = "${input.aws.defaultBucket}"`);
  }

  if (input.dccs) {
    const { maya, blender, unreal } = input.dccs;

    if (maya?.enabled) {
      lines.push('', '[dccs.maya]');
      lines.push(`enabled = ${maya.enabled}`);
      if (maya.executablePath) lines.push(`executable_path = "${maya.executablePath}"`);
    }

    if (blender?.enabled) {
      lines.push('', '[dccs.blender]');
      lines.push(`enabled = ${blender.enabled}`);
      if (blender.executablePath) lines.push(`executable_path = "${blender.executablePath}"`);
    }

    if (unreal?.enabled) {
      lines.push('', '[dccs.unreal]');
      lines.push(`enabled = ${unreal.enabled}`);
      if (unreal.executablePath) lines.push(`executable_path = "${unreal.executablePath}"`);
    }
  }

  // TODO: Add pipeline step definitions, logging configuration, and other
  // advanced OnePiece settings derived from future wizard steps.

  return lines.join('\n') + '\n';
}

async function safeCopyFile(src: string, dest: string): Promise<void> {
  try {
    await fs.access(dest);
    // If the destination exists, do not overwrite—starter kits should not clobber user files.
    return;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT') throw error;
  }

  await fs.copyFile(src, dest);
}

async function copyDirectoryRecursive(srcDir: string, destDir: string): Promise<void> {
  await fs.mkdir(destDir, { recursive: true });

  const entries = await fs.readdir(srcDir, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(srcDir, entry.name);
    const destPath = path.join(destDir, entry.name);

    if (entry.isDirectory()) {
      await copyDirectoryRecursive(srcPath, destPath);
    } else if (entry.isFile()) {
      await safeCopyFile(srcPath, destPath);
    }
    // TODO: Handle symlinks or special file types if starter kits require them.
  }
}

/**
 * Copy the starter-kit files for the selected profile into the target project directory.
 * Files are only written when they do not already exist, so running the wizard again is safe.
 */
export async function installStarterKit(profile: WizardConfigInput['profile'], projectRoot: string): Promise<void> {
  const resourcesDir = app.isPackaged ? process.resourcesPath : app.getAppPath();
  const kitPath = path.join(resourcesDir, 'starter-kits', profile);

  let stats: Awaited<ReturnType<typeof fs.stat>>;
  try {
    stats = await fs.stat(kitPath);
  } catch (error) {
    console.warn(`Starter kit for profile "${profile}" was not found at ${kitPath}.`);
    return;
  }

  if (!stats.isDirectory()) {
    console.warn(`Starter kit path ${kitPath} is not a directory.`);
    return;
  }

  await copyDirectoryRecursive(kitPath, projectRoot);
}
