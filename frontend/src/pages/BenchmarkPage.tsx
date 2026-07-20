import { useState, useEffect, useRef } from 'react';
import {
  FlaskConical, Loader2, CheckCircle2, XCircle, Clock,
  BarChart2, Download, Plus, Trash2, Play,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Cell, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { Header } from '@/components/Header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/hooks/use-toast';
import * as api from '@/services/api';
import type { BenchmarkEntry, BenchmarkResult, BenchmarkSummary } from '@/services/api';

// ── DockQ classification helpers ─────────────────────────────────────────────

const DOCKQ_COLORS: Record<string, string> = {
  High:       '#22c55e',
  Medium:     '#3b82f6',
  Acceptable: '#f59e0b',
  Incorrect:  '#ef4444',
};

function dockqColor(score?: number): string {
  if (score === undefined) return '#6b7280';
  if (score >= 0.80) return DOCKQ_COLORS.High;
  if (score >= 0.49) return DOCKQ_COLORS.Medium;
  if (score >= 0.23) return DOCKQ_COLORS.Acceptable;
  return DOCKQ_COLORS.Incorrect;
}

function ClassificationBadge({ cls }: { cls?: string }) {
  const color = cls ? DOCKQ_COLORS[cls] : '#6b7280';
  return (
    <span
      className="px-2 py-0.5 rounded text-xs font-semibold"
      style={{ background: color + '22', color }}
    >
      {cls ?? '—'}
    </span>
  );
}

// ── Entry editor row ──────────────────────────────────────────────────────────

function EntryRow({
  entry,
  onUpdate,
  onRemove,
}: {
  entry: BenchmarkEntry;
  onUpdate: (e: BenchmarkEntry) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex gap-2 items-center text-sm">
      <Input
        className="w-24 font-mono uppercase"
        value={entry.pdb_code}
        placeholder="1AY7"
        onChange={e => onUpdate({ ...entry, pdb_code: e.target.value.toUpperCase().trim() })}
      />
      <Input
        className="w-28 font-mono"
        value={entry.receptor_chains.join(',')}
        placeholder="A"
        title="Receptor chain(s), comma-separated"
        onChange={e =>
          onUpdate({ ...entry, receptor_chains: e.target.value.split(',').map(c => c.trim().toUpperCase()).filter(Boolean) })
        }
      />
      <Input
        className="w-28 font-mono"
        value={entry.binder_chains.join(',')}
        placeholder="B"
        title="Binder chain(s), comma-separated"
        onChange={e =>
          onUpdate({ ...entry, binder_chains: e.target.value.split(',').map(c => c.trim().toUpperCase()).filter(Boolean) })
        }
      />
      <Input
        className="flex-1"
        value={entry.description}
        placeholder="Description"
        onChange={e => onUpdate({ ...entry, description: e.target.value })}
      />
      <button onClick={onRemove} className="text-muted-foreground hover:text-destructive">
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}

// ── Result row ────────────────────────────────────────────────────────────────

function ResultRow({ r }: { r: BenchmarkResult }) {
  const isRunning = r.status === 'running';
  const isSuccess = r.status === 'success';
  const isFailed  = r.status === 'failed';

  return (
    <tr className="border-b border-border/40 hover:bg-muted/30 transition-colors">
      <td className="py-2 px-3 font-mono font-semibold">{r.pdb_code}</td>
      <td className="py-2 px-3 text-muted-foreground text-xs">{r.description}</td>
      <td className="py-2 px-3">
        <span className="text-xs px-1.5 py-0.5 rounded bg-muted">{r.category}</span>
      </td>
      <td className="py-2 px-3">
        {isRunning && <Loader2 className="h-4 w-4 animate-spin text-blue-400" />}
        {isSuccess && <CheckCircle2 className="h-4 w-4 text-green-500" />}
        {isFailed  && <XCircle     className="h-4 w-4 text-red-500" />}
      </td>
      <td className="py-2 px-3 font-mono font-bold" style={{ color: dockqColor(r.DockQ) }}>
        {r.DockQ !== undefined ? r.DockQ.toFixed(3) : '—'}
      </td>
      <td className="py-2 px-3"><ClassificationBadge cls={r.classification} /></td>
      <td className="py-2 px-3 font-mono text-xs text-muted-foreground">
        {r.Fnat !== undefined ? r.Fnat.toFixed(3) : '—'}
      </td>
      <td className="py-2 px-3 font-mono text-xs text-muted-foreground">
        {r.iRMS !== undefined ? r.iRMS.toFixed(2) : '—'}
      </td>
      <td className="py-2 px-3 font-mono text-xs text-muted-foreground">
        {r.LRMS !== undefined ? r.LRMS.toFixed(2) : '—'}
      </td>
      <td className="py-2 px-3 font-mono text-xs text-muted-foreground">
        {r.rosetta_score !== undefined ? r.rosetta_score.toFixed(1) : '—'}
      </td>
    </tr>
  );
}

// ── Summary cards ─────────────────────────────────────────────────────────────

function SummaryCards({ summary, done, total }: { summary?: BenchmarkSummary; done: number; total: number }) {
  if (!summary) return null;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {[
        { label: 'Mean DockQ', value: summary.mean_DockQ?.toFixed(3) ?? '—', color: dockqColor(summary.mean_DockQ ?? 0) },
        { label: 'Median DockQ', value: summary.median_DockQ?.toFixed(3) ?? '—', color: dockqColor(summary.median_DockQ ?? 0) },
        { label: 'Acceptable+', value: `${((summary.acceptable_or_better ?? 0) * 100).toFixed(0)}%`, color: '#f59e0b' },
        { label: 'Success Rate', value: `${((summary.success_rate ?? 0) * 100).toFixed(0)}%`, color: '#22c55e' },
      ].map(c => (
        <div key={c.label} className="bg-card border border-border rounded-lg p-4 text-center">
          <div className="text-2xl font-bold" style={{ color: c.color }}>{c.value}</div>
          <div className="text-xs text-muted-foreground mt-1">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

// ── DockQ bar chart ───────────────────────────────────────────────────────────

function DockQChart({ results }: { results: BenchmarkResult[] }) {
  const data = results
    .filter(r => r.DockQ !== undefined)
    .map(r => ({ pdb: r.pdb_code, DockQ: r.DockQ! }))
    .sort((a, b) => b.DockQ - a.DockQ);

  if (data.length === 0) return null;

  return (
    <div className="bg-card border border-border rounded-lg p-4 mb-6">
      <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
        <BarChart2 className="h-4 w-4 text-blue-400" /> DockQ Scores
      </h3>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ left: -10, right: 10, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
          <XAxis dataKey="pdb" tick={{ fontSize: 11, fill: '#9ca3af' }} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: '#9ca3af' }} />
          <Tooltip
            contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6 }}
            formatter={(v: number) => [v.toFixed(3), 'DockQ']}
          />
          <ReferenceLine y={0.80} stroke={DOCKQ_COLORS.High}       strokeDasharray="4 3" label={{ value: 'High',       position: 'right', fontSize: 10, fill: DOCKQ_COLORS.High }} />
          <ReferenceLine y={0.49} stroke={DOCKQ_COLORS.Medium}     strokeDasharray="4 3" label={{ value: 'Medium',     position: 'right', fontSize: 10, fill: DOCKQ_COLORS.Medium }} />
          <ReferenceLine y={0.23} stroke={DOCKQ_COLORS.Acceptable} strokeDasharray="4 3" label={{ value: 'Accept.',    position: 'right', fontSize: 10, fill: DOCKQ_COLORS.Acceptable }} />
          <Bar dataKey="DockQ" radius={[3, 3, 0, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={dockqColor(d.DockQ)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BenchmarkPage() {
  const { toast } = useToast();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [presets, setPresets] = useState<BenchmarkEntry[]>([]);
  const [entries, setEntries]  = useState<BenchmarkEntry[]>([]);
  const [nstruct, setNstruct]  = useState(10);
  const [timeLimit, setTimeLimit] = useState('04:00:00');
  const [cpus, setCpus] = useState(4);

  const [phase, setPhase]     = useState<'setup' | 'running' | 'done'>('setup');
  const [jobId, setJobId]     = useState<string | null>(null);
  const [done, setDone]       = useState(0);
  const [total, setTotal]     = useState(0);
  const [results, setResults] = useState<BenchmarkResult[]>([]);
  const [summary, setSummary] = useState<BenchmarkSummary | undefined>();

  // Load preset entries on mount
  useEffect(() => {
    api.fetchBenchmarkPresets().then(r => {
      setPresets(r.presets);
      setEntries(r.presets);
    }).catch(() => {
      toast({ title: 'Could not load presets', variant: 'destructive' });
    });
  }, []);

  // Poll while running
  useEffect(() => {
    if (phase !== 'running' || !jobId) return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.checkBenchmarkStatus(jobId, total);
        setDone(s.done);
        setResults(s.results);
        if (['COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT'].includes(s.status)) {
          setPhase('done');
          if (s.summary) setSummary(s.summary);
          clearInterval(pollRef.current!);
        }
      } catch { /* ignore transient errors */ }
    }, 8000);
    return () => clearInterval(pollRef.current!);
  }, [phase, jobId, total]);

  function addCustomEntry() {
    setEntries(prev => [...prev, {
      pdb_code: '',
      receptor_chains: ['A'],
      binder_chains: ['B'],
      category: 'Custom',
      description: '',
    }]);
  }

  function exportCsv() {
    if (results.length === 0) return;
    const header = 'pdb_code,description,category,DockQ,classification,Fnat,iRMS,LRMS,rosetta_score,status';
    const rows = results.map(r =>
      [r.pdb_code, r.description, r.category, r.DockQ ?? '', r.classification ?? '', r.Fnat ?? '', r.iRMS ?? '', r.LRMS ?? '', r.rosetta_score ?? '', r.status].join(',')
    );
    const blob = new Blob([[header, ...rows].join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'benchmark_results.csv';
    a.click();
  }

  async function handleSubmit() {
    const valid = entries.filter(e => e.pdb_code.length === 4);
    if (valid.length === 0) {
      toast({ title: 'Add at least one valid PDB code', variant: 'destructive' });
      return;
    }
    try {
      const r = await api.submitBenchmark(valid, nstruct, timeLimit, cpus);
      setJobId(r.job_id);
      setTotal(r.num_entries);
      setDone(0);
      setResults([]);
      setSummary(undefined);
      setPhase('running');
      toast({ title: `Benchmark submitted`, description: `SLURM job ${r.job_id} — ${r.num_entries} complexes` });
    } catch (e: any) {
      toast({ title: 'Submission failed', description: e.message, variant: 'destructive' });
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <Header />
      <main className="flex-1 container mx-auto px-4 py-8 max-w-6xl">

        {/* Title */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-blue-500/10 rounded-lg">
            <FlaskConical className="h-6 w-6 text-blue-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">DockQ Benchmark</h1>
            <p className="text-muted-foreground text-sm">
              Validate docking accuracy against known PDB co-crystal structures
            </p>
          </div>
        </div>

        {/* Setup panel */}
        {phase === 'setup' && (
          <div className="space-y-6">

            {/* Entry table */}
            <div className="bg-card border border-border rounded-lg p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="font-semibold text-sm">Benchmark Set</h2>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => setEntries(presets)}>
                    Reset to Presets
                  </Button>
                  <Button variant="outline" size="sm" onClick={addCustomEntry}>
                    <Plus className="h-3.5 w-3.5 mr-1" /> Add PDB
                  </Button>
                </div>
              </div>

              <div className="flex gap-2 text-xs text-muted-foreground mb-2 px-1">
                <span className="w-24">PDB Code</span>
                <span className="w-28">Receptor chains</span>
                <span className="w-28">Binder chains</span>
                <span className="flex-1">Description</span>
              </div>
              <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {entries.map((e, i) => (
                  <EntryRow
                    key={i}
                    entry={e}
                    onUpdate={updated => setEntries(prev => prev.map((x, j) => j === i ? updated : x))}
                    onRemove={() => setEntries(prev => prev.filter((_, j) => j !== i))}
                  />
                ))}
              </div>
            </div>

            {/* Settings */}
            <div className="bg-card border border-border rounded-lg p-5">
              <h2 className="font-semibold text-sm mb-4">Settings</h2>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">nstruct per complex</label>
                  <Input
                    type="number" min={1} max={100}
                    value={nstruct}
                    onChange={e => setNstruct(parseInt(e.target.value) || 10)}
                  />
                  <p className="text-xs text-muted-foreground mt-1">10 = fast, 50 = more accurate</p>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">SLURM time limit</label>
                  <Input value={timeLimit} onChange={e => setTimeLimit(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">CPUs</label>
                  <Input type="number" min={1} max={48} value={cpus} onChange={e => setCpus(parseInt(e.target.value) || 4)} />
                </div>
              </div>
            </div>

            {/* DockQ legend */}
            <div className="bg-card border border-border rounded-lg p-4">
              <p className="text-xs font-semibold text-muted-foreground mb-2">DockQ Classification Thresholds</p>
              <div className="flex gap-6 text-xs">
                {[
                  { label: 'High',       range: '≥ 0.80', color: DOCKQ_COLORS.High },
                  { label: 'Medium',     range: '0.49 – 0.79', color: DOCKQ_COLORS.Medium },
                  { label: 'Acceptable', range: '0.23 – 0.48', color: DOCKQ_COLORS.Acceptable },
                  { label: 'Incorrect',  range: '< 0.23', color: DOCKQ_COLORS.Incorrect },
                ].map(t => (
                  <div key={t.label} className="flex items-center gap-1.5">
                    <div className="w-3 h-3 rounded-sm" style={{ background: t.color }} />
                    <span className="font-semibold" style={{ color: t.color }}>{t.label}</span>
                    <span className="text-muted-foreground">{t.range}</span>
                  </div>
                ))}
              </div>
            </div>

            <Button onClick={handleSubmit} className="w-full" size="lg">
              <Play className="h-4 w-4 mr-2" />
              Submit Benchmark ({entries.filter(e => e.pdb_code.length === 4).length} complexes)
            </Button>
          </div>
        )}

        {/* Running panel */}
        {phase === 'running' && (
          <div className="space-y-6">
            {/* Progress */}
            <div className="bg-card border border-border rounded-lg p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin text-blue-400" />
                  <span className="font-semibold">Running — SLURM job {jobId}</span>
                </div>
                <span className="text-sm text-muted-foreground">{done} / {total} completed</span>
              </div>
              <div className="w-full bg-muted rounded-full h-2">
                <div
                  className="bg-blue-500 h-2 rounded-full transition-all duration-500"
                  style={{ width: total > 0 ? `${(done / total) * 100}%` : '0%' }}
                />
              </div>
              <p className="text-xs text-muted-foreground mt-2">Polling every 8 seconds</p>
            </div>

            {results.length > 0 && <DockQChart results={results} />}

            {/* Live results table */}
            {results.length > 0 && (
              <div className="bg-card border border-border rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/50 text-xs text-muted-foreground">
                      <th className="py-2 px-3 text-left">PDB</th>
                      <th className="py-2 px-3 text-left">Description</th>
                      <th className="py-2 px-3 text-left">Category</th>
                      <th className="py-2 px-3 text-left">Status</th>
                      <th className="py-2 px-3 text-left">DockQ</th>
                      <th className="py-2 px-3 text-left">Class.</th>
                      <th className="py-2 px-3 text-left">Fnat</th>
                      <th className="py-2 px-3 text-left">iRMS</th>
                      <th className="py-2 px-3 text-left">LRMS</th>
                      <th className="py-2 px-3 text-left">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map(r => <ResultRow key={r.pdb_code} r={r} />)}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Done panel */}
        {phase === 'done' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-green-500 font-semibold">
                <CheckCircle2 className="h-5 w-5" />
                Benchmark complete
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={exportCsv}>
                  <Download className="h-4 w-4 mr-1" /> Export CSV
                </Button>
                <Button variant="outline" size="sm" onClick={() => setPhase('setup')}>
                  Run Again
                </Button>
              </div>
            </div>

            <SummaryCards summary={summary} done={done} total={total} />
            <DockQChart results={results} />

            <div className="bg-card border border-border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50 text-xs text-muted-foreground">
                    <th className="py-2 px-3 text-left">PDB</th>
                    <th className="py-2 px-3 text-left">Description</th>
                    <th className="py-2 px-3 text-left">Category</th>
                    <th className="py-2 px-3 text-left">Status</th>
                    <th className="py-2 px-3 text-left">DockQ</th>
                    <th className="py-2 px-3 text-left">Classification</th>
                    <th className="py-2 px-3 text-left">Fnat</th>
                    <th className="py-2 px-3 text-left">iRMS (Å)</th>
                    <th className="py-2 px-3 text-left">LRMS (Å)</th>
                    <th className="py-2 px-3 text-left">Rosetta Score</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map(r => <ResultRow key={r.pdb_code} r={r} />)}
                </tbody>
              </table>
            </div>
          </div>
        )}

      </main>
    </div>
  );
}
