import { useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Cell, ReferenceLine, ResponsiveContainer,
} from 'recharts';
import type { DockingModel } from '@/types/docking';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { BarChart3, TrendingDown } from 'lucide-react';

interface DockingChartsProps {
  models: DockingModel[];
  bestModelDesc?: string;
}

interface ChartEntry extends DockingModel {
  rank: number;
  shortName: string;
  isBest: boolean;
}

// Custom tooltip
function CustomTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as ChartEntry;
  return (
    <div className="bg-card/95 backdrop-blur border-2 border-border rounded-lg p-3 shadow-layered text-sm">
      <p className="font-bold font-mono text-foreground">{data.desc}</p>
      <p className="text-primary font-bold mt-1">
        Score: {data.score.toFixed(2)} REU
      </p>
      {data.rms != null && (
        <p className="text-muted-foreground">RMS: {data.rms.toFixed(2)}</p>
      )}
      {data.I_sc != null && (
        <p className="text-muted-foreground">I_sc: {data.I_sc.toFixed(2)}</p>
      )}
      {data.isBest && (
        <p className="text-success font-bold mt-1">Best Model</p>
      )}
    </div>
  );
}

export function DockingScoreBarChart({ models, bestModelDesc }: DockingChartsProps) {
  const [selectedModel, setSelectedModel] = useState<DockingModel | null>(null);

  if (!models || models.length === 0) return null;

  // Sort by score ascending (lower is better for Rosetta)
  const sortedData: ChartEntry[] = [...models]
    .sort((a, b) => a.score - b.score)
    .map((model, index) => ({
      ...model,
      rank: index + 1,
      shortName: model.desc?.replace(/^complex_input_full_/, '#') || `#${index + 1}`,
      isBest: model.desc === bestModelDesc,
    }));

  const avgScore = models.reduce((sum, m) => sum + m.score, 0) / models.length;

  const handleBarClick = (data: any) => {
    if (data?.activePayload?.[0]) {
      const model = data.activePayload[0].payload as DockingModel;
      setSelectedModel(prev => prev?.desc === model.desc ? null : model);
    }
  };

  return (
    <div className="space-y-4 animate-fade-in">
      <Card className="panel-card">
        <CardHeader className="panel-header">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-primary/20 text-primary">
              <BarChart3 className="w-4 h-4" />
            </div>
            <CardTitle className="text-sm font-bold uppercase tracking-wider">
              Score Distribution
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent className="p-4">
          <div className="h-[280px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sortedData} onClick={handleBarClick} style={{ cursor: 'pointer' }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                <XAxis
                  dataKey="shortName"
                  tick={{ fontSize: 11, fontFamily: 'JetBrains Mono', fill: 'hsl(var(--muted-foreground))' }}
                  axisLine={{ stroke: 'hsl(var(--border))' }}
                  tickLine={{ stroke: 'hsl(var(--border))' }}
                />
                <YAxis
                  tick={{ fontSize: 11, fontFamily: 'JetBrains Mono', fill: 'hsl(var(--muted-foreground))' }}
                  axisLine={{ stroke: 'hsl(var(--border))' }}
                  tickLine={{ stroke: 'hsl(var(--border))' }}
                  label={{
                    value: 'Score (REU)',
                    angle: -90,
                    position: 'insideLeft',
                    style: { fontSize: 11, fill: 'hsl(var(--muted-foreground))' },
                    offset: 0,
                  }}
                />
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine
                  y={avgScore}
                  stroke="hsl(var(--warning))"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                />
                <Bar dataKey="score" radius={[4, 4, 0, 0]} maxBarSize={60}>
                  {sortedData.map((entry, index) => (
                    <Cell
                      key={index}
                      fill={entry.isBest
                        ? 'hsl(142, 71%, 40%)'
                        : 'hsl(0, 100%, 37%)'
                      }
                      opacity={selectedModel?.desc === entry.desc ? 1 : 0.75}
                      stroke={selectedModel?.desc === entry.desc ? 'hsl(var(--foreground))' : 'none'}
                      strokeWidth={selectedModel?.desc === entry.desc ? 2 : 0}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Legend */}
          <div className="flex gap-4 justify-center mt-3 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-sm" style={{ background: 'hsl(142, 71%, 40%)' }} />
              <span>Best Model</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-sm" style={{ background: 'hsl(0, 100%, 37%)' }} />
              <span>Other Models</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-6 h-0.5" style={{ background: 'hsl(var(--warning))' }} />
              <span>Average</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Selected model detail card */}
      {selectedModel && (
        <Card className="panel-card border-primary/30 animate-scale-in">
          <CardHeader className="panel-header">
            <div className="flex items-center gap-2">
              <TrendingDown className="w-4 h-4" />
              <span>Model Details: {selectedModel.desc}</span>
            </div>
          </CardHeader>
          <CardContent className="p-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: 'Total Score', value: selectedModel.score?.toFixed(2) },
                { label: 'RMS', value: selectedModel.rms?.toFixed(2) ?? '-' },
                { label: 'I_sc', value: selectedModel.I_sc?.toFixed(2) ?? '-' },
                { label: 'Fnat', value: selectedModel.Fnat?.toFixed(3) ?? '-' },
                { label: 'CAPRI Rank', value: selectedModel.CAPRI_rank?.toFixed(0) ?? '-' },
                { label: 'Irms', value: selectedModel.Irms?.toFixed(2) ?? '-' },
                { label: 'fa_atr', value: selectedModel.fa_atr?.toFixed(2) ?? '-' },
                { label: 'fa_rep', value: selectedModel.fa_rep?.toFixed(2) ?? '-' },
              ].map((item) => (
                <div key={item.label} className="p-2 bg-muted/50 rounded-lg text-center">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">{item.label}</p>
                  <p className="font-mono font-bold text-sm mt-1">{item.value}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
