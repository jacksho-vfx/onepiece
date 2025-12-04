import { accessSync, constants, statSync } from 'fs';
import path from 'path';
import os from 'os';
import type { IpcMain } from 'electron';

/**
 * Check whether a given file path exists and is likely executable.
 */
export function pathExists(candidate: string | undefined): candidate is string {
  if (!candidate) {
    return false;
  }

  try {
    const stats = statSync(candidate);
    if (!stats.isFile()) {
      return false;
    }

    if (process.platform !== 'win32') {
      accessSync(candidate, constants.X_OK);
    }

    return true;
  } catch (error) {
    // Swallow errors and treat the candidate as missing to keep detection best-effort.
    return false;
  }
}

/**
 * Attempt to resolve an executable on the current PATH.
 *
 * Best-effort and cross-platform: on Windows we account for PATHEXT while other
 * platforms attempt the command name verbatim.
 */
function findOnPath(command: string): string | undefined {
  const pathEnv = process.env.PATH;
  if (!pathEnv) {
    return undefined;
  }

  const pathExts: string[] =
    process.platform === 'win32'
      ? (process.env.PATHEXT?.split(path.delimiter).filter(Boolean) ?? ['.exe', '.bat', '.cmd'])
      : [''];

  const commandHasExt = Boolean(path.extname(command));

  for (const baseDir of pathEnv.split(path.delimiter)) {
    for (const ext of pathExts) {
      const suffix = commandHasExt ? '' : ext;
      const candidate = path.join(baseDir, `${command}${suffix}`);
      if (pathExists(candidate)) {
        return candidate;
      }
    }
  }

  return undefined;
}

/**
 * Collect a unique list of candidate paths, returning the first that exists.
 */
