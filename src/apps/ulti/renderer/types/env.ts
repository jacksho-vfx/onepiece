export type DccAppKey = 'maya' | 'blender' | 'unreal';

export type PackagedRuntimeStatus = {
  present: boolean;
  bundlePath?: string;
  manifestPath?: string;
  manifestSource?: string;
  searchedPaths: string[];
  missing?: string[];
  error?: string;
};

export type DetectedEnv = {
  pythonPathGuess?: string;
  dccs: Partial<Record<DccAppKey, string>>;
  system: {
    platform: NodeJS.Platform;
    release: string;
    arch: string;
  };
  nodeEnv?: string;
  packagedRuntime: PackagedRuntimeStatus;
};
