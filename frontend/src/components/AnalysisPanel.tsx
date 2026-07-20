import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Microscope, Brain, FlaskConical, Loader2, AlertCircle,
  ArrowUpDown, Atom, Droplets, Zap as ZapIcon, Shield, Target,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  analyzeInterface, aiInterpret, experimentPlan,
  submitAlaScan, checkAlaScanStatus,
  type InterfaceData, type AIInterpretation, type ExperimentPlanData,
  type AlaScanStatusResult, type AlaScanMutation,
} from '@/services/api';

const AA_MAP: Record<string, string> = {
  ALA: "A", ARG: "R", ASN: "N", ASP: "D", CYS: "C",
  GLN: "Q", GLU: "E", GLY: "G", HIS: "H", ILE: "I",
  LEU: "L", LYS: "K", MET: "M", PHE: "F", PRO: "P",
  SER: "S", THR: "T", TRP: "W", TYR: "Y", VAL: "V",
};

interface AnalysisPanelProps {
  projectName: string;
  pdbPath?: string;
}

type AnalysisStatus = 'idle' | 'loading' | 'done' | 'error';
type ScanStatus = 'idle' | 'submitting' | 'polling' | 'done' | 'error';

export function AnalysisPanel({ projectName, pdbPath }: AnalysisPanelProps) {
  const [status, setStatus] = useState<AnalysisStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [interfaceData, setInterfaceData] = useState<InterfaceData | null>(null);
  const [aiData, setAiData] = useState<AIInterpretation | null>(null);
  const [expData, setExpData] = useState<ExperimentPlanData | null>(null);

  // Alanine scan state
  const [scanStatus, setScanStatus] = useState<ScanStatus>('idle');
  const [scanError, setScanError] = useState<string | null>(null);
  const [scanProgress, setScanProgress] = useState<{ done: number; total: number }>({ done: 0, total: 0 });
  const [scanResults, setScanResults] = useState<AlaScanMutation[] | null>(null);
  const [scanWtDG, setScanWtDG] = useState<number | null>(null);
  const [scanWtStd, setScanWtStd] = useState<number | null>(null);
  const [scanWtWarning, setScanWtWarning] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const runAll = async () => {
    setStatus('loading');
    setError(null);
    try {
      const [iface, ai, exp] = await Promise.all([
        analyzeInterface(projectName, pdbPath),
        aiInterpret(projectName, pdbPath),
        experimentPlan(projectName, pdbPath),
      ]);
      setInterfaceData(iface);
      setAiData(ai);
      setExpData(exp);
      setStatus('done');
    } catch (e: any) {
      setError(e.message);
      setStatus('error');
    }
  };

  const pollScanStatus = useCallback(async () => {
    try {
      const result: AlaScanStatusResult = await checkAlaScanStatus(projectName);
      setScanProgress({ done: result.tasks_done, total: result.tasks_total });

      if (result.status === 'COMPLETED' && result.results) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setScanResults(result.results.mutations);
        setScanWtDG(result.results.wt_dG);
        setScanWtStd(result.results.wt_std ?? null);
        setScanWtWarning(result.results.wt_warning ?? null);
        setScanStatus('done');
      } else if (result.status === 'FAILED') {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setScanError(result.error || 'Scan job failed. Check SLURM logs.');
        setScanStatus('error');
      }
    } catch (e: any) {
      // Don't stop polling on transient errors
      console.error('Poll error:', e);
    }
  }, [projectName]);

  const startAlaScan = async () => {
    setScanStatus('submitting');
    setScanError(null);
    setScanResults(null);
    setScanWtDG(null);
    try {
      const result = await submitAlaScan(projectName, pdbPath);
      setScanProgress({ done: 0, total: result.num_mutations + 1 });
      setScanStatus('polling');

      // Start polling every 3 seconds
      pollRef.current = setInterval(pollScanStatus, 3000);
    } catch (e: any) {
      setScanError(e.message);
      setScanStatus('error');
    }
  };

  if (status === 'idle') {
    return (
      <div className="panel-card animate-fade-in">
        <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-primary/20 text-primary shadow-layered">
              <Microscope className="w-4 h-4" />
            </div>
            <span className="font-bold">Deep Analysis</span>
          </div>
        </div>
        <div className="p-6 text-center space-y-3">
          <p className="text-sm text-muted-foreground">
            Run interface analysis, AI interpretation, and experiment design in one click.
          </p>
          <Button
            className="h-12 px-8 bg-gradient-to-r from-primary to-primary/80 hover:shadow-lg transition-all font-bold"
            onClick={runAll}
          >
            <Microscope className="w-5 h-5 mr-2" />
            Run Deep Analysis
          </Button>
        </div>
      </div>
    );
  }

  if (status === 'loading') {
    return (
      <div className="panel-card animate-fade-in">
        <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-primary/20 text-primary">
              <Loader2 className="w-4 h-4 animate-spin" />
            </div>
            <span className="font-bold">Analyzing...</span>
          </div>
        </div>
        <div className="p-8 text-center space-y-4">
          <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto" />
          <p className="text-sm text-muted-foreground">
            Running interface analysis, AI interpretation, and experiment design...
          </p>
        </div>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="panel-card animate-fade-in">
        <div className="panel-header bg-destructive/10">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-destructive" />
            <span className="font-bold text-destructive">Analysis Failed</span>
          </div>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-sm text-destructive">{error}</p>
          <Button variant="outline" onClick={runAll}>Retry</Button>
        </div>
      </div>
    );
  }

  // status === 'done'
  const summary = interfaceData?.summary;

  return (
    <div className="panel-card animate-fade-in">
      <div className="panel-header bg-gradient-to-r from-primary/10 to-primary/5">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-primary/20 text-primary shadow-layered">
            <Microscope className="w-4 h-4" />
          </div>
          <span className="font-bold">Deep Analysis</span>
        </div>
        <Button variant="ghost" size="sm" className="ml-auto text-xs" onClick={runAll}>
          Re-run
        </Button>
      </div>

      {/* Summary stats bar */}
      {summary && (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-px bg-border/50">
          <StatCell label="Buried SA" value={`${summary.total_buried_sasa}`} unit="Å²" />
          <StatCell label="Residues A" value={`${summary.n_interface_residues_a}`} />
          <StatCell label="Residues B" value={`${summary.n_interface_residues_b}`} />
          <StatCell label="H-Bonds" value={`${summary.n_hbonds}`} />
          <StatCell label="Salt Bridges" value={`${summary.n_salt_bridges}`} />
          <StatCell label="Hydrophobic" value={`${summary.n_hydrophobic_contacts}`} />
        </div>
      )}

      <Tabs defaultValue="interface" className="w-full">
        <TabsList className="w-full grid grid-cols-3 h-10 rounded-none border-b">
          <TabsTrigger value="interface" className="text-xs gap-1.5 data-[state=active]:shadow-none">
            <Atom className="w-3.5 h-3.5" />
            Interface
          </TabsTrigger>
          <TabsTrigger value="ai" className="text-xs gap-1.5 data-[state=active]:shadow-none">
            <Brain className="w-3.5 h-3.5" />
            AI Analysis
          </TabsTrigger>
          <TabsTrigger value="experiments" className="text-xs gap-1.5 data-[state=active]:shadow-none">
            <FlaskConical className="w-3.5 h-3.5" />
            Experiments
          </TabsTrigger>
        </TabsList>

        {/* ── Interface Tab ── */}
        <TabsContent value="interface" className="p-4 space-y-4 mt-0">
          {summary && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ArrowUpDown className="w-3.5 h-3.5" />
              Dominant interaction: <span className="font-semibold text-foreground">{summary.dominant_interaction}</span>
            </div>
          )}

          {/* Residue table */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">Interface Residues (by buried surface)</h4>
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-muted/50">
                    <th className="px-2 py-1.5 text-left font-semibold">Chain</th>
                    <th className="px-2 py-1.5 text-left font-semibold">Residue</th>
                    <th className="px-2 py-1.5 text-right font-semibold">&Delta;SASA (Å²)</th>
                    <th className="px-2 py-1.5 text-right font-semibold">Contacts</th>
                    <th className="px-2 py-1.5 text-left font-semibold">Type</th>
                  </tr>
                </thead>
                <tbody>
                  {interfaceData && [...interfaceData.residues_a, ...interfaceData.residues_b]
                    .sort((a, b) => b.delta_sasa - a.delta_sasa)
                    .slice(0, 15)
                    .map((r, i) => (
                      <tr key={i} className="border-t border-border/30 hover:bg-muted/30">
                        <td className="px-2 py-1">
                          <span className={`inline-block w-5 h-5 rounded text-center text-[10px] font-bold leading-5 ${
                            r.chain === interfaceData.chain_a_id ? 'bg-teal-500/20 text-teal-400' : 'bg-orange-500/20 text-orange-400'
                          }`}>{r.chain}</span>
                        </td>
                        <td className="px-2 py-1 font-mono">{r.resname}{r.resid} <span className="text-muted-foreground">({AA_MAP[r.resname] || '?'}{r.resid})</span></td>
                        <td className="px-2 py-1 text-right font-mono">{r.delta_sasa}</td>
                        <td className="px-2 py-1 text-right font-mono">{r.n_contacts}</td>
                        <td className="px-2 py-1">
                          <TypeBadge type={r.classification} />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Contacts */}
          {interfaceData && (interfaceData.hbonds.length > 0 || interfaceData.salt_bridges.length > 0) && (
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">Key Contacts</h4>
              <div className="space-y-1.5">
                {interfaceData.hbonds.slice(0, 8).map((c, i) => (
                  <ContactRow key={`h${i}`} contact={c} icon={<Droplets className="w-3 h-3 text-blue-400" />} label="H-bond" />
                ))}
                {interfaceData.salt_bridges.slice(0, 6).map((c, i) => (
                  <ContactRow key={`s${i}`} contact={c} icon={<ZapIcon className="w-3 h-3 text-yellow-400" />} label="Salt bridge" />
                ))}
              </div>
            </div>
          )}
        </TabsContent>

        {/* ── AI Tab ── */}
        <TabsContent value="ai" className="p-4 space-y-4 mt-0">
          {aiData && (
            <>
              {aiData.rule_based.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">Score Interpretation</h4>
                  <div className="space-y-1.5">
                    {aiData.rule_based.map((obs, i) => {
                      const isGood = obs.includes('strong') || obs.includes('extensive') || obs.includes('favorable') || obs.includes('significant');
                      return (
                        <div key={i} className={`text-xs p-2 rounded-lg border ${
                          isGood ? 'bg-success/5 border-success/20' : 'bg-warning/5 border-warning/20'
                        }`}>
                          <span className="font-mono">{obs}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {aiData.llm_interpretation && (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                    <Brain className="w-3.5 h-3.5 inline mr-1" />
                    LLM Interpretation
                  </h4>
                  <div className="text-sm text-muted-foreground leading-relaxed p-3 bg-muted/30 rounded-lg border">
                    {aiData.llm_interpretation}
                  </div>
                </div>
              )}
              {aiData.rule_based.length === 0 && !aiData.llm_interpretation && (
                <p className="text-sm text-muted-foreground text-center py-4">No significant score observations.</p>
              )}
            </>
          )}
        </TabsContent>

        {/* ── Experiments Tab ── */}
        <TabsContent value="experiments" className="p-4 space-y-4 mt-0">
          {expData && (
            <>
              <p className="text-xs text-muted-foreground leading-relaxed">{expData.summary}</p>

              {/* Hotspot table */}
              {expData.hotspots.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">Predicted Hotspots</h4>
                  <div className="overflow-x-auto rounded-lg border">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-muted/50">
                          <th className="px-2 py-1.5 text-left font-semibold">Mutation</th>
                          <th className="px-2 py-1.5 text-left font-semibold">Residue</th>
                          <th className="px-2 py-1.5 text-right font-semibold">Score</th>
                          <th className="px-2 py-1.5 text-right font-semibold">&Delta;SASA</th>
                          {scanResults && (
                            <>
                              <th className="px-2 py-1.5 text-right font-semibold">&Delta;&Delta;G (REU)</th>
                              <th className="px-2 py-1.5 text-right font-semibold">SNR</th>
                              <th className="px-2 py-1.5 text-left font-semibold">Driver</th>
                            </>
                          )}
                          <th className="px-2 py-1.5 text-left font-semibold">{scanResults ? 'Class' : 'Reason'}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {expData.hotspots.map((h, i) => {
                          const scanMatch = scanResults?.find(
                            s => s.chain === h.chain && s.resid === h.resid
                          );
                          return (
                            <tr key={i} className="border-t border-border/30 hover:bg-muted/30">
                              <td className="px-2 py-1 font-mono font-bold text-primary">{h.mutation}</td>
                              <td className="px-2 py-1 font-mono">
                                <span className={`inline-block w-4 h-4 rounded text-center text-[9px] font-bold leading-4 mr-1 ${
                                  h.chain === 'A' ? 'bg-teal-500/20 text-teal-400' : 'bg-orange-500/20 text-orange-400'
                                }`}>{h.chain}</span>
                                {h.resname}{h.resid} <span className="text-muted-foreground">({AA_MAP[h.resname] || h.one_letter || '?'}{h.resid})</span>
                              </td>
                              <td className="px-2 py-1 text-right font-mono font-semibold">{h.hotspot_score}</td>
                              <td className="px-2 py-1 text-right font-mono">{h.delta_sasa}</td>
                              {scanResults && (
                                <>
                                  <td className="px-2 py-1 text-right font-mono font-bold">
                                    {scanMatch?.ddG != null ? (
                                      <span className={ddgColor(scanMatch.ddG)}>{scanMatch.ddG > 0 ? '+' : ''}{scanMatch.ddG}</span>
                                    ) : (
                                      <span className="text-muted-foreground">--</span>
                                    )}
                                  </td>
                                  <td className="px-2 py-1 text-right font-mono text-muted-foreground text-[10px]">
                                    {scanMatch?.snr != null && scanMatch.snr !== Infinity
                                      ? scanMatch.snr.toFixed(1)
                                      : (scanMatch?.snr === Infinity ? '\u221e' : '')}
                                  </td>
                                  <td className="px-2 py-1 text-[10px] font-mono text-muted-foreground">
                                    {scanMatch?.energy_decomp?.dominant
                                      ? formatDominantShort(scanMatch.energy_decomp.dominant as string)
                                      : ''}
                                  </td>
                                </>
                              )}
                              <td className="px-2 py-1">
                                {scanMatch ? (
                                  <DdgBadge classification={scanMatch.classification} />
                                ) : (
                                  <span className="text-muted-foreground text-[10px] max-w-[200px] truncate block">{h.reason}</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {scanWtDG != null && (
                    <div className="mt-1 space-y-0.5">
                      <p className="text-[10px] text-muted-foreground">
                        Wildtype dG_separated: {scanWtDG} REU
                        {scanWtStd != null && ` (std: ${scanWtStd} REU)`}
                      </p>
                      {scanWtWarning && (
                        <p className="text-[10px] text-yellow-500">{scanWtWarning}</p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* ΔΔG Scan controls */}
              {expData.hotspots.length > 0 && (
                <div className="p-3 rounded-lg border bg-card">
                  <div className="flex items-center gap-2 mb-2">
                    <Target className="w-3.5 h-3.5 text-primary" />
                    <span className="text-sm font-semibold">Computational Alanine Scanning</span>
                  </div>

                  {scanStatus === 'idle' && (
                    <div className="space-y-2">
                      <p className="text-xs text-muted-foreground">
                        Run Rosetta-based alanine scanning to compute true &Delta;&Delta;G for each hotspot.
                        Submits a SLURM job (~5 min).
                      </p>
                      <Button size="sm" onClick={startAlaScan}>
                        <Target className="w-3.5 h-3.5 mr-1.5" />
                        Run &Delta;&Delta;G Scan
                      </Button>
                    </div>
                  )}

                  {scanStatus === 'submitting' && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Submitting SLURM array job...
                    </div>
                  )}

                  {scanStatus === 'polling' && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-xs">
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
                        <span>Scanning... {scanProgress.done}/{scanProgress.total} tasks complete</span>
                      </div>
                      <div className="w-full bg-muted rounded-full h-1.5">
                        <div
                          className="bg-primary h-1.5 rounded-full transition-all duration-500"
                          style={{ width: `${scanProgress.total > 0 ? (scanProgress.done / scanProgress.total) * 100 : 0}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {scanStatus === 'done' && (
                    <div className="flex items-center gap-2 text-xs text-green-400">
                      <Shield className="w-3.5 h-3.5" />
                      <span>&Delta;&Delta;G scan complete. Results shown in table above.</span>
                      <Button variant="ghost" size="sm" className="ml-auto text-xs" onClick={startAlaScan}>
                        Re-run
                      </Button>
                    </div>
                  )}

                  {scanStatus === 'error' && (
                    <div className="space-y-2">
                      <p className="text-xs text-destructive">{scanError}</p>
                      <Button variant="outline" size="sm" onClick={startAlaScan}>Retry</Button>
                    </div>
                  )}
                </div>
              )}

              {/* Experiment cards */}
              {expData.experiments.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">Suggested Experiments</h4>
                  <div className="space-y-2">
                    {expData.experiments.map((exp, i) => (
                      <div key={i} className="p-3 rounded-lg border bg-card hover:bg-muted/20 transition-colors">
                        <div className="flex items-center gap-2 mb-1">
                          <FlaskConical className="w-3.5 h-3.5 text-primary" />
                          <span className="text-sm font-semibold">{exp.name}</span>
                          <PriorityBadge priority={exp.priority} />
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">{exp.description}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── Small helper components ──

function StatCell({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="bg-card px-3 py-2 text-center">
      <div className="text-lg font-bold font-mono">{value}<span className="text-xs text-muted-foreground ml-0.5">{unit}</span></div>
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</div>
    </div>
  );
}

function TypeBadge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    'charged+': 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    'charged-': 'bg-red-500/15 text-red-400 border-red-500/30',
    polar: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
    hydrophobic: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  };
  return (
    <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded border font-semibold ${styles[type] || 'bg-muted text-muted-foreground border-border'}`}>
      {type}
    </span>
  );
}

function ddgColor(ddG: number): string {
  if (ddG >= 4.0) return 'text-red-400';
  if (ddG >= 2.0) return 'text-orange-400';
  if (ddG >= 1.0) return 'text-yellow-400';
  if (ddG < 0) return 'text-green-400';
  return 'text-muted-foreground';
}

function formatDominantShort(term: string): string {
  const labels: Record<string, string> = {
    fa_atr: 'vdW', fa_rep: 'clash', fa_elec: 'elec',
    fa_sol: 'solv', hbond_sc: 'hbond', hbond_bb_sc: 'bb-hb', lk_ball_wtd: 'LK',
  };
  return labels[term] || term;
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

function ContactRow({ contact, icon, label }: { contact: any; icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs p-1.5 rounded bg-muted/20 border border-border/30">
      {icon}
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">
        {contact.resname_a}{contact.resid_a} ({AA_MAP[contact.resname_a] || '?'}{contact.resid_a}) [{contact.chain_a}]
      </span>
      <span className="text-muted-foreground">&mdash;</span>
      <span className="font-mono">
        {contact.resname_b}{contact.resid_b} ({AA_MAP[contact.resname_b] || '?'}{contact.resid_b}) [{contact.chain_b}]
      </span>
      <span className="ml-auto font-mono text-muted-foreground">{contact.distance}A</span>
    </div>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const p = priority.toLowerCase();
  const style = p.includes('high')
    ? 'bg-red-500/15 text-red-400 border-red-500/30'
    : p.includes('medium')
      ? 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30'
      : 'bg-muted text-muted-foreground border-border';
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold ml-auto ${style}`}>
      {priority}
    </span>
  );
}
