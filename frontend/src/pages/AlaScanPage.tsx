import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Target, Loader2, AlertCircle, Shield, TestTube,
  ArrowRight, Dna, Download, XCircle,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Cell, ReferenceLine, ResponsiveContainer, ErrorBar,
} from 'recharts';
import { Header } from '@/components/Header';
import { Button } from '@/components/ui/button';
import { useToast } from '@/hooks/use-toast';
import * as api from '@/services/api';
import type {
  ExperimentPlanData, InterfaceData,
  AlaScanStatusResult, AlaScanMutation, AlaScanResults,
} from '@/services/api';

const AA_MAP: Record<string, string> = {
  ALA: "A", ARG: "R", ASN: "N", ASP: "D", CYS: "C",
  GLN: "Q", GLU: "E", GLY: "G", HIS: "H", ILE: "I",
  LEU: "L", LYS: "K", MET: "M", PHE: "F", PRO: "P",
  SER: "S", THR: "T", TRP: "W", TYR: "Y", VAL: "V",
};

const CHAIN_COLORS: Record<string, { bg: string; text: string }> = {
  A: { bg: 'bg-teal-500/20', text: 'text-teal-400' },
  B: { bg: 'bg-orange-500/20', text: 'text-orange-400' },
  C: { bg: 'bg-violet-500/20', text: 'text-violet-400' },
  D: { bg: 'bg-emerald-500/20', text: 'text-emerald-400' },
  E: { bg: 'bg-pink-500/20', text: 'text-pink-400' },
  F: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  G: { bg: 'bg-amber-500/20', text: 'text-amber-400' },
  H: { bg: 'bg-red-500/20', text: 'text-red-400' },
  I: { bg: 'bg-green-500/20', text: 'text-green-400' },
  J: { bg: 'bg-purple-500/20', text: 'text-purple-400' },
};
const DEFAULT_CHAIN_COLOR = { bg: 'bg-muted', text: 'text-muted-foreground' };
function chainColor(chain: string) {
  return CHAIN_COLORS[chain] || DEFAULT_CHAIN_COLOR;
}

const ENERGY_TERM_LABELS: Record<string, string> = {
  fa_atr: "vdW attract",
  fa_rep: "vdW repulse",
  fa_elec: "electrostatics",
  fa_sol: "solvation",
  hbond_sc: "SC H-bond",
  hbond_bb_sc: "BB-SC H-bond",
  lk_ball_wtd: "Lazaridis-Karplus",
};

type PageStatus = 'select-project' | 'loading' | 'ready' | 'error';
type ScanStatus = 'idle' | 'submitting' | 'polling' | 'done' | 'error';

interface ProjectInfo {
  name: string;
  hasDockingResults: boolean;
  bestPdbPath?: string;
}

