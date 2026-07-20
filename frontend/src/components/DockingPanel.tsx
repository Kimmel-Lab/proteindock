import { useState, useEffect, useRef } from 'react';
import { Play, FileCode, Settings, Trophy, Eye, ChevronDown, ChevronUp, Square, Zap, Table2, Loader2, Download, ExternalLink, Share2, Image, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Progress } from '@/components/ui/progress';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { SortableTable } from '@/components/SortableTable';
import { EnhancedProgress } from '@/components/EnhancedProgress';
import { DockingScoreBarChart } from '@/components/DockingCharts';
import { TableSkeleton, ResultsSkeleton } from '@/components/SkeletonLoader';
import { useToast } from '@/hooks/use-toast';
import { BASE, downloadShareHtml } from '@/services/api';
import type { DockingState, SequentialStep } from '@/types/docking';

interface DockingPanelProps {
  dockingState: DockingState;
  canDock: boolean;
  optionsContent: string;
  xmlContent: string;
  projectName: string;
  onOptionsChange: (content: string) => void;
  onRunDocking: () => void;
  onVisualize: () => void;
  onCancelDocking?: () => void;
  liveScores?: Array<{ score: number; desc: string }>;
  currentStructure?: number;
  totalStructures?: number;
  dockingStartTime?: Date;
}

// CSS-only confetti celebration
function CelebrationEffect() {
  const pieces = Array.from({ length: 20 }, (_, i) => ({
    id: i,
    left: `${Math.random() * 100}%`,
    delay: `${Math.random() * 0.5}s`,
    duration: `${1 + Math.random() * 1.5}s`,
    color: ['bg-primary', 'bg-success', 'bg-warning', 'bg-primary/60', 'bg-success/60'][i % 5],
    size: Math.random() > 0.5 ? 'w-2 h-2' : 'w-1.5 h-3',
  }));

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none z-10">
      {pieces.map((piece) => (
        <div
          key={piece.id}
          className={`absolute ${piece.color} ${piece.size} rounded-sm`}
          style={{
            left: piece.left,
            top: '-10px',
            animation: `confetti-fall ${piece.duration} ease-out ${piece.delay} forwards`,
          }}
        />
      ))}
    </div>
  );
}

