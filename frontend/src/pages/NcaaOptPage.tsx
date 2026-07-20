import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  Atom, Loader2, AlertCircle, Upload, Play, XCircle,
  Download, Settings2, Zap, Target, TrendingUp, Search, Library, ArrowLeft,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Cell, ReferenceLine, ResponsiveContainer,
  ScatterChart, Scatter, ZAxis,
} from 'recharts';
import { Header } from '@/components/Header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Switch } from '@/components/ui/switch';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { useToast } from '@/hooks/use-toast';
import * as api from '@/services/api';
import type {
  NcaaOptStatusResult, NcaaOptResult, NcaaOptResults,
  NcaaBuiltinEntry,
} from '@/services/api';

const CHAIN_COLORS: Record<string, { bg: string; text: string }> = {
  A: { bg: 'bg-teal-500/20', text: 'text-teal-400' },
  B: { bg: 'bg-orange-500/20', text: 'text-orange-400' },
  C: { bg: 'bg-violet-500/20', text: 'text-violet-400' },
  D: { bg: 'bg-emerald-500/20', text: 'text-emerald-400' },
  E: { bg: 'bg-pink-500/20', text: 'text-pink-400' },
};
const DEFAULT_CC = { bg: 'bg-muted', text: 'text-muted-foreground' };
function chainColor(c: string) { return CHAIN_COLORS[c] || DEFAULT_CC; }

type PageStatus = 'select-project' | 'ready' | 'error';
type OptStatus = 'idle' | 'submitting' | 'polling' | 'done' | 'error';

interface ProjectInfo { name: string; hasDockingResults: boolean; }

