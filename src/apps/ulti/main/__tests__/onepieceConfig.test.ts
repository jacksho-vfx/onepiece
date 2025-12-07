import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({
  app: {
    getAppPath: vi.fn(),
    getPath: vi.fn(),
  },
}));

import { generateOnepieceToml } from '../onepieceConfig';

describe('generateOnepieceToml', () => {

  const baseInput = {
    profile: 'vfx' as const,
    projectRoot: '/projects/example',
  };

  it('includes VFX pipeline templates by default for VFX profiles', () => {
    const output = generateOnepieceToml(baseInput);

    expect(output).toContain('[pipelines.ingest]');
    expect(output).toContain('display_name = "Vendor Ingest"');
    expect(output).toContain('log_file = "logs/pipeline/render.log"');
    expect(output).toContain('[pipelines.delivery]');
  });

  it('omits pipeline templates when explicitly disabled', () => {
    const output = generateOnepieceToml({
      ...baseInput,
      includePipelineTemplates: false,
    });

    expect(output).not.toContain('[pipelines.ingest]');
    expect(output).not.toContain('[pipelines.render]');
    expect(output).not.toContain('[pipelines.delivery]');
  });

  it('does not inject VFX pipelines for non-VFX profiles even when toggled', () => {
    const output = generateOnepieceToml({
      ...baseInput,
      profile: 'archviz',
      includePipelineTemplates: true,
    });

    expect(output).not.toContain('[pipelines.ingest]');
    expect(output).not.toContain('Vendor Ingest');
  });
});
