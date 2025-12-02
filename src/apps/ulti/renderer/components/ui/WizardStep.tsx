import React, { type ReactNode } from 'react';

const animationStyles = `
@keyframes op-wizard-fade-slide {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
`;

interface WizardStepProps {
  stepKey: number | string;
  children: ReactNode;
}

function WizardStep({ stepKey, children }: WizardStepProps): JSX.Element {
  return (
    <>
      <style>{animationStyles}</style>
      <div key={stepKey} style={{ animation: 'op-wizard-fade-slide 180ms ease' }}>
        {children}
      </div>
    </>
  );
}

export default WizardStep;
