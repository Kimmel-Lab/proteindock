import { Sparkles, Link2, Hash, Merge, Check, Loader2, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { ProcessingState, StepStatus } from '@/types/docking';

interface PreprocessingPanelProps {
  processingState: ProcessingState;
  canProcess: boolean;
  onClean: () => void;
  onNormalize: () => void;
  onSanitize: () => void;
  onMerge: () => void;
  logs: string[];
}

interface StepButtonProps {
  label: string;
  description: string;
  icon: React.ReactNode;
  status: StepStatus;
  onClick: () => void;
  disabled: boolean;
  stepNumber: number;
}

function StepButton({ 
  label, 
  description, 
  icon, 
  status, 
  onClick, 
  disabled,
  stepNumber 
}: StepButtonProps) {
  const getStatusIcon = () => {
    if (status === 'complete') return <Check className="w-4 h-4" />;
    if (status === 'running') return <Loader2 className="w-4 h-4 animate-spin" />;
    if (status === 'error') return <AlertCircle className="w-4 h-4" />;
    return stepNumber;
  };

  const getStatusStyle = () => {
    if (status === 'complete') return 'bg-success text-white shadow-lg shadow-success/30';
    if (status === 'running') return 'bg-primary text-white shadow-lg shadow-primary/40 animate-pulse';
    if (status === 'error') return 'bg-destructive text-white shadow-lg shadow-destructive/30';
    return 'bg-muted text-muted-foreground';
  };

  return (
    <div className={`
      flex items-start gap-4 p-5 rounded-xl border-2 transition-smooth glass hover-lift
      ${status === 'complete' 
        ? 'border-success/40 bg-gradient-to-br from-success/10 via-success/5 to-transparent shadow-glow-success' 
        : status === 'running'
          ? 'border-primary/50 bg-gradient-to-br from-primary/10 via-primary/5 to-transparent shadow-glow-primary animate-pulse-glow'
          : status === 'error'
            ? 'border-destructive/40 bg-gradient-to-br from-destructive/10 via-destructive/5 to-transparent'
            : 'border-border/50 bg-gradient-card hover:border-primary/40 hover:shadow-layered'
      }
    `}>
      <div className={`
        w-12 h-12 rounded-full flex items-center justify-center text-sm font-bold transition-smooth shadow-layered
        ${getStatusStyle()}
      `}
        style={{ fontFamily: 'Oswald, sans-serif' }}
      >
        {getStatusIcon()}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 mb-2">
          <span className="p-2 rounded-lg bg-primary/10 text-primary shadow-layered hover:scale-110 transition-smooth">
            {icon}
          </span>
          <span className="font-bold text-sm uppercase tracking-wide" style={{ fontFamily: 'Oswald, sans-serif' }}>
            {label}
          </span>
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed">{description}</p>
      </div>
      <Button
        size="sm"
        variant={status === 'complete' ? 'outline' : 'default'}
        onClick={onClick}
        disabled={disabled || status === 'running'}
        className={`
          shrink-0 transition-smooth hover:scale-105
          ${status === 'complete' ? 'border-success/30 hover:border-success/50' : ''}
          ${status === 'running' ? 'cursor-wait' : ''}
        `}
      >
        {status === 'running' ? 'Running...' : status === 'complete' ? 'Re-run' : 'Run'}
      </Button>
    </div>
  );
}

export function PreprocessingPanel({
  processingState,
  canProcess,
  onClean,
  onNormalize,
  onSanitize,
  onMerge,
  logs,
}: PreprocessingPanelProps) {
  const steps = [
    {
      key: 'clean' as const,
      label: 'Clean with Rosetta',
      description: 'Remove non-standard residues and prepare for docking',
      icon: <Sparkles className="w-4 h-4 text-primary" />,
      onClick: onClean,
    },
    {
      key: 'normalize' as const,
      label: 'Normalize Chains',
      description: 'Assign sequential chain IDs (A, B, C, ...) to each component',
      icon: <Link2 className="w-4 h-4 text-primary" />,
      onClick: onNormalize,
    },
    {
      key: 'sanitize' as const,
      label: 'Renumber Residues',
      description: 'Fix insertion codes and ensure sequential numbering',
      icon: <Hash className="w-4 h-4 text-primary" />,
      onClick: onSanitize,
    },
    {
      key: 'merge' as const,
      label: 'Merge into Complex',
      description: 'Align all components with 2Å gap and create complex_input.pdb',
      icon: <Merge className="w-4 h-4 text-primary" />,
      onClick: onMerge,
    },
  ];

  const allComplete = Object.values(processingState).every(s => s === 'complete');

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
          allComplete 
            ? 'bg-success text-success-foreground' 
            : 'bg-primary text-primary-foreground'
        }`}>
          {allComplete ? <Check className="w-4 h-4" /> : '2'}
        </div>
        <h2 className="font-semibold">Preprocessing</h2>
      </div>

      <div className="panel-card">
        <div className="panel-header">
          <span>Processing Steps</span>
          {!canProcess && (
            <span className="text-xs text-muted-foreground ml-auto">
              Add both structures to begin
            </span>
          )}
        </div>
        <div className="p-4 space-y-3">
          {steps.map((step, index) => (
            <StepButton
              key={step.key}
              label={step.label}
              description={step.description}
              icon={step.icon}
              status={processingState[step.key]}
              onClick={step.onClick}
              disabled={!canProcess}
              stepNumber={index + 1}
            />
          ))}
        </div>
      </div>

      {logs.length > 0 && (
        <div className="panel-card">
          <div className="panel-header">
            <span>Processing Log</span>
          </div>
          <div className="log-container">
            {logs.map((log, i) => (
              <div key={i} className="py-0.5">
                {log}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