function firstExisting(candidates: Array<string | undefined>): string | undefined {
  for (const candidate of candidates) {
    if (pathExists(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

/**
 * Attempt to detect an appropriate Python interpreter path.
 */
function detectPython(): string | undefined {
  if (process.platform === 'win32') {
    // Prefer the launcher if available as it can dispatch to the correct version.
    return firstExisting([
      findOnPath('py.exe'),
      findOnPath('py'),
      findOnPath('python.exe'),
      findOnPath('python'),
    ]);
  }

  // On POSIX systems prefer python3, falling back to python.
  return firstExisting([findOnPath('python3'), findOnPath('python')]);
}

/**
 * Build a list of likely Maya executable locations across platforms.
 */
function mayaCandidates(): string[] {
  const candidates: Array<string | undefined> = [];

  // Environment hint. MAYA_LOCATION typically points to the install root.
  if (process.env.MAYA_LOCATION) {
    candidates.push(
      path.join(process.env.MAYA_LOCATION, 'bin', process.platform === 'win32' ? 'maya.exe' : 'maya'),
    );
  }

  if (process.platform === 'win32') {
    // Common Autodesk install directories. The exact year may vary; extend as needed.
    const base = 'C://Program Files//Autodesk';
    const versions = ['Maya2022', 'Maya2023', 'Maya2024', 'Maya2025'];
    for (const version of versions) {
      candidates.push(path.join(base, version, 'bin', 'maya.exe'));
    }
  } else if (process.platform === 'darwin') {
    // macOS application bundle.
    candidates.push('/Applications/Autodesk/maya2024/Maya.app/Contents/bin/maya');
    candidates.push('/Applications/Autodesk/maya2025/Maya.app/Contents/bin/maya');
  } else {
    // Linux distributions often install under /usr/autodesk or the user's home directory.
    candidates.push('/usr/autodesk/maya2024/bin/maya');
    candidates.push('/usr/autodesk/maya2025/bin/maya');
    candidates.push(path.join(os.homedir(), 'maya', 'maya2024', 'bin', 'maya'));
  }

  return candidates.filter(Boolean) as string[];
}

/**
 * Build a list of likely Blender executable locations across platforms.
 */
function blenderCandidates(): string[] {
  const candidates: Array<string | undefined> = [];

  // BLENDER_PATH may point directly at the binary or a containing folder.
  if (process.env.BLENDER_PATH) {
    candidates.push(process.env.BLENDER_PATH);
    candidates.push(path.join(process.env.BLENDER_PATH, 'blender'));
    candidates.push(path.join(process.env.BLENDER_PATH, 'blender.exe'));
  }

  if (process.platform === 'win32') {
    // Standard Program Files path with versioned folders.
    const base = 'C://Program Files//Blender Foundation';
    const versions = ['Blender 4.0', 'Blender 4.1', 'Blender 3.6'];
    for (const version of versions) {
      candidates.push(path.join(base, version, 'blender.exe'));
    }
  } else if (process.platform === 'darwin') {
    // Default application bundle name.
    candidates.push('/Applications/Blender.app/Contents/MacOS/Blender');
  } else {
    // Linux packaging typically installs the binary on PATH, but check common prefixes too.
    candidates.push(findOnPath('blender'));
    candidates.push('/usr/bin/blender');
    candidates.push('/usr/local/bin/blender');
  }

  return candidates.filter(Boolean) as string[];
}

/**
 * Build a list of likely Unreal Engine editor executable locations across platforms.
 */
function unrealCandidates(): string[] {
  const candidates: Array<string | undefined> = [];

  // Environment hints. UNREAL_ENGINE_PATH usually points to the engine root.
  if (process.env.UNREAL_ENGINE_PATH) {
    const root = process.env.UNREAL_ENGINE_PATH;
    if (process.platform === 'win32') {
      candidates.push(path.join(root, 'Engine', 'Binaries', 'Win64', 'UnrealEditor.exe'));
      candidates.push(path.join(root, 'Engine', 'Binaries', 'Win64', 'UE4Editor.exe'));
    } else if (process.platform === 'darwin') {
      candidates.push(
        path.join(root, 'Engine', 'Binaries', 'Mac', 'UnrealEditor.app', 'Contents', 'MacOS', 'UnrealEditor'),
      );
      candidates.push(
        path.join(root, 'Engine', 'Binaries', 'Mac', 'UE4Editor.app', 'Contents', 'MacOS', 'UE4Editor'),
      );
    } else {
      candidates.push(path.join(root, 'Engine', 'Binaries', 'Linux', 'UnrealEditor'));
      candidates.push(path.join(root, 'Engine', 'Binaries', 'Linux', 'UE4Editor'));
    }
  }

  if (process.platform === 'win32') {
    // Typical Epic Games Launcher installs.
    candidates.push('C://Program Files//Epic Games//UE_5.3//Engine//Binaries//Win64//UnrealEditor.exe');
    candidates.push('C://Program Files//Epic Games//UE_5.2//Engine//Binaries//Win64//UnrealEditor.exe');
    candidates.push('C://Program Files//Epic Games//UE_4.27//Engine//Binaries//Win64//UE4Editor.exe');
  } else if (process.platform === 'darwin') {
    // macOS bundle paths for UE5/UE4.
    candidates.push(
      '/Applications/Epic Games/UE_5.3/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor',
    );
    candidates.push(
      '/Applications/Epic Games/UE_4.27/Engine/Binaries/Mac/UE4Editor.app/Contents/MacOS/UE4Editor',
    );
  } else {
    // Linux source builds and launcher installs.
    const homeDir = os.homedir();
    candidates.push(path.join(homeDir, 'UnrealEngine', 'Engine', 'Binaries', 'Linux', 'UnrealEditor'));
    candidates.push(path.join(homeDir, 'UnrealEngine', 'Engine', 'Binaries', 'Linux', 'UE4Editor'));
    candidates.push('/opt/unreal-engine/Engine/Binaries/Linux/UnrealEditor');
  }

  return candidates.filter(Boolean) as string[];
}

export async function detectEnvironment(): Promise<{
  pythonPathGuess?: string;
  dccs: {
    maya?: string;
    blender?: string;
    unreal?: string;
  };
}> {
  const pythonPathGuess = detectPython();

  const maya = firstExisting(mayaCandidates());
  const blender = firstExisting(blenderCandidates());
  const unreal = firstExisting(unrealCandidates());

  return {
    pythonPathGuess,
    dccs: {
      maya,
      blender,
      unreal,
    },
  };
}

function getCurrentUsername(): string | null {
  try {
    const userInfo = os.userInfo();
    if (userInfo.username) {
      return userInfo.username;
    }
  } catch (error) {
    console.warn('Unable to determine current username', error);
  }

  return process.env.USER || process.env.USERNAME || null;
}

export function registerEnvIpcHandlers(ipcMain: IpcMain): void {
  ipcMain.handle('system/detect-env', async () => detectEnvironment());
  ipcMain.handle('system/get-username', async () => getCurrentUsername());
}
