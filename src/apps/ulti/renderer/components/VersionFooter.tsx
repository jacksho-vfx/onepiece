import React, { useEffect, useState } from 'react';

type VersionInfo = {
  desktop: string;
  onepiece: string | null;
};

function VersionFooter(): JSX.Element {
  const [versions, setVersions] = useState<VersionInfo | null>(null);

  useEffect(() => {
    let isMounted = true;

    const fetchVersions = async (): Promise<void> => {
      try {
        const result = await window.electron.invoke<VersionInfo>('version/get');
        if (isMounted) {
          setVersions(result);
        }
      } catch (error) {
        console.error('Failed to load version info', error);
      }
    };

    void fetchVersions();

    return () => {
      isMounted = false;
    };
  }, []);

  if (!versions) {
    return <div className="op-version-footer">Loading version info...</div>;
  }

  return (
    <div className="op-version-footer">
      <span>Desktop v{versions.desktop}</span>
      <span className="op-version-footer__separator">•</span>
      <span>
        {versions.onepiece ? `OnePiece v${versions.onepiece}` : 'OnePiece version: unknown'}
      </span>
    </div>
  );
}

export default VersionFooter;
