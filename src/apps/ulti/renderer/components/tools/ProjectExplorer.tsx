import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Card, SectionHeader, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';
import VendorIngestWizard from '../workflows/VendorIngestWizard';

export type FsNode = {
  path: string;
  name: string;
  isDir: boolean;
  children?: FsNode[];
};

type Project = { name: string; path: string };

type ProjectExplorerProps = {
  project?: Project | null;
};

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

const INDENT_PER_LEVEL = 18;

function ProjectExplorer({ project }: ProjectExplorerProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const [rootNode, setRootNode] = useState<FsNode | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [ingestPath, setIngestPath] = useState<string | null>(null);
  const [isIngestOpen, setIsIngestOpen] = useState(false);

  const updateNodeInTree = useCallback((node: FsNode, targetPath: string, updated: FsNode): FsNode => {
    if (node.path === targetPath) {
      return { ...updated };
    }

    if (!node.children) {
      return node;
    }

    return {
      ...node,
      children: node.children.map((child) => updateNodeInTree(child, targetPath, updated)),
    };
  }, []);

  const fetchRoot = useCallback(async (): Promise<void> => {
    if (!project?.path) {
      setRootNode(null);
      setExpandedPaths(new Set());
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const node = await window.electron.invoke<FsNode>('fs/list-directory', {
        root: project.path,
        depth: 2,
      });
      setRootNode(node);
      setExpandedPaths(new Set([node.path]));
    } catch (err) {
      console.error('Failed to load project tree', err);
      setError('Unable to load project structure.');
    } finally {
      setLoading(false);
    }
  }, [project]);

  useEffect(() => {
    void fetchRoot();
  }, [fetchRoot]);

  const loadNode = useCallback(
    async (node: FsNode): Promise<void> => {
      if (!node.isDir) {
        return;
      }

      setLoadingPaths((prev) => new Set(prev).add(node.path));

      try {
        const updatedNode = await window.electron.invoke<FsNode>('fs/list-directory', {
          root: node.path,
          depth: 2,
        });

        setRootNode((prev) => (prev ? updateNodeInTree(prev, node.path, updatedNode) : updatedNode));
      } catch (err) {
        console.error('Failed to load directory', err);
        setError('Unable to read one of the folders.');
      } finally {
        setLoadingPaths((prev) => {
          const next = new Set(prev);
          next.delete(node.path);
          return next;
        });
      }
    },
    [updateNodeInTree],
  );

  const handleToggleNode = (node: FsNode): void => {
    if (!node.isDir) {
      return;
    }

    setExpandedPaths((prev) => {
      const next = new Set(prev);
      const willExpand = !next.has(node.path);

      if (willExpand) {
        next.add(node.path);
        if (!node.children) {
          void loadNode(node);
        }
      } else {
        next.delete(node.path);
      }

      return next;
    });
  };

  const handleOpenInOs = useCallback(
    async (targetPath: string): Promise<void> => {
      try {
        await window.electron.invoke('fs/open-in-os', { path: targetPath });
      } catch (err) {
        console.error('Failed to open path in OS', err);
        showToast({
          title: 'Open failed',
          description: 'Unable to open this path in Finder/Explorer.',
          variant: 'error',
        });
      }
    },
    [showToast],
  );

  const handleRunIngest = (targetPath: string): void => {
    if (!project) {
      setError('Select a project to run ingest actions.');
      return;
    }

    setIngestPath(targetPath);
    setIsIngestOpen(true);
  };

  const nodeMetadata = useCallback(
    (node: FsNode): string => {
      if (node.isDir) {
        const count = node.children?.length;
        return typeof count === 'number' ? `${count} item${count === 1 ? '' : 's'}` : 'Folder';
      }

      return 'File';
    },
    [],
  );

  const renderActions = useCallback(
    (node: FsNode) => {
      const actions: JSX.Element[] = [];
      const name = node.name.toLowerCase();
      const isRendersFolder = name === 'renders' || name === 'render' || name === 'output';
      const isIngestFolder = ['plates', 'footage', 'vendors', 'ingest'].includes(name);

      if (node.isDir && isIngestFolder) {
        actions.push(
          <Button key="ingest" variant="ghost" size="sm" onClick={() => handleRunIngest(node.path)}>
            Run Vendor Ingest here
          </Button>,
        );
      }

      if (node.isDir && isRendersFolder) {
        actions.push(
          <Button key="open-renders" variant="ghost" size="sm" onClick={() => void handleOpenInOs(node.path)}>
            Open renders
          </Button>,
        );
      }

      actions.push(
        <Button key="open" variant="ghost" size="sm" onClick={() => void handleOpenInOs(node.path)}>
          Open in Finder/Explorer
        </Button>,
      );

      return actions;
    },
    [handleOpenInOs, handleRunIngest],
  );

  const renderNode = useCallback(
    (node: FsNode, depth = 0): JSX.Element => {
      const isExpanded = expandedPaths.has(node.path);
      const isLoadingNode = loadingPaths.has(node.path);
      const hasChildren = Boolean(node.children?.length);

      return (
        <div key={node.path} style={{ padding: `${theme.spacing.xs} 0`, paddingLeft: depth * INDENT_PER_LEVEL }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: theme.spacing.sm,
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm, flex: 1, minWidth: 0 }}>
              {node.isDir ? (
                <button
                  type="button"
                  onClick={() => handleToggleNode(node)}
                  aria-expanded={isExpanded}
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: theme.radii.sm,
                    border: `1px solid ${theme.colors.border}`,
                    background: theme.colors.surfaceAlt,
                    color: theme.colors.text,
                    cursor: 'pointer',
                  }}
                >
                  {isExpanded ? '▾' : '▸'}
                </button>
              ) : (
                <span style={{ width: 28, textAlign: 'center' }}>•</span>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.xs }}>
                  <span style={{ fontWeight: theme.typography.fontWeightMedium }}>{node.name}</span>
                  <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
                    {node.isDir ? 'Folder' : 'File'}
                  </span>
                </div>
                <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
                  {isLoadingNode ? 'Loading…' : nodeMetadata(node)}
                </span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: theme.spacing.xs, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {renderActions(node)}
            </div>
          </div>
          {node.isDir && isExpanded && hasChildren ? (
            <div style={{ borderLeft: `1px dashed ${theme.colors.border}`, marginLeft: 14 }}>
              {node.children?.map((child) => renderNode(child, depth + 1))}
            </div>
          ) : null}
          {node.isDir && isExpanded && !hasChildren && !isLoadingNode ? (
            <div style={{ color: theme.colors.textMuted, paddingLeft: INDENT_PER_LEVEL, fontSize: theme.typography.fontSizeSm }}>
              Empty folder
            </div>
          ) : null}
        </div>
      );
    },
    [expandedPaths, handleToggleNode, loadingPaths, nodeMetadata, renderActions, theme],
  );

  const headerSubtitle = useMemo(() => {
    if (!project) {
      return 'Select a project to browse its structure.';
    }

    return project.path;
  }, [project]);

  return (
    <Card>
      <SectionHeader title="Project Explorer" subtitle={headerSubtitle} />
      {!project ? (
        <div style={{ padding: `${theme.spacing.lg} ${theme.spacing.md}`, color: theme.colors.textMuted }}>
          <h3 style={{ margin: 0, marginBottom: theme.spacing.xs }}>No project selected</h3>
          <p style={{ margin: 0 }}>Select a project to browse its structure.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: theme.spacing.md }}>
          {loading ? (
            <p style={{ color: theme.colors.textMuted }}>Loading project tree…</p>
          ) : error ? (
            <p style={{ color: theme.colors.danger }}>{error}</p>
          ) : rootNode ? (
            <div
              style={{
                background: theme.colors.surfaceAlt,
                border: `1px solid ${theme.colors.border}`,
                borderRadius: theme.radii.md,
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
              }}
            >
              {renderNode(rootNode)}
            </div>
          ) : (
            <p style={{ color: theme.colors.textMuted }}>No items to display.</p>
          )}
        </div>
      )}
      <VendorIngestWizard
        isOpen={isIngestOpen}
        project={project ?? null}
        initialSourcePath={ingestPath ?? undefined}
        onClose={() => {
          setIsIngestOpen(false);
          setIngestPath(null);
        }}
        onCompleted={() => {
          setIsIngestOpen(false);
          setIngestPath(null);
        }}
        onViewTasks={() => setIsIngestOpen(false)}
      />
    </Card>
  );
}

export default ProjectExplorer;