// Sequential Assembly Timeline
function SequentialTimeline({ steps, currentStep, totalSteps, stepPhase }: {
  steps?: SequentialStep[];
  currentStep?: number;
  totalSteps?: number;
  stepPhase?: string;
}) {
  if (!totalSteps) return null;

  const displaySteps = steps && steps.length > 0
    ? steps
    : Array.from({ length: totalSteps }, (_, i) => ({
        step: i + 1,
        status: (i + 1 < (currentStep || 1) ? 'completed'
          : i + 1 === (currentStep || 1) ? 'docking'
          : 'pending') as SequentialStep['status'],
      }));

  const completedCount = displaySteps.filter(s => s.status === 'completed').length;

  return (
    <div className="p-3 bg-card rounded-lg border border-primary/20">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-4 h-4 text-primary" />
        <span className="text-xs font-semibold uppercase tracking-wider">Sequential Assembly</span>
        <span className="text-xs text-muted-foreground ml-auto">
          {completedCount}/{totalSteps} steps
        </span>
      </div>

      {/* Overall progress bar */}
      <div className="h-2 bg-muted rounded-full overflow-hidden mb-3">
        <div
          className="h-full bg-gradient-to-r from-primary to-success rounded-full transition-all duration-500"
          style={{ width: `${Math.round((completedCount / totalSteps) * 100)}%` }}
        />
      </div>

      {/* Step indicators */}
      <div className="space-y-1.5">
        {displaySteps.map((step) => {
          const isCurrent = step.step === currentStep;
          const isCompleted = step.status === 'completed';
          const isFailed = step.status === 'failed';

          return (
            <div
              key={step.step}
              className={`flex items-center gap-2 px-2 py-1.5 rounded-md text-xs transition-all ${
                isCurrent ? 'bg-primary/10 border border-primary/30' :
                isCompleted ? 'bg-success/5' :
                isFailed ? 'bg-destructive/5' : ''
              }`}
            >
              {/* Status icon */}
              <div className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
                isCompleted ? 'bg-success text-white' :
                isFailed ? 'bg-destructive text-white' :
                isCurrent ? 'bg-primary text-white' :
                'bg-muted text-muted-foreground'
              }`}>
                {isCompleted ? (
                  <Check className="w-3 h-3" />
                ) : isCurrent ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <span className="text-[10px] font-bold">{step.step}</span>
                )}
              </div>

              {/* Label */}
              <span className={`font-mono ${isCurrent ? 'font-bold text-primary' : isCompleted ? 'text-success' : 'text-muted-foreground'}`}>
                Step {step.step}
              </span>

              {/* Phase for current step */}
              {isCurrent && stepPhase && (
                <span className="text-primary/70 ml-1 truncate">{stepPhase}</span>
              )}

              {/* Score for completed steps */}
              {isCompleted && step.best_score != null && (
                <span className="font-mono font-bold text-success ml-auto">
                  {step.best_score.toFixed(1)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function DockingPanel({
  dockingState,
  canDock,
  optionsContent,
  xmlContent,
  projectName,
  onOptionsChange,
  onRunDocking,
  onVisualize,
  onCancelDocking,
  liveScores = [],
  currentStructure = 0,
  totalStructures = 0,
  dockingStartTime,
}: DockingPanelProps) {
  const { toast } = useToast();
  const [showOptions, setShowOptions] = useState(false);
  const [showXml, setShowXml] = useState(false);
  const [showConfetti, setShowConfetti] = useState(false);
  const logContainerRef = useRef<HTMLDivElement>(null);

  const [selectedPdbPath, setSelectedPdbPath] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const isRunning = dockingState.status === 'running';
  const isComplete = dockingState.status === 'complete';

  // Auto-scroll logs to bottom
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [dockingState.logs]);

  // Trigger confetti on completion and auto-select best model for 3D viewer
  useEffect(() => {
    if (isComplete && dockingState.bestScore) {
      setShowConfetti(true);
      if (dockingState.bestPdbPath) {
        setSelectedPdbPath(dockingState.bestPdbPath);
      }
      const timer = setTimeout(() => setShowConfetti(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [isComplete, dockingState.bestScore, dockingState.bestPdbPath]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
          isComplete
            ? 'bg-success text-success-foreground'
            : 'bg-primary text-primary-foreground'
        }`}>
          3
        </div>
        <h2 className="font-semibold">Docking</h2>
      </div>

      <div className="panel-card">
        <div className="panel-header">
          <Play className="w-4 h-4" />
          <span>Rosetta Docking</span>
        </div>
        <div className="p-4 space-y-4">
          {/* Options File */}
          <Collapsible open={showOptions} onOpenChange={setShowOptions}>
            <CollapsibleTrigger asChild>
              <Button variant="outline" className="w-full justify-between">
                <div className="flex items-center gap-2">
                  <Settings className="w-4 h-4" />
                  <span>docking.options.txt</span>
                  <span className="text-xs text-muted-foreground">(editable)</span>
                </div>
                {showOptions ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
              <Textarea
                value={optionsContent}
                onChange={(e) => onOptionsChange(e.target.value)}
                className="font-mono text-xs h-48 resize-none"
                placeholder="Docking options will appear here..."
              />
            </CollapsibleContent>
          </Collapsible>

          {/* XML Protocol */}
          <Collapsible open={showXml} onOpenChange={setShowXml}>
            <CollapsibleTrigger asChild>
              <Button variant="outline" className="w-full justify-between">
                <div className="flex items-center gap-2">
                  <FileCode className="w-4 h-4" />
                  <span>docking_full.xml</span>
                  <span className="text-xs text-muted-foreground">(read-only)</span>
                </div>
                {showXml ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
              <Textarea
                value={xmlContent}
                readOnly
                className="font-mono text-xs h-48 resize-none bg-muted"
                placeholder="XML protocol will appear here..."
              />
            </CollapsibleContent>
          </Collapsible>

          {/* Run Button — morphs based on state */}
          <Button
            className={`w-full h-14 text-lg shadow-xl transition-all duration-500 ${
              isComplete
                ? 'bg-gradient-success hover:shadow-glow-success'
                : isRunning
                  ? 'bg-primary/80 cursor-wait'
                  : 'bg-gradient-scarlet hover:shadow-2xl hover:shadow-primary/30 hover:-translate-y-1'
            }`}
            size="lg"
            disabled={!canDock || isRunning}
            onClick={onRunDocking}
          >
            {isComplete ? (
              <>
                <Trophy className="w-5 h-5" />
                <span style={{ fontFamily: 'Oswald, sans-serif' }}>Docking Complete</span>
              </>
            ) : isRunning ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Running Docking...</span>
              </>
            ) : (
              <>
                <Play className="w-5 h-5" />
                <span style={{ fontFamily: 'Oswald, sans-serif' }}>Run Rosetta Docking</span>
              </>
            )}
          </Button>

          {/* Enhanced Progress */}
          {isRunning && (
            <div className="space-y-4">
              {/* Sequential timeline or standard progress */}
              {dockingState.mode === 'sequential' ? (
                <SequentialTimeline
                  steps={dockingState.steps}
                  currentStep={dockingState.currentStep}
                  totalSteps={dockingState.totalSteps}
                  stepPhase={dockingState.stepPhase}
                />
              ) : (
                <EnhancedProgress
                  current={currentStructure}
                  total={totalStructures}
                  startTime={dockingStartTime}
                  label="Docking in progress"
                />
              )}

              {/* Live Scores */}
              {liveScores.length > 0 && (
                <div className="p-3 bg-card rounded-lg border border-primary/20">
                  <div className="flex items-center gap-2 mb-2">
                    <Zap className="w-4 h-4 text-warning" />
                    <span className="text-xs font-semibold uppercase tracking-wider">Live Scores</span>
                  </div>
                  <div className="space-y-1 max-h-24 overflow-y-auto">
                    {liveScores.slice(-5).map((s, i) => (
                      <div key={i} className="flex justify-between text-xs font-mono">
                        <span className="text-muted-foreground truncate">{s.desc}</span>
                        <span className={`font-bold ${s.score < -200 ? 'text-success' : s.score < -100 ? 'text-warning' : 'text-foreground'}`}>
                          {s.score.toFixed(1)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Cancel Button */}
              {onCancelDocking && (
                <Button
                  variant="outline"
                  className="w-full border-destructive/50 text-destructive hover:bg-destructive/10"
                  onClick={onCancelDocking}
                >
                  <Square className="w-4 h-4 mr-2" />
                  Cancel Docking
                </Button>
              )}

              <p className="text-xs text-muted-foreground text-center">
                This may take several minutes depending on protein size and nstruct value
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Log Output */}
      <div className="panel-card">
        <div className="panel-header">
          <span>Docking Log</span>
          {dockingState.logs.length > 0 && (
            <span className="text-xs text-muted-foreground ml-auto">
              {dockingState.logs.length} entries
            </span>
          )}
          {isRunning && (
            <div className="w-2 h-2 rounded-full bg-success animate-pulse ml-2" />
          )}
        </div>
        <div ref={logContainerRef} className="log-container">
          {dockingState.logs.length === 0 ? (
            <span className="text-muted-foreground">Waiting for docking to start...</span>
          ) : (
            dockingState.logs.map((log, i) => (
              <div
                key={i}
                className={`py-0.5 ${
                  log.includes('complete') ? 'text-success' :
                  log.includes('failed') || log.includes('FAILED') ? 'text-destructive' :
                  log.includes('SCORE:') ? 'text-primary font-semibold' :
                  ''
                }`}
              >
                {log}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Results */}
      {isComplete && dockingState.bestScore && (
        <>
          <div className="relative">
            {showConfetti && <CelebrationEffect />}
            <div className="panel-card border-2 border-success/40 overflow-hidden shadow-glow-success animate-scale-in">
              <div className="panel-header bg-gradient-success text-white shadow-layered">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-white/20">
                    <Trophy className="w-5 h-5" />
                  </div>
                  <span className="font-bold text-lg">Docking Complete!</span>
                </div>
              </div>
              <div className="p-6 space-y-5 bg-gradient-to-br from-success/8 via-success/5 to-success/3">
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-5 glass rounded-xl border-2 border-success/30 shadow-layered hover:shadow-glow-success transition-smooth">
                    <p className="text-xs text-muted-foreground mb-2 uppercase tracking-wider font-bold">Best Score</p>
                    <p className="text-4xl font-extrabold font-mono text-gradient-success animate-fade-in" style={{ fontFamily: 'Oswald, sans-serif' }}>
                      {dockingState.bestScore.toFixed(2)}
                    </p>
                    {/* Score range context */}
                    {dockingState.allModels && dockingState.allModels.length > 1 && (() => {
                      const scores = dockingState.allModels!.map(m => m.score);
                      const min = Math.min(...scores);
                      const max = Math.max(...scores);
                      const range = max - min || 1;
                      const bestPercent = ((dockingState.bestScore! - min) / range) * 100;
                      return (
                        <div className="mt-3">
                          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-gradient-to-r from-success to-success/60 rounded-full transition-all duration-700"
                              style={{ width: `${Math.max(5, bestPercent)}%` }}
                            />
                          </div>
                          <p className="text-xs text-muted-foreground mt-1">
                            Range: {min.toFixed(0)} to {max.toFixed(0)} REU
                          </p>
                        </div>
                      );
                    })()}
                  </div>
                  <div className="p-5 glass rounded-xl border-2 border-border/50 shadow-layered hover-lift">
                    <p className="text-xs text-muted-foreground mb-2 uppercase tracking-wider font-bold">Best Model</p>
                    <p className="text-sm font-mono truncate text-foreground font-semibold">{dockingState.bestModel}</p>
                    <p className="text-xs text-muted-foreground mt-3">
                      {dockingState.allModels?.length || 0} models generated
                    </p>
                  </div>
                </div>
                <div className="flex gap-3">
                  <Button
                    className="flex-1 h-12 text-base bg-gradient-success hover:shadow-glow-success transition-smooth hover:scale-105 font-bold"
                    onClick={onVisualize}
                  >
                    <Eye className="w-5 h-5 mr-2" />
                    Render PyMOL Image
                  </Button>
                  <Button
                    variant="outline"
                    className="h-12 px-5 border-primary/40 text-primary hover:bg-primary/10 transition-smooth font-semibold"
                    disabled={isExporting}
                    onClick={async () => {
                      setIsExporting(true);
                      try {
                        await downloadShareHtml(projectName, selectedPdbPath || undefined);
                        toast({ title: 'Report exported!', description: 'Self-contained HTML report downloaded.' });
                      } catch (e: any) {
                        toast({ title: 'Export failed', description: e.message, variant: 'destructive' });
                      } finally {
                        setIsExporting(false);
                      }
                    }}
                  >
                    {isExporting ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Share2 className="w-4 h-4 mr-2" />}
                    Share
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Structure Viewer — PyMOL rendered image + download tools */}
          <div className="panel-card animate-fade-in">
            <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-primary/20 text-primary shadow-layered">
                  <Image className="w-4 h-4" />
                </div>
                <span className="font-bold">Structure Viewer</span>
              </div>
              {selectedPdbPath && (
                <span className="text-xs text-muted-foreground ml-auto font-mono truncate max-w-[200px]">
                  {selectedPdbPath.split('/').pop()}
                </span>
              )}
            </div>
            <div className="p-4 space-y-4">
              {/* PyMOL rendered image */}
              {selectedPdbPath && (
                <div className="relative rounded-xl overflow-hidden border border-border shadow-layered bg-muted/30">
                  <img
                    src={`${BASE}/pdb-image?path=${encodeURIComponent(selectedPdbPath)}`}
                    alt="PyMOL render"
                    className="w-full object-contain"
                    style={{ maxHeight: 420 }}
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                      (e.target as HTMLImageElement).nextElementSibling?.classList.remove('hidden');
                    }}
                  />
                  <div className="hidden flex items-center justify-center p-8 text-sm text-muted-foreground">
                    No image yet — click "Render PyMOL Image" above to generate one.
                  </div>
                </div>
              )}

              {/* Download buttons */}
              {selectedPdbPath && (
                <div className="flex gap-2 flex-wrap">
                  <Button
                    size="sm"
                    className="flex-1 bg-gradient-to-r from-primary to-primary/80 hover:shadow-lg"
                    onClick={async () => {
                      try {
                        const fd = new FormData();
                        fd.append('path', selectedPdbPath);
                        await fetch(`${BASE}/open-pymol`, { method: 'POST', body: fd });
                        toast({ title: 'PyMOL Launched', description: 'Opening in PyMOL on the server...' });
                      } catch (e: any) {
                        toast({ title: 'Failed to launch PyMOL', description: e.message, variant: 'destructive' });
                      }
                    }}
                  >
                    <ExternalLink className="w-4 h-4 mr-2" />
                    Open in PyMOL
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => window.open(`${BASE}/download?path=${encodeURIComponent(selectedPdbPath)}`, '_blank')}
                  >
                    <Download className="w-4 h-4 mr-2" />
                    Download PDB
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => window.open(`${BASE}/pymol-script?path=${encodeURIComponent(selectedPdbPath)}`, '_blank')}
                  >
                    <FileCode className="w-4 h-4 mr-2" />
                    PyMOL Script
                  </Button>
                </div>
              )}

              {/* Model selector */}
              {dockingState.allModels && dockingState.allModels.length > 1 && (
                <div className="flex gap-1.5 flex-wrap">
                  {dockingState.allModels.map((model) => (
                    <Button
                      key={model.desc}
                      size="sm"
                      variant={selectedPdbPath === model.pdb_path ? 'default' : 'outline'}
                      className="text-xs h-7 px-2 font-mono"
                      onClick={() => model.pdb_path && setSelectedPdbPath(model.pdb_path)}
                      disabled={!model.pdb_path}
                    >
                      {model.desc === dockingState.bestModel ? '* ' : ''}{model.index ?? '?'}
                    </Button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Score Distribution Chart */}
          {dockingState.allModels && dockingState.allModels.length > 0 && (
            <DockingScoreBarChart
              models={dockingState.allModels}
              bestModelDesc={dockingState.bestModel}
            />
          )}

          {/* Enhanced Results Table */}
          {dockingState.allModels && dockingState.allModels.length > 0 ? (
            <div className="panel-card animate-fade-in">
              <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-primary/20 text-primary shadow-layered">
                    <Table2 className="w-4 h-4" />
                  </div>
                  <span className="font-bold">All Docking Results</span>
                </div>
                <span className="text-xs text-muted-foreground ml-auto bg-primary/10 px-2.5 py-1 rounded-full border border-primary/20 font-semibold">
                  {dockingState.allModels.length} models
                </span>
              </div>
              <div className="p-6">
                <SortableTable
                  models={dockingState.allModels}
                  bestModelDesc={dockingState.bestModel}
                  onExport={() => toast({ title: 'Exported!', description: 'Results saved to CSV file' })}
                />
              </div>
            </div>
          ) : !dockingState.allModels ? (
            <ResultsSkeleton />
          ) : null}
        </>
      )}
    </div>
  );
}
