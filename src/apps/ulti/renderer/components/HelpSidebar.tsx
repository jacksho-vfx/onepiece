import React from 'react';
import { Button } from './ui';
import { useTheme } from '../styles/ThemeContext';

interface HelpLink {
  label: string;
  href: string;
}

interface HelpContent {
  title: string;
  description: string[];
  links?: HelpLink[];
}

const HELP_CONTENT: Record<string, HelpContent> = {
  'home.overview': {
    title: 'Project overview',
    description: [
      'View the current project status, recent tasks, and quick entry points to start a workflow.',
      'Use the tabs on this page to jump between health, services, and shortcuts.',
    ],
    links: [
      { label: 'Desktop overview docs', href: 'https://docs.onepiece.io/desktop/overview' },
      { label: 'Managing projects', href: 'https://docs.onepiece.io/desktop/projects' },
    ],
  },
  'wizard.vendorIngest.step1': {
    title: 'Select a vendor source',
    description: [
      'Point the wizard at the folder containing vendor deliveries. The path is remembered per project.',
      'Make sure the selected project matches the delivery you are about to ingest.',
    ],
    links: [
      { label: 'Vendor ingest guide', href: 'https://docs.onepiece.io/ingest/vendor/overview' },
      { label: 'Folder structure tips', href: 'https://docs.onepiece.io/ingest/vendor/checklist' },
    ],
  },
  'wizard.vendorIngest.step2': {
    title: 'Preflight your ingest',
    description: [
      'Run a preflight to count files, validate naming, and catch missing deliveries before running ingest.',
      'Resolve errors before continuing; warnings can often be fixed after the initial import.',
    ],
    links: [
      { label: 'Preflight checks', href: 'https://docs.onepiece.io/ingest/vendor/preflight' },
      { label: 'Troubleshooting ingest', href: 'https://docs.onepiece.io/ingest/vendor/troubleshooting' },
    ],
  },
  'wizard.dccPublish.preflight': {
    title: 'Publish preflight',
    description: [
      'Validate your scene before publishing. Check for missing textures, broken references, and warnings.',
      'Use the collections list to spot problematic assets and fix them in your DCC before continuing.',
    ],
    links: [
      { label: 'DCC publish checklist', href: 'https://docs.onepiece.io/publish/dcc/preflight' },
      { label: 'Scene validation FAQ', href: 'https://docs.onepiece.io/publish/dcc/faq' },
    ],
  },
};

const fallbackContent: HelpContent = {
  title: 'Need help?',
  description: [
    'Choose a workflow on the left to see guidance, tips, and links to the relevant documentation.',
    'Help updates automatically as you move through the app.',
  ],
  links: [{ label: 'OnePiece docs', href: 'https://docs.onepiece.io/' }],
};

function HelpSidebar({ contextKey }: { contextKey?: string | null }): JSX.Element {
  const theme = useTheme();
  const content = (contextKey ? HELP_CONTENT[contextKey] : undefined) ?? fallbackContent;

  return (
    <aside
      aria-label="Contextual help"
      style={{
        background: theme.colors.surfaceAlt,
        border: `1px solid ${theme.colors.border}`,
        borderRadius: theme.radii.lg,
        padding: theme.spacing.lg,
        boxShadow: theme.shadow.card,
        minWidth: '280px',
        maxWidth: '360px',
        position: 'sticky',
        top: '100px',
        display: 'grid',
        gap: theme.spacing.md,
        alignSelf: 'flex-start',
      }}
    >
      <div style={{ display: 'grid', gap: theme.spacing.xs }}>
        <p
          style={{
            margin: 0,
            color: theme.colors.textMuted,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            fontSize: theme.typography.fontSizeXs,
            fontWeight: theme.typography.fontWeightBold,
          }}
        >
          Help
        </p>
        <h3 style={{ margin: 0 }}>{content.title}</h3>
        {content.description.map((paragraph) => (
          <p key={paragraph} style={{ margin: 0, color: theme.colors.textMuted, lineHeight: 1.5 }}>
            {paragraph}
          </p>
        ))}
      </div>

      {content.links?.length ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: theme.spacing.sm }}>
          {content.links.map((link) => (
            <a
              key={link.href}
              href={link.href}
              target="_blank"
              rel="noreferrer"
              style={{ textDecoration: 'none' }}
            >
              <Button variant="ghost" fullWidth style={{ justifyContent: 'space-between' }}>
                <span>{link.label}</span>
                <span aria-hidden>↗</span>
              </Button>
            </a>
          ))}
        </div>
      ) : null}
    </aside>
  );
}

export default HelpSidebar;