export default function AlaScanPage() {
  const { toast } = useToast();

  const [projectName, setProjectName] = useState('');
  const [pageStatus, setPageStatus] = useState<PageStatus>('select-project');
  const [pageError, setPageError] = useState<string | null>(null);

  // Available projects with docking results
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);

  // Analysis data for selected project
  const [interfaceData, setInterfaceData] = useState<InterfaceData | null>(null);
  const [expData, setExpData] = useState<ExperimentPlanData | null>(null);
  const [bestPdbPath, setBestPdbPath] = useState<string | null>(null);

  // Scan state
  const [scanStatus, setScanStatus] = useState<ScanStatus>('idle');
  const [scanError, setScanError] = useState<string | null>(null);
  const [scanProgress, setScanProgress] = useState({ done: 0, total: 0 });
  const [scanResults, setScanResults] = useState<AlaScanMutation[] | null>(null);
  const [scanMeta, setScanMeta] = useState<Partial<AlaScanResults>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Scan settings
  const [nstruct, setNstruct] = useState(3);
  const [maxMutations, setMaxMutations] = useState(8);
  const [nPoses, setNPoses] = useState(1);

  const isMultiPose = (scanMeta.mode === 'multi_pose') || (scanMeta.n_poses != null && scanMeta.n_poses > 1);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Load available projects on mount
  useEffect(() => {
    (async () => {
      setLoadingProjects(true);
      try {
        const res = await fetch(`${api.BASE}/projects`);
        if (!res.ok) throw new Error('Failed to load projects');
        const data = await res.json();
        const infos: ProjectInfo[] = [];
        for (const p of data.projects || []) {
          try {
            const dockRes = await fetch(`${api.BASE}/dock-results?project=${encodeURIComponent(p.name)}`);
            if (dockRes.ok) {
              const dockData = await dockRes.json();
              infos.push({
                name: p.name,
                hasDockingResults: true,
                bestPdbPath: dockData.best?.pdb_path,
              });
            }
          } catch { /* skip projects without results */ }
        }
        setProjects(infos);
      } catch (e: any) {
        toast({ title: 'Error', description: e.message, variant: 'destructive' });
      }
      setLoadingProjects(false);
    })();
  }, [toast]);

  const applyResults = useCallback((results: AlaScanResults) => {
    setScanResults(results.mutations);
    setScanMeta({
      wt_dG: results.wt_dG,
      wt_std: results.wt_std,
      wt_warning: results.wt_warning,
      wt_noise_floor: results.wt_noise_floor,
      mode: results.mode,
      n_poses: results.n_poses,
    });
  }, []);

  const selectProject = useCallback(async (project: ProjectInfo) => {
    setProjectName(project.name);
    setBestPdbPath(project.bestPdbPath || null);
    setPageStatus('loading');
    setPageError(null);
    setScanStatus('idle');
    setScanResults(null);
    setScanMeta({});
    setScanError(null);
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }

    try {
      const [iface, exp] = await Promise.all([
        api.analyzeInterface(project.name, project.bestPdbPath),
        api.experimentPlan(project.name, project.bestPdbPath),
      ]);
      setInterfaceData(iface);
      setExpData(exp);
      setPageStatus('ready');

      // Check if there's already a completed scan
      try {
        const scanCheck = await api.checkAlaScanStatus(project.name);
        if (scanCheck.status === 'COMPLETED' && scanCheck.results) {
          applyResults(scanCheck.results);
          setScanStatus('done');
        } else if (scanCheck.status === 'RUNNING' || scanCheck.status === 'PENDING') {
          setScanProgress({ done: scanCheck.tasks_done, total: scanCheck.tasks_total });
          setScanStatus('polling');
          startPolling();
        }
      } catch { /* no existing scan */ }
    } catch (e: any) {
      setPageError(e.message);
      setPageStatus('error');
    }
  }, []);

  const pollScanStatus = useCallback(async () => {
    try {
      const result: AlaScanStatusResult = await api.checkAlaScanStatus(projectName);
      setScanProgress({ done: result.tasks_done, total: result.tasks_total });

      if (result.status === 'COMPLETED' && result.results) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        applyResults(result.results);
        setScanStatus('done');
        toast({ title: 'Scan Complete', description: `${result.results.mutations.length} mutations analyzed` });
      } else if (result.status === 'FAILED') {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        setScanError(result.error || 'Scan job failed');
        setScanStatus('error');
      }
    } catch (e) {
      console.error('Poll error:', e);
    }
  }, [projectName, toast, applyResults]);

  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(pollScanStatus, 3000);
  }, [pollScanStatus]);

  const handleStartScan = async () => {
    setScanStatus('submitting');
    setScanError(null);
    setScanResults(null);
    setScanMeta({});
    try {
      const result = await api.submitAlaScan(projectName, bestPdbPath || undefined, nstruct, maxMutations, nPoses);
      const totalTasks = nPoses > 1
        ? (result.num_mutations + 1) * (result.n_poses ?? nPoses)
        : result.num_mutations + 1;
      setScanProgress({ done: 0, total: totalTasks });
      setScanStatus('polling');
      startPolling();
      const poseMsg = nPoses > 1 ? ` across ${result.n_poses ?? nPoses} poses` : '';
      toast({ title: 'Scan Submitted', description: `SLURM job ${result.job_id} — ${result.num_mutations} mutations${poseMsg}` });
    } catch (e: any) {
      setScanError(e.message);
      setScanStatus('error');
    }
  };

  const handleCancelScan = async () => {
    try {
      await api.cancelAlaScan(projectName);
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      setScanStatus('idle');
      toast({ title: 'Scan Cancelled' });
    } catch (e: any) {
      toast({ title: 'Cancel failed', description: e.message, variant: 'destructive' });
    }
  };

  const handleExportCsv = () => {
    if (!scanResults || !expData) return;
    const headers = [
      'Mutation', 'Chain', 'Side', 'Resname', 'Resid', 'Heuristic_Score', 'Delta_SASA',
      'WT_dG', 'Mut_dG', 'Mut_Std', 'DDG',
      ...(isMultiPose ? ['Cross_Pose_Std', 'N_Poses_OK'] : []),
      'CI_Lower', 'CI_Upper', 'SNR',
      'Classification', 'Dominant_Energy',
    ];
    const rows = [headers.join(',')];
    for (const m of scanResults) {
      const hotspot = expData.hotspots.find(h => h.chain === m.chain && h.resid === m.resid);
      const row = [
        m.mutation, m.chain, m.side ?? '', m.resname, m.resid,
        hotspot?.hotspot_score ?? '', hotspot?.delta_sasa ?? '',
        m.wt_dG, m.mut_dG ?? '', m.mut_std ?? '', m.ddG ?? '',
        ...(isMultiPose ? [m.cross_pose_std ?? '', m.n_poses_ok ?? ''] : []),
        m.ci_lower ?? '', m.ci_upper ?? '', m.snr ?? '',
        m.classification,
        m.energy_decomp?.dominant ?? '',
      ];
      rows.push(row.join(','));
    }
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${projectName}_ala_scan.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // For Header compatibility
  const handleNewProject = useCallback(() => {
    setProjectName('');
    setPageStatus('select-project');
    setInterfaceData(null);
    setExpData(null);
    setScanStatus('idle');
    setScanResults(null);
    setScanMeta({});
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const handleProjectSelect = useCallback(async (name: string) => {
    const project = projects.find(p => p.name === name);
    if (project) {
      selectProject(project);
    } else {
      selectProject({ name, hasDockingResults: true });
    }
  }, [projects, selectProject]);

  return (
    <div className="min-h-screen bg-background relative overflow-hidden">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary/5 rounded-full blur-3xl animate-pulse" />
        <div className="absolute top-1/2 -left-40 w-96 h-96 bg-primary/3 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '1s' }} />
      </div>

      <Header
        workingDir="./inputs"
        onWorkingDirChange={() => {}}
        projectName={projectName || 'Select a project'}
        onProjectNameChange={setProjectName}
        nstruct={nstruct}
        onNstructChange={setNstruct}
        onNewProject={handleNewProject}
        onProjectSelect={handleProjectSelect}
        showBackButton={true}
        backButtonLabel="Back to Dashboard"
      />

      <main className="relative max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page Title */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary text-sm font-semibold mb-3">
            <TestTube className="w-4 h-4" />
            Computational Alanine Scanning
          </div>
          <p className="text-sm text-muted-foreground max-w-xl mx-auto">
            Compute true Rosetta &Delta;&Delta;G values by mutating each hotspot residue to alanine.
            Identifies critical binding determinants with energy-level precision.
          </p>
        </div>

        {/* Project Selection */}
        {pageStatus === 'select-project' && (
          <div className="panel-card animate-fade-in max-w-2xl mx-auto">
            <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
              <div className="flex items-center gap-2">
                <Dna className="w-4 h-4 text-primary" />
                <span className="font-bold">Select a Docked Project</span>
              </div>
            </div>
            <div className="p-4 space-y-2">
              {loadingProjects ? (
                <div className="flex items-center gap-2 justify-center py-8 text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Loading projects...
                </div>
              ) : projects.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-sm">No projects with docking results found.</p>
                  <p className="text-xs mt-1">Run docking first, then come back here.</p>
                </div>
              ) : (
                projects.map((p) => (
                  <button
                    key={p.name}
                    onClick={() => selectProject(p)}
                    className="w-full flex items-center gap-3 p-3 rounded-lg border bg-card hover:bg-muted/30 transition-colors text-left group"
                  >
                    <div className="p-2 rounded-lg bg-primary/10 text-primary">
                      <Dna className="w-4 h-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold truncate">{p.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {p.hasDockingResults ? 'Docking results available' : 'No results'}
                      </p>
                    </div>
                    <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
                  </button>
                ))
              )}
            </div>
          </div>
        )}

        {/* Loading */}
        {pageStatus === 'loading' && (
          <div className="panel-card animate-fade-in max-w-2xl mx-auto">
            <div className="p-8 text-center space-y-4">
              <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto" />
              <p className="text-sm text-muted-foreground">
                Running interface analysis on {projectName}...
              </p>
            </div>
          </div>
        )}

        {/* Error */}
        {pageStatus === 'error' && (
          <div className="panel-card animate-fade-in max-w-2xl mx-auto">
            <div className="panel-header bg-destructive/10">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-destructive" />
                <span className="font-bold text-destructive">Analysis Failed</span>
              </div>
            </div>
            <div className="p-4 space-y-3">
              <p className="text-sm text-destructive">{pageError}</p>
              <Button variant="outline" onClick={handleNewProject}>Back to project list</Button>
            </div>
          </div>
        )}

        {/* Main Content — Ready */}
        {pageStatus === 'ready' && expData && interfaceData && (
          <div className="space-y-6 animate-fade-in">
            {/* Interface Summary */}
            <div className="panel-card">
              <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Target className="w-4 h-4 text-primary" />
                    <span className="font-bold">Interface Hotspots</span>
                    <span className="text-xs text-muted-foreground ml-2">
                      {projectName}
                    </span>
                    {isMultiPose && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-semibold">
                        {scanMeta.n_poses}-pose consensus
                      </span>
                    )}
                  </div>
                  {scanResults && (
                    <Button variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={handleExportCsv}>
                      <Download className="w-3 h-3" />
                      Export CSV
                    </Button>
                  )}
                </div>
              </div>

              {/* Summary stats */}
              {interfaceData.summary && (
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-px bg-border/50">
                  <StatCell label="Buried SA" value={`${interfaceData.summary.total_buried_sasa}`} unit="A&#178;" />
                  <StatCell label="Interface Res" value={`${interfaceData.summary.n_interface_residues_a + interfaceData.summary.n_interface_residues_b}`} />
                  <StatCell label="H-Bonds" value={`${interfaceData.summary.n_hbonds}`} />
                  <StatCell label="Salt Bridges" value={`${interfaceData.summary.n_salt_bridges}`} />
                  <StatCell label="Hydrophobic" value={`${interfaceData.summary.n_hydrophobic_contacts}`} />
                </div>
              )}

              {/* Chain legend (multi-component) */}
              {interfaceData.receptor_chains && interfaceData.binder_chains && (
                <div className="px-4 py-2 border-b border-border/30 flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="font-semibold">Receptor:</span>
                  {interfaceData.receptor_chains.map(ch => (
                    <span key={ch} className={`${chainColor(ch).bg} ${chainColor(ch).text} px-1.5 py-0.5 rounded font-mono font-bold`}>
                      {ch}
                    </span>
                  ))}
                  <span className="font-semibold ml-2">Binder:</span>
                  {interfaceData.binder_chains.map(ch => (
                    <span key={ch} className={`${chainColor(ch).bg} ${chainColor(ch).text} px-1.5 py-0.5 rounded font-mono font-bold`}>
                      {ch}
                    </span>
                  ))}
                  {interfaceData.partners && (
                    <span className="ml-2 text-[10px] text-muted-foreground/60 font-mono">
                      ({interfaceData.partners})
                    </span>
                  )}
                </div>
              )}

              {/* Hotspot table */}
              <div className="p-4">
                {expData.hotspots.length > 0 ? (
                  <div className="overflow-x-auto rounded-lg border">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-muted/50">
                          <th className="px-3 py-2 text-left font-semibold">Mutation</th>
                          <th className="px-3 py-2 text-left font-semibold">Residue</th>
                          <th className="px-3 py-2 text-right font-semibold">Heuristic Score</th>
                          <th className="px-3 py-2 text-right font-semibold">&Delta;SASA (A&#178;)</th>
                          {scanResults && (
                            <>
                              <th className="px-3 py-2 text-right font-semibold">
                                {isMultiPose ? 'Mean ' : ''}&Delta;&Delta;G (REU)
                              </th>
                              <th className="px-3 py-2 text-right font-semibold">
                                {isMultiPose ? 'Cross-Pose Std' : 'Std'}
                              </th>
                              <th className="px-3 py-2 text-right font-semibold">SNR</th>
                              <th className="px-3 py-2 text-center font-semibold">CI</th>
                              <th className="px-3 py-2 text-left font-semibold">Dominant</th>
                              <th className="px-3 py-2 text-left font-semibold">Classification</th>
                            </>
                          )}
                          {!scanResults && (
                            <th className="px-3 py-2 text-left font-semibold">Reason</th>
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {expData.hotspots.map((h, i) => {
                          const scanMatch = scanResults?.find(
                            s => s.chain === h.chain && s.resid === h.resid
                          );
                          return (
                            <tr key={i} className="border-t border-border/30 hover:bg-muted/30">
                              <td className="px-3 py-2 font-mono font-bold text-primary">{h.mutation}</td>
                              <td className="px-3 py-2 font-mono">
                                <span className={`inline-block w-5 h-5 rounded text-center text-[10px] font-bold leading-5 mr-1 ${
                                  chainColor(h.chain).bg} ${chainColor(h.chain).text
                                }`}>{h.chain}</span>
                                {(h.side || scanMatch?.side) && (
                                  <span className={`text-[9px] px-1 py-0.5 rounded mr-1 ${
                                    (h.side || scanMatch?.side) === 'receptor'
                                      ? 'bg-sky-500/10 text-sky-400 border border-sky-500/20'
                                      : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                                  }`}>
                                    {(h.side || scanMatch?.side) === 'receptor' ? 'R' : 'B'}
                                  </span>
                                )}
                                {h.resname}{h.resid}
                                <span className="text-muted-foreground ml-1">({AA_MAP[h.resname] || '?'}{h.resid})</span>
                              </td>
                              <td className="px-3 py-2 text-right font-mono font-semibold">{h.hotspot_score}</td>
                              <td className="px-3 py-2 text-right font-mono">{h.delta_sasa}</td>
                              {scanResults && (
                                <>
                                  <td className="px-3 py-2 text-right font-mono font-bold text-sm">
                                    {scanMatch?.ddG != null ? (
                                      <span className={ddgColor(scanMatch.ddG)}>
                                        {scanMatch.ddG > 0 ? '+' : ''}{scanMatch.ddG}
                                      </span>
                                    ) : (
                                      <span className="text-muted-foreground">--</span>
                                    )}
                                  </td>
                                  <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                                    {isMultiPose
                                      ? (scanMatch?.cross_pose_std != null ? `\u00b1${scanMatch.cross_pose_std}` : '')
                                      : (scanMatch?.mut_std != null ? `\u00b1${scanMatch.mut_std}` : '')}
                                  </td>
                                  <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                                    {scanMatch?.snr != null && scanMatch.snr !== Infinity
                                      ? scanMatch.snr.toFixed(1)
                                      : (scanMatch?.snr === Infinity ? '\u221e' : '')}
                                  </td>
                                  <td className="px-3 py-2 text-center font-mono text-[10px] text-muted-foreground">
                                    {scanMatch?.ci_lower != null && scanMatch?.ci_upper != null
                                      ? `[${scanMatch.ci_lower}, ${scanMatch.ci_upper}]`
                                      : ''}
                                  </td>
                                  <td className="px-3 py-2">
                                    {scanMatch?.energy_decomp?.dominant && (
                                      <span className="text-[10px] px-1 py-0.5 rounded bg-muted font-mono" title={
                                        ENERGY_TERM_LABELS[scanMatch.energy_decomp.dominant as string] || ''
                                      }>
                                        {formatDominantTerm(scanMatch.energy_decomp.dominant as string, scanMatch.energy_decomp)}
                                      </span>
                                    )}
                                  </td>
                                  <td className="px-3 py-2">
                                    {scanMatch && <DdgBadge classification={scanMatch.classification} />}
                                  </td>
                                </>
                              )}
                              {!scanResults && (
                                <td className="px-3 py-2 text-muted-foreground text-[10px] max-w-[250px]">
                                  {h.reason}
                                </td>
                              )}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    No significant hotspot residues found at this interface.
                  </p>
                )}

                {scanMeta.wt_dG != null && (
                  <div className="mt-2 space-y-1">
                    <p className="text-[10px] text-muted-foreground">
                      Wildtype interface dG_separated: {scanMeta.wt_dG} REU
                      {scanMeta.wt_std != null && ` (std: ${scanMeta.wt_std} REU)`}
                    </p>
                    {scanMeta.wt_noise_floor != null && scanMeta.wt_noise_floor > 0 && (
                      <p className="text-[10px] text-muted-foreground">
                        WT noise floor: &plusmn;{scanMeta.wt_noise_floor} REU | Mutations with SNR &lt; 1.5 are flagged uncertain
                      </p>
                    )}
                    {scanMeta.wt_warning && (
                      <p className="text-[10px] text-yellow-500 flex items-center gap-1">
                        <AlertCircle className="w-3 h-3 flex-shrink-0" />
                        {scanMeta.wt_warning}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* DDG Bar Chart */}
            {scanResults && scanResults.some(m => m.ddG != null) && (
              <div className="panel-card">
                <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
                  <div className="flex items-center gap-2">
                    <Target className="w-4 h-4 text-primary" />
                    <span className="font-bold">&Delta;&Delta;G Waterfall</span>
                    {isMultiPose && (
                      <span className="text-[10px] text-muted-foreground ml-1">(error bars = cross-pose std)</span>
                    )}
                  </div>
                </div>
                <div className="p-4">
                  <DdgBarChart mutations={scanResults} isMultiPose={isMultiPose} />
                </div>
              </div>
            )}

            {/* Scan Controls */}
            {expData.hotspots.length > 0 && (
              <div className="panel-card">
                <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
                  <div className="flex items-center gap-2">
                    <Target className="w-4 h-4 text-primary" />
                    <span className="font-bold">Run &Delta;&Delta;G Scan</span>
                  </div>
                </div>
                <div className="p-4 space-y-4">
                  {scanStatus === 'idle' && (
                    <>
                      <p className="text-xs text-muted-foreground">
                        Submit a Rosetta alanine scanning job via SLURM. Each hotspot residue is mutated to ALA,
                        repacked within 8A, minimized, and scored with InterfaceAnalyzerMover.
                        Typically completes in ~5 minutes.
                      </p>
                      <div className="flex flex-wrap items-end gap-4">
                        <div>
                          <label className="text-xs font-semibold text-muted-foreground block mb-1">Replicates per mutation</label>
                          <select
                            value={nstruct}
                            onChange={e => setNstruct(Number(e.target.value))}
                            className="h-9 px-3 rounded-md border bg-background text-sm"
                          >
                            <option value={1}>1 (fast)</option>
                            <option value={3}>3 (standard)</option>
                            <option value={5}>5 (robust)</option>
                            <option value={10}>10 (publication)</option>
                          </select>
                        </div>
                        <div>
                          <label className="text-xs font-semibold text-muted-foreground block mb-1">Max mutations</label>
                          <select
                            value={maxMutations}
                            onChange={e => setMaxMutations(Number(e.target.value))}
                            className="h-9 px-3 rounded-md border bg-background text-sm"
                          >
                            <option value={4}>Top 4</option>
                            <option value={8}>Top 8</option>
                            <option value={12}>Top 12</option>
                            <option value={16}>Top 16</option>
                          </select>
                        </div>
                        <div>
                          <label className="text-xs font-semibold text-muted-foreground block mb-1">Decoys to average</label>
                          <select
                            value={nPoses}
                            onChange={e => setNPoses(Number(e.target.value))}
                            className="h-9 px-3 rounded-md border bg-background text-sm"
                          >
                            <option value={1}>1 (single pose)</option>
                            <option value={3}>3 (recommended)</option>
                            <option value={5}>5 (thorough)</option>
                          </select>
                        </div>
                        <Button onClick={handleStartScan} className="h-9">
                          <Target className="w-4 h-4 mr-1.5" />
                          Submit Scan
                        </Button>
                      </div>
                    </>
                  )}

                  {scanStatus === 'submitting' && (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Submitting SLURM array job{nPoses > 1 ? 's' : ''}...
                    </div>
                  )}

                  {scanStatus === 'polling' && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-sm">
                        <Loader2 className="w-4 h-4 animate-spin text-primary" />
                        <span>Alanine scanning in progress... {scanProgress.done}/{scanProgress.total} tasks complete</span>
                        <Button variant="ghost" size="sm" className="ml-auto h-7 text-xs text-destructive hover:text-destructive gap-1" onClick={handleCancelScan}>
                          <XCircle className="w-3 h-3" />
                          Cancel
                        </Button>
                      </div>
                      <div className="w-full bg-muted rounded-full h-2">
                        <div
                          className="bg-primary h-2 rounded-full transition-all duration-500"
                          style={{ width: `${scanProgress.total > 0 ? (scanProgress.done / scanProgress.total) * 100 : 0}%` }}
                        />
                      </div>
                      <p className="text-[10px] text-muted-foreground">
                        {nPoses > 1
                          ? `${nPoses} poses x (WT + mutations) running in parallel via SLURM`
                          : `Wildtype + ${scanProgress.total - 1} mutations running in parallel via SLURM array job`}
                      </p>
                    </div>
                  )}

                  {scanStatus === 'done' && (
                    <div className="flex items-center gap-2 text-sm text-green-400">
                      <Shield className="w-4 h-4" />
                      <span>
                        &Delta;&Delta;G scan complete.
                        {isMultiPose && ` ${scanMeta.n_poses}-pose consensus computed.`}
                        {' '}Results displayed in the table above.
                      </span>
                      <Button variant="ghost" size="sm" className="ml-auto text-xs" onClick={() => setScanStatus('idle')}>
                        Re-run
                      </Button>
                    </div>
                  )}

                  {scanStatus === 'error' && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-sm text-destructive">
                        <AlertCircle className="w-4 h-4" />
                        <span>{scanError}</span>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => setScanStatus('idle')}>Retry</Button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Experiment Summary */}
            {expData.summary && (
              <div className="p-4 rounded-lg border bg-card/50 text-sm text-muted-foreground leading-relaxed">
                {expData.summary}
              </div>
            )}
          </div>
        )}

        <footer className="mt-12 text-center text-sm text-muted-foreground">
          <p>Powered by <span className="font-bold text-primary">Rosetta</span> &mdash; Kortemme &amp; Baker (2002)</p>
        </footer>
      </main>
    </div>
  );
}

// ── Helpers ──

function StatCell({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="bg-card px-3 py-2 text-center">
      <div className="text-lg font-bold font-mono">{value}<span className="text-xs text-muted-foreground ml-0.5">{unit}</span></div>
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</div>
    </div>
  );
}

function ddgColor(ddG: number): string {
  if (ddG >= 4.0) return 'text-red-400';
  if (ddG >= 2.0) return 'text-orange-400';
  if (ddG >= 1.0) return 'text-yellow-400';
  if (ddG < 0) return 'text-green-400';
  return 'text-muted-foreground';
}

function ddgFill(ddG: number): string {
  if (ddG >= 4.0) return '#f87171';
  if (ddG >= 2.0) return '#fb923c';
  if (ddG >= 1.0) return '#facc15';
  if (ddG < 0) return '#4ade80';
  return '#94a3b8';
}

function formatDominantTerm(term: string, decomp: Record<string, number | string>): string {
  const shortNames: Record<string, string> = {
    fa_atr: 'vdW', fa_rep: 'clash', fa_elec: 'elec',
    fa_sol: 'solv', hbond_sc: 'hbond', hbond_bb_sc: 'bb-hb', lk_ball_wtd: 'LK',
  };
  const val = decomp[term];
  const label = shortNames[term] || term;
  if (typeof val === 'number') {
    return `${label} ${val > 0 ? '+' : ''}${val}`;
  }
  return label;
}

function DdgBadge({ classification }: { classification: string }) {
  const styles: Record<string, string> = {
    critical: 'bg-red-500/15 text-red-400 border-red-500/30',
    strong: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
    moderate: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
    weak: 'bg-muted text-muted-foreground border-border',
    stabilizing: 'bg-green-500/15 text-green-400 border-green-500/30',
    uncertain: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30 border-dashed',
    error: 'bg-destructive/15 text-destructive border-destructive/30',
  };
  return (
    <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded border font-semibold ${styles[classification] || 'bg-muted text-muted-foreground border-border'}`}>
      {classification}
    </span>
  );
}

// ── DDG Bar Chart ──

function DdgChartTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-card/95 backdrop-blur border-2 border-border rounded-lg p-3 shadow-layered text-sm">
      <p className="font-bold font-mono text-foreground">{d.mutation}</p>
      <p className="mt-1">
        <span className="text-muted-foreground">DDG: </span>
        <span className={`font-bold ${ddgColor(d.ddG)}`}>
          {d.ddG > 0 ? '+' : ''}{d.ddG} REU
        </span>
      </p>
      {d.errorStd != null && d.errorStd > 0 && (
        <p className="text-muted-foreground text-xs">&plusmn;{d.errorStd.toFixed(2)} REU ({d.isMultiPose ? 'cross-pose std' : 'std'})</p>
      )}
      {d.snr != null && d.snr !== Infinity && (
        <p className="text-muted-foreground text-xs">SNR: {d.snr.toFixed(1)}</p>
      )}
      {d.dominant && (
        <p className="text-muted-foreground text-xs">Driven by: {ENERGY_TERM_LABELS[d.dominant] || d.dominant}</p>
      )}
      <p className="text-xs mt-1">
        <DdgBadge classification={d.classification} />
      </p>
    </div>
  );
}

function DdgBarChart({ mutations, isMultiPose }: { mutations: AlaScanMutation[]; isMultiPose: boolean }) {
  const data = mutations
    .filter(m => m.ddG != null)
    .sort((a, b) => (b.ddG ?? 0) - (a.ddG ?? 0))
    .map(m => ({
      mutation: m.mutation,
      ddG: m.ddG!,
      errorStd: isMultiPose ? (m.cross_pose_std ?? 0) : (m.mut_std ?? 0),
      classification: m.classification,
      snr: m.snr,
      dominant: (m.energy_decomp?.dominant as string) || null,
      isMultiPose,
    }));

  if (data.length === 0) return null;

  const hasErrors = data.some(d => d.errorStd > 0);

  return (
    <ResponsiveContainer width="100%" height={Math.max(200, data.length * 32 + 60)}>
      <BarChart data={data} layout="vertical" margin={{ top: 5, right: 30, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 11 }} label={{ value: 'DDG (REU)', position: 'insideBottom', offset: -2, fontSize: 11 }} />
        <YAxis type="category" dataKey="mutation" tick={{ fontSize: 11, fontFamily: 'monospace' }} width={80} />
        <Tooltip content={<DdgChartTooltip />} />
        <ReferenceLine x={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
        <ReferenceLine x={1} stroke="#facc1566" strokeDasharray="3 3" />
        <ReferenceLine x={2} stroke="#fb923c66" strokeDasharray="3 3" />
        <ReferenceLine x={4} stroke="#f8717166" strokeDasharray="3 3" />
        <Bar dataKey="ddG" radius={[0, 4, 4, 0]}>
          {data.map((entry, i) => (
            <Cell key={i} fill={ddgFill(entry.ddG)} />
          ))}
          {hasErrors && <ErrorBar dataKey="errorStd" width={4} stroke="#94a3b8" strokeWidth={1.5} />}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
