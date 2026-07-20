import { useEffect, useState } from 'react';
import { Progress } from '@/components/ui/progress';
import { Clock, Zap, TrendingUp, Loader2 } from 'lucide-react';

interface EnhancedProgressProps {
  current: number;
  total: number;
  startTime?: Date;
  label?: string;
}

export function EnhancedProgress({ current, total, startTime, label = 'Progress' }: EnhancedProgressProps) {
  const [elapsed, setElapsed] = useState(0);
  const [eta, setEta] = useState<number | null>(null);
  const [speed, setSpeed] = useState<number | null>(null);

  // Timer ticks every second from job start, regardless of current progress
  useEffect(() => {
    if (!startTime) return;

    const interval = setInterval(() => {
      const now = new Date();
      const elapsedMs = now.getTime() - startTime.getTime();
      const elapsedSec = Math.floor(elapsedMs / 1000);
      setElapsed(elapsedSec);

      // Only calculate speed and ETA when progress has started
      if (current > 0 && elapsedSec > 0) {
        const structuresPerSec = current / elapsedSec;
        setSpeed(structuresPerSec);

        if (structuresPerSec > 0) {
          const remaining = total - current;
          const etaSec = Math.ceil(remaining / structuresPerSec);
          setEta(etaSec);
        }
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [current, total, startTime]);

  const percent = total > 0 ? Math.round((current / total) * 100) : 0;
  const isWaiting = current === 0 && total > 0;

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins > 0) {
      return `${mins}m ${secs}s`;
    }
    return `${secs}s`;
  };

  const formatElapsed = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="space-y-4 p-5 bg-gradient-to-br from-primary/10 via-primary/5 to-transparent rounded-xl border-2 border-primary/20 shadow-layered">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${
            isWaiting ? 'bg-warning animate-pulse' : 'bg-primary animate-pulse'
          }`} />
          <span className="font-semibold text-foreground">
            {isWaiting ? 'Computing first structure...' : label}
          </span>
        </div>
        <span className="font-bold text-xl font-mono" style={{ fontFamily: 'Oswald, sans-serif' }}>
          {isWaiting ? (
            <span className="text-warning flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              Starting...
            </span>
          ) : (
            <span className="text-primary">{percent}%</span>
          )}
        </span>
      </div>

      {/* Progress Bar - shimmer when waiting, normal when progressing */}
      {isWaiting ? (
        <div className="relative h-3 w-full overflow-hidden rounded-full bg-secondary">
          <div className="absolute inset-0 rounded-full bg-gradient-to-r from-transparent via-warning/40 to-transparent animate-[shimmer_2s_ease-in-out_infinite]" />
        </div>
      ) : (
        <Progress value={percent} className="h-3" />
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
        {/* Current/Total */}
        <div className="flex items-center gap-2 p-2 bg-card/50 rounded-lg border border-border/50">
          <TrendingUp className="w-4 h-4 text-primary" />
          <div>
            <p className="text-xs text-muted-foreground">Progress</p>
            <p className="text-sm font-bold font-mono">
              {current} / {total}
            </p>
          </div>
        </div>

        {/* Elapsed Time - always shows when startTime exists */}
        {startTime && (
          <div className="flex items-center gap-2 p-2 bg-card/50 rounded-lg border border-border/50">
            <Clock className="w-4 h-4 text-primary" />
            <div>
              <p className="text-xs text-muted-foreground">Elapsed</p>
              <p className="text-sm font-bold font-mono">{formatElapsed(elapsed)}</p>
            </div>
          </div>
        )}

        {/* Speed - only when structures are completing */}
        {speed !== null && current > 0 && (
          <div className="flex items-center gap-2 p-2 bg-card/50 rounded-lg border border-border/50">
            <Zap className="w-4 h-4 text-warning" />
            <div>
              <p className="text-xs text-muted-foreground">Speed</p>
              <p className="text-sm font-bold font-mono">
                {speed < 0.01 ? '<0.01' : speed.toFixed(2)}/s
              </p>
            </div>
          </div>
        )}

        {/* ETA */}
        {eta !== null && current > 0 ? (
          <div className="flex items-center gap-2 p-2 bg-card/50 rounded-lg border border-border/50">
            <Clock className="w-4 h-4 text-success" />
            <div>
              <p className="text-xs text-muted-foreground">ETA</p>
              <p className="text-sm font-bold font-mono">{formatTime(eta)}</p>
            </div>
          </div>
        ) : isWaiting ? (
          <div className="flex items-center gap-2 p-2 bg-card/50 rounded-lg border border-border/50">
            <Clock className="w-4 h-4 text-muted-foreground" />
            <div>
              <p className="text-xs text-muted-foreground">ETA</p>
              <p className="text-sm font-bold font-mono text-muted-foreground">Calculating...</p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