export default function NcaaOptPage() {
  const { toast } = useToast();

  // Project selection
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [selectedProject, setSelectedProject] = useState('');
  const [pageStatus, setPageStatus] = useState<PageStatus>('select-project');

  // ncAA params
  const [ncaaNames, setNcaaNames] = useState<string[]>([]);
  const [ncaaInput, setNcaaInput] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Built-in library
  const [builtinLibrary, setBuiltinLibrary] = useState<NcaaBuiltinEntry[]>([]);
  const [librarySearch, setLibrarySearch] = useState('');
  const [libraryOpen, setLibraryOpen] = useState(false);

  // Optimization settings
  const [mode, setMode] = useState<string>('single');
  const [positions, setPositions] = useState('auto');
  const [nCalls, setNCalls] = useState(20);
  const [trials, setTrials] = useState(1);
  const [useAlaScanSeed, setUseAlaScanSeed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Job tracking
  const [optStatus, setOptStatus] = useState<OptStatus>('idle');
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Results
  const [results, setResults] = useState<NcaaOptResults | null>(null);
  const [sortKey, setSortKey] = useState<string>('objective_score');
  const [sortAsc, setSortAsc] = useState(true);

  // Load project list + built-in library
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${(api as any).BASE || ''}/projects`);
        if (!res.ok) return;
        const data = await res.json();
        setProjects(
          (data.projects || []).map((p: any) => ({
            name: p.name,
            hasDockingResults: p.has_docking_results,
          })),
        );
      } catch { /* ignore */ }
    })();
    (async () => {
      try {
        const lib = await api.fetchNcaaBuiltinLibrary();
        setBuiltinLibrary(lib.entries);
      } catch { /* ignore — library just won't show */ }
    })();
  }, []);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const handleSelectProject = (name: string) => {
    setSelectedProject(name);
    setPageStatus('ready');
    setOptStatus('idle');
    setResults(null);
    setNcaaNames([]);
  };

  // ── Params Upload ──────────────────────────────────────────
  const handleParamsUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length || !selectedProject) return;
    try {
      const res = await api.uploadNcaaParams(selectedProject, Array.from(files));
      setNcaaNames(prev => [...new Set([...prev, ...res.ncaa_names])]);
      toast({ title: `Uploaded ${res.count} params file(s)`, description: res.ncaa_names.join(', ') });
    } catch (err: any) {
      toast({ title: 'Upload failed', description: err.message, variant: 'destructive' });
    }
    e.target.value = '';
  };

  const handleAddNcaa = () => {
    const name = ncaaInput.trim().toUpperCase();
    if (!name || ncaaNames.includes(name)) return;
    const isBuiltin = builtinLibrary.some(e => e.code === name);
    setNcaaNames(prev => [...prev, name]);
    setNcaaInput('');
    if (!isBuiltin) {
      toast({
        title: `"${name}" is not a built-in ncAA`,
        description: 'Make sure you upload the matching .params file, or it will fail at runtime.',
        variant: 'destructive',
      });
    }
  };

  // Autocomplete suggestions for manual input
  const ncaaInputUpper = ncaaInput.trim().toUpperCase();
  const autocompleteSuggestions = ncaaInputUpper.length >= 1
    ? builtinLibrary
        .filter(e =>
          !ncaaNames.includes(e.code) &&
          (e.code.toUpperCase().includes(ncaaInputUpper) || e.label.toUpperCase().includes(ncaaInputUpper))
        )
        .slice(0, 6)
    : [];

  const handleRemoveNcaa = (name: string) => {
    setNcaaNames(prev => prev.filter(n => n !== name));
  };

  // ── Submit Optimization ────────────────────────────────────
  const handleSubmit = async () => {
    if (!selectedProject || ncaaNames.length === 0) {
      toast({ title: 'Missing inputs', description: 'Select a project and add ncAA targets.', variant: 'destructive' });
      return;
    }

    setOptStatus('submitting');
    try {
      await api.submitNcaaOptimize(
        selectedProject, ncaaNames, positions, mode,
        nCalls, trials, useAlaScanSeed,
      );
      setOptStatus('polling');
      setProgress({ done: 0, total: nCalls });
      startPolling();
    } catch (err: any) {
      setOptStatus('error');
      toast({ title: 'Submit failed', description: err.message, variant: 'destructive' });
    }
  };

  // ── Polling ────────────────────────────────────────────────
  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.checkNcaaOptStatus(selectedProject);
        setProgress({ done: s.evaluations_done, total: s.evaluations_total });

        if (s.status === 'COMPLETED') {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setOptStatus('done');
          if (s.results) setResults(s.results);
        } else if (s.status === 'FAILED' || s.status === 'CANCELLED') {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setOptStatus('error');
          toast({ title: `Job ${s.status}`, description: s.error, variant: 'destructive' });
        }
      } catch { /* retry next interval */ }
    }, 3000);
  }, [selectedProject, toast]);

  const handleCancel = async () => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
    try {
      await api.cancelNcaaOptimize(selectedProject);
      setOptStatus('idle');
      toast({ title: 'Job cancelled' });
    } catch { /* ignore */ }
  };

  // ── CSV Export ─────────────────────────────────────────────
  const exportCsv = () => {
    if (!results?.history?.length) return;
    const keys = Object.keys(results.history[0]);
    const rows = [keys.join(',')];
    for (const r of results.history) {
      rows.push(keys.map(k => (r as any)[k] ?? '').join(','));
    }
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ncaa_opt_${selectedProject}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── Sorted history ─────────────────────────────────────────
  const sortedHistory = results?.history
    ? [...results.history]
        .filter(r => r.status === 'ok')
        .sort((a, b) => {
          const va = (a as any)[sortKey] ?? 999;
          const vb = (b as any)[sortKey] ?? 999;
          return sortAsc ? va - vb : vb - va;
        })
    : [];

  const handleSort = (key: string) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  };

  // ── Bar chart data ─────────────────────────────────────────
  const barData = sortedHistory.map(r => ({
    label: `${r.ncaa}@${r.chain || ''}${r.resid || r.position}`,
    ddg_bind: typeof r.ddg_bind === 'number' ? +r.ddg_bind.toFixed(2) : 0,
    ddg_fold: typeof r.ddg_fold === 'number' ? +r.ddg_fold.toFixed(2) : 0,
    score: typeof r.objective_score === 'number' ? +r.objective_score.toFixed(2) : 0,
  })).sort((a, b) => a.score - b.score).slice(0, 30);

  // ── Pareto scatter data ────────────────────────────────────
  const paretoData = results?.pareto?.map(p => ({
    x: p.ddg_bind,
    y: p.abs_ddg_fold,
    label: `${p.ncaa}@${p.position}`,
  })) || [];

  // ══════════════════════════════════════════════════════════════
  //  Render
  // ══════════════════════════════════════════════════════════════

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="max-w-6xl mx-auto p-6 space-y-6">
        <div className="flex items-center gap-3">
          <Link to="/">
            <Button variant="ghost" size="sm" className="gap-1">
              <ArrowLeft className="h-4 w-4" /> Dashboard
            </Button>
          </Link>
          <Atom className="h-7 w-7 text-purple-400" />
          <h1 className="text-2xl font-bold">ncAA Bayesian Optimization</h1>
        </div>

        {/* Project Selector */}
        <div className="panel-card">
          <div className="panel-header"><Target className="h-5 w-5" /> Select Project</div>
          <div className="p-4">
            <Select value={selectedProject} onValueChange={handleSelectProject}>
              <SelectTrigger><SelectValue placeholder="Choose a project..." /></SelectTrigger>
              <SelectContent>
                {projects.map(p => (
                  <SelectItem key={p.name} value={p.name}>
                    {p.name} {p.hasDockingResults && <Badge variant="secondary" className="ml-2 text-xs">docked</Badge>}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {pageStatus === 'ready' && (
          <>
            {/* ncAA Library Panel */}
            <div className="panel-card">
              <div className="panel-header"><Atom className="h-5 w-5" /> ncAA Library</div>
              <div className="p-4 space-y-4">

                {/* Selected ncAAs */}
                {ncaaNames.length > 0 && (
                  <div>
                    <Label className="text-xs text-muted-foreground mb-1 block">
                      Selected ({ncaaNames.length})
                    </Label>
                    <div className="flex flex-wrap gap-2">
                      {ncaaNames.map(n => (
                        <Badge key={n} variant="secondary" className="gap-1 text-sm">
                          {n}
                          <button onClick={() => handleRemoveNcaa(n)} className="ml-1 hover:text-destructive">
                            <XCircle className="h-3 w-3" />
                          </button>
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Built-in library */}
                {builtinLibrary.length > 0 && (
                  <Collapsible open={libraryOpen} onOpenChange={setLibraryOpen}>
                    <CollapsibleTrigger className="flex items-center gap-2 text-sm font-medium cursor-pointer hover:text-foreground text-muted-foreground w-full">
                      <Library className="h-4 w-4" />
                      Built-in PyRosetta Library ({builtinLibrary.length} ncAAs)
                      <span className="text-xs ml-auto">{libraryOpen ? '▲' : '▼'}</span>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="mt-2 space-y-2">
                        <div className="relative">
                          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                          <Input
                            value={librarySearch}
                            onChange={e => setLibrarySearch(e.target.value)}
                            placeholder="Search ncAAs..."
                            className="pl-8 h-9"
                          />
                        </div>
                        <div className="max-h-48 overflow-y-auto border rounded-md p-2 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1">
                          {builtinLibrary
                            .filter(e => {
                              const q = librarySearch.toLowerCase();
                              return !q || e.code.toLowerCase().includes(q) || e.label.toLowerCase().includes(q);
                            })
                            .map(e => {
                              const selected = ncaaNames.includes(e.code);
                              return (
                                <button
                                  key={e.code}
                                  onClick={() => {
                                    if (selected) handleRemoveNcaa(e.code);
                                    else setNcaaNames(prev => [...prev, e.code]);
                                  }}
                                  className={`text-left text-xs px-2 py-1.5 rounded border transition-colors ${
                                    selected
                                      ? 'bg-primary/20 border-primary/50 text-primary font-semibold'
                                      : 'border-border/50 hover:bg-muted/50 text-muted-foreground'
                                  }`}
                                  title={e.label}
                                >
                                  <span className="font-mono font-bold">{e.code}</span>
                                  <span className="block truncate text-[10px] opacity-70">{e.label}</span>
                                </button>
                              );
                            })}
                        </div>
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                )}

                {/* Manual entry + upload */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="relative">
                    <Label className="text-xs">Add by 3-letter code</Label>
                    <div className="flex gap-1 mt-1">
                      <Input
                        value={ncaaInput}
                        onChange={e => setNcaaInput(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') handleAddNcaa();
                          if (e.key === 'Tab' && autocompleteSuggestions.length > 0) {
                            e.preventDefault();
                            setNcaaInput(autocompleteSuggestions[0].code);
                          }
                        }}
                        placeholder="e.g. NLU"
                        className="w-32 h-9"
                      />
                      <Button variant="outline" size="sm" onClick={handleAddNcaa}>Add</Button>
                    </div>
                    {autocompleteSuggestions.length > 0 && ncaaInput.trim() && (
                      <div className="absolute z-10 mt-1 w-56 bg-popover border rounded-md shadow-lg overflow-hidden">
                        {autocompleteSuggestions.map(e => (
                          <button
                            key={e.code}
                            onClick={() => {
                              if (!ncaaNames.includes(e.code)) setNcaaNames(prev => [...prev, e.code]);
                              setNcaaInput('');
                            }}
                            className="w-full text-left px-3 py-1.5 text-sm hover:bg-muted/50 flex items-center gap-2"
                          >
                            <span className="font-mono font-bold text-primary">{e.code}</span>
                            <span className="text-xs text-muted-foreground truncate">{e.label}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".params"
                      multiple
                      onChange={handleParamsUpload}
                      className="hidden"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <Upload className="h-4 w-4 mr-1" /> Upload custom .params
                    </Button>
                  </div>
                </div>
              </div>
            </div>

            {/* Optimization Settings */}
            <div className="panel-card">
              <Collapsible open={settingsOpen} onOpenChange={setSettingsOpen}>
                <CollapsibleTrigger className="panel-header w-full cursor-pointer">
                  <Settings2 className="h-5 w-5" /> Optimization Settings
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="p-4 grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div>
                      <Label>Mode</Label>
                      <Select value={mode} onValueChange={setMode}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="single">Single Objective</SelectItem>
                          <SelectItem value="pareto">Pareto (Multi-Objective)</SelectItem>
                          <SelectItem value="combinatorial">Combinatorial (Pairs)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label>Positions</Label>
                      <Input
                        value={positions}
                        onChange={e => setPositions(e.target.value)}
                        placeholder="auto or 10,42,55"
                      />
                    </div>
                    <div>
                      <Label>Iterations</Label>
                      <Select value={nCalls.toString()} onValueChange={v => setNCalls(+v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {[5, 10, 20, 30, 50].map(n => (
                            <SelectItem key={n} value={n.toString()}>{n}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label>Trials / eval</Label>
                      <Select value={trials.toString()} onValueChange={v => setTrials(+v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {[1, 3, 5].map(n => (
                            <SelectItem key={n} value={n.toString()}>{n}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex items-end gap-2">
                      <div className="space-y-1">
                        <Label>Warm-start from ala scan</Label>
                        <Switch checked={useAlaScanSeed} onCheckedChange={setUseAlaScanSeed} />
                      </div>
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>

            {/* Run Button / Progress */}
            <div className="panel-card">
              <div className="p-4 space-y-4">
                {optStatus === 'idle' && (
                  <Button
                    onClick={handleSubmit}
                    disabled={ncaaNames.length === 0}
                    className="w-full"
                    size="lg"
                  >
                    <Zap className="h-5 w-5 mr-2" />
                    Run {mode === 'pareto' ? 'Pareto' : mode === 'combinatorial' ? 'Combinatorial' : 'Bayesian'} Optimization
                  </Button>
                )}

                {optStatus === 'submitting' && (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin" /> Submitting SLURM job...
                  </div>
                )}

                {optStatus === 'polling' && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">
                        Evaluations: {progress.done} / {progress.total}
                      </span>
                      <Button variant="outline" size="sm" onClick={handleCancel}>
                        <XCircle className="h-4 w-4 mr-1" /> Cancel
                      </Button>
                    </div>
                    <Progress value={progress.total ? (progress.done / progress.total) * 100 : 0} />
                  </div>
                )}

                {optStatus === 'error' && (
                  <div className="flex items-center gap-2 text-destructive">
                    <AlertCircle className="h-5 w-5" /> Job failed or cancelled.
                    <Button variant="outline" size="sm" onClick={() => setOptStatus('idle')}>Retry</Button>
                  </div>
                )}

                {optStatus === 'done' && results && (
                  <div className="flex items-center gap-2 text-green-400">
                    <TrendingUp className="h-5 w-5" /> Optimization complete!
                    <Button variant="outline" size="sm" onClick={exportCsv} className="ml-auto">
                      <Download className="h-4 w-4 mr-1" /> Export CSV
                    </Button>
                  </div>
                )}
              </div>
            </div>

            {/* ── Results ─────────────────────────────────────── */}
            {optStatus === 'done' && results && (
              <>
                {/* Best Result Card */}
                {results.best && (
                  <div className="panel-card border-purple-500/30">
                    <div className="panel-header"><Zap className="h-5 w-5 text-yellow-400" /> Best Result</div>
                    <div className="p-4 grid grid-cols-2 md:grid-cols-5 gap-4 text-center">
                      <div>
                        <div className="text-xs text-muted-foreground">Mutation</div>
                        <div className="text-lg font-bold font-mono">
                          <span className="text-muted-foreground text-sm">
                            {results.best.wt_aa3 || results.best.wt_aa}
                          </span>
                          {' \u2192 '}
                          {results.best.ncaa}@
                          <span className={chainColor(results.best.chain || '').text}>
                            {results.best.chain}
                          </span>
                          {results.best.resid || results.best.position}
                        </div>
                        {typeof results.best.sasa === 'number' && (
                          <div className="text-xs text-muted-foreground mt-1">
                            SASA: {results.best.sasa.toFixed(1)} &#8491;&sup2;
                          </div>
                        )}
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">DDG Bind</div>
                        <div className={`text-lg font-bold ${(results.best.ddg_bind ?? 0) < 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {results.best.ddg_bind?.toFixed(2) ?? '--'}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">DDG Fold</div>
                        <div className="text-lg font-bold">
                          {results.best.ddg_fold?.toFixed(2) ?? '--'}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">Score</div>
                        <div className="text-lg font-bold text-purple-400">
                          {results.best_score?.toFixed(2) ?? results.best.objective_score?.toFixed(2) ?? '--'}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* DDG Bar Chart */}
                {barData.length > 0 && (
                  <div className="panel-card">
                    <div className="panel-header"><TrendingUp className="h-5 w-5" /> Objective Scores</div>
                    <div className="p-4">
                      <ResponsiveContainer width="100%" height={Math.max(250, barData.length * 28)}>
                        <BarChart data={barData} layout="vertical" margin={{ left: 80, right: 20 }}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                          <XAxis type="number" />
                          <YAxis type="category" dataKey="label" width={75} tick={{ fontSize: 11 }} />
                          <Tooltip
                            contentStyle={{ backgroundColor: '#1e1e2e', border: '1px solid #444' }}
                            formatter={(v: number) => v.toFixed(3)}
                          />
                          <ReferenceLine x={0} stroke="#666" />
                          <Bar dataKey="score" name="Objective">
                            {barData.map((d, i) => (
                              <Cell key={i} fill={d.score < 0 ? '#22c55e' : d.score < 2 ? '#f59e0b' : '#ef4444'} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* Pareto Scatter (if multi-objective) */}
                {paretoData.length > 0 && (
                  <div className="panel-card">
                    <div className="panel-header"><Target className="h-5 w-5" /> Pareto Front</div>
                    <div className="p-4">
                      <ResponsiveContainer width="100%" height={350}>
                        <ScatterChart margin={{ left: 20, right: 20, top: 10, bottom: 10 }}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                          <XAxis
                            type="number" dataKey="x" name="Binding Improvement (DDG_bind)"
                            label={{ value: 'DDG Bind', position: 'bottom', fill: '#999' }}
                          />
                          <YAxis
                            type="number" dataKey="y" name="|DDG Fold|"
                            label={{ value: '|DDG Fold|', angle: -90, position: 'insideLeft', fill: '#999' }}
                          />
                          <ZAxis dataKey="label" name="Mutation" />
                          <Tooltip
                            contentStyle={{ backgroundColor: '#1e1e2e', border: '1px solid #444' }}
                          />
                          <Scatter data={paretoData} fill="#a855f7" />
                        </ScatterChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* History Table */}
                {sortedHistory.length > 0 && (
                  <div className="panel-card">
                    <div className="panel-header"><Play className="h-5 w-5" /> Evaluation History ({sortedHistory.length} results)</div>
                    <div className="p-4 overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-muted-foreground border-b border-border">
                            {[
                              { key: 'iteration', label: '#' },
                              { key: 'ncaa', label: 'ncAA' },
                              { key: 'chain', label: 'Chain' },
                              { key: 'resid', label: 'Resid' },
                              { key: 'wt_aa3', label: 'WT Residue' },
                              { key: 'sasa', label: 'SASA' },
                              { key: 'ddg_bind', label: 'DDG Bind' },
                              { key: 'ddg_fold', label: 'DDG Fold' },
                              { key: 'objective_score', label: 'Score' },
                            ].map(col => (
                              <th
                                key={col.key}
                                className="px-2 py-1 cursor-pointer hover:text-foreground"
                                onClick={() => handleSort(col.key)}
                              >
                                {col.label}
                                {sortKey === col.key && (sortAsc ? ' \u25B2' : ' \u25BC')}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {sortedHistory.map((r, i) => (
                            <tr key={i} className="border-b border-border/50 hover:bg-muted/20">
                              <td className="px-2 py-1 text-muted-foreground">{r.iteration ?? i + 1}</td>
                              <td className="px-2 py-1 font-mono font-bold">{r.ncaa}</td>
                              <td className="px-2 py-1">
                                {r.chain && (
                                  <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${chainColor(r.chain).bg} ${chainColor(r.chain).text}`}>
                                    {r.chain}
                                  </span>
                                )}
                              </td>
                              <td className="px-2 py-1 font-mono">{r.resid ?? r.position}</td>
                              <td className="px-2 py-1 font-mono">{r.wt_aa3 || r.wt_aa}</td>
                              <td className="px-2 py-1 font-mono text-muted-foreground">
                                {typeof r.sasa === 'number' ? r.sasa.toFixed(1) : '--'}
                              </td>
                              <td className={`px-2 py-1 font-mono ${(r.ddg_bind ?? 0) < 0 ? 'text-green-400' : 'text-red-400'}`}>
                                {typeof r.ddg_bind === 'number' ? r.ddg_bind.toFixed(2) : '--'}
                              </td>
                              <td className="px-2 py-1 font-mono">
                                {typeof r.ddg_fold === 'number' ? r.ddg_fold.toFixed(2) : '--'}
                              </td>
                              <td className="px-2 py-1 font-mono font-bold">
                                {typeof r.objective_score === 'number' ? r.objective_score.toFixed(2) : '--'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
