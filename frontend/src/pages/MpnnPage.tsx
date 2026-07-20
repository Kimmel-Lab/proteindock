import { useState, useEffect } from 'react';
import { Dna, Loader2, Copy, Check, Sliders, Sparkles, ChevronDown, ChevronUp } from 'lucide-react';
import { Header } from '@/components/Header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/hooks/use-toast';
import * as api from '@/services/api';
import type { MpnnSequence } from '@/services/api';

// ── Sequence card ────────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  // Lower score = better (negative log probability)
  if (score < -1.5) return '#22c55e';
  if (score < -1.0) return '#3b82f6';
  if (score < -0.5) return '#f59e0b';
  return '#ef4444';
}

function recoveryColor(r: number): string {
  if (r > 0.7) return '#22c55e';
  if (r > 0.5) return '#3b82f6';
  if (r > 0.3) return '#f59e0b';
  return '#ef4444';
}

function SequenceCard({ seq, wtSeq }: { seq: MpnnSequence; wtSeq?: string }) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  function copy() {
    navigator.clipboard.writeText(seq.sequence);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // Highlight mutations vs wild-type
  function renderSeq() {
    if (!wtSeq || wtSeq.length !== seq.sequence.length) {
      return <span className="font-mono text-xs break-all">{seq.sequence}</span>;
    }
    return (
      <span className="font-mono text-xs break-all">
        {seq.sequence.split('').map((aa, i) => (
          <span
            key={i}
            className={aa !== wtSeq[i] ? 'text-orange-400 font-bold' : 'text-muted-foreground'}
          >
            {aa}
          </span>
        ))}
      </span>
    );
  }

  const mutations = wtSeq
    ? seq.sequence.split('').filter((aa, i) => aa !== wtSeq[i]).length
    : null;

  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-xs font-bold text-muted-foreground">#{seq.rank}</span>
          <div className="flex gap-3 text-xs">
            <span>
              Score:{' '}
              <span className="font-mono font-bold" style={{ color: scoreColor(seq.score) }}>
                {seq.score.toFixed(3)}
              </span>
            </span>
            <span>
              Recovery:{' '}
              <span className="font-mono font-bold" style={{ color: recoveryColor(seq.recovery) }}>
                {(seq.recovery * 100).toFixed(0)}%
              </span>
            </span>
            {mutations !== null && (
              <span className="text-orange-400 font-semibold">{mutations} mutations</span>
            )}
          </div>
        </div>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={() => setExpanded(e => !e)} className="h-7 px-2">
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </Button>
          <Button variant="ghost" size="sm" onClick={copy} className="h-7 px-2">
            {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </div>
      {expanded && (
        <div className="mt-2 p-2 bg-muted/50 rounded text-xs break-all leading-relaxed">
          {renderSeq()}
        </div>
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function MpnnPage() {
  const { toast } = useToast();
  const [projects, setProjects] = useState<string[]>([]);
  const [project, setProject] = useState('');
  const [pdbPath, setPdbPath] = useState('');
  const [binderChain, setBinderChain] = useState('B');
  const [nSeqs, setNSeqs] = useState(10);
  const [temperature, setTemperature] = useState(0.1);
  const [interfaceOnly, setInterfaceOnly] = useState(true);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<MpnnSequence[] | null>(null);
  const [nInterfaceRes, setNInterfaceRes] = useState<number | null>(null);
  const [wtSeq, setWtSeq] = useState<string | undefined>();

  useEffect(() => {
    fetch(`${api.BASE}/projects`)
      .then(r => r.json())
      .then((r: any) => {
        const names: string[] = r.projects?.map((p: any) => p.name) ?? [];
        setProjects(names);
        if (names.length > 0) setProject(names[0]);
      })
      .catch(() => {});
  }, []);

  async function handleRun() {
    if (!project) { toast({ title: 'Select a project', variant: 'destructive' }); return; }
    setRunning(true);
    setResults(null);
    try {
      const r = await api.designMpnn(project, pdbPath, binderChain, nSeqs, temperature, interfaceOnly);
      setResults(r.sequences);
      setNInterfaceRes(r.n_interface_residues);
      if (r.sequences.length === 0) {
        toast({ title: 'No sequences generated', description: 'Check the binder chain ID', variant: 'destructive' });
      } else {
        toast({ title: `${r.sequences.length} sequences designed`, description: `${r.n_interface_residues ?? 'all'} residues redesigned on chain ${r.binder_chain}` });
      }
    } catch (e: any) {
      toast({ title: 'Design failed', description: e.message, variant: 'destructive' });
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <Header />
      <main className="flex-1 container mx-auto px-4 py-8 max-w-4xl">

        {/* Title */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-purple-500/10 rounded-lg">
            <Sparkles className="h-6 w-6 text-purple-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">ProteinMPNN Interface Redesign</h1>
            <p className="text-muted-foreground text-sm">
              Redesign binder interface residues using a learned protein sequence model
            </p>
          </div>
        </div>

        {/* What it does */}
        <div className="bg-purple-500/5 border border-purple-500/20 rounded-lg p-4 mb-6 text-sm">
          <p className="font-semibold text-purple-300 mb-1">How it works</p>
          <p className="text-muted-foreground">
            Takes your best docked model, identifies interface residues on the binder via SASA analysis,
            then runs ProteinMPNN to generate alternative sequences that are optimized for that backbone geometry.
            Lower score = higher predicted probability = better sequence. Mutations vs. wild-type highlighted in orange.
          </p>
        </div>

        {/* Config */}
        <div className="bg-card border border-border rounded-lg p-5 mb-6">
          <h2 className="font-semibold text-sm mb-4 flex items-center gap-2">
            <Sliders className="h-4 w-4" /> Settings
          </h2>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Project</label>
              <select
                className="w-full bg-background border border-border rounded px-3 py-2 text-sm"
                value={project}
                onChange={e => setProject(e.target.value)}
              >
                {projects.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Binder chain to redesign</label>
              <Input
                value={binderChain}
                onChange={e => setBinderChain(e.target.value.toUpperCase().trim())}
                className="font-mono"
                placeholder="B"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">
                Number of sequences
              </label>
              <Input type="number" min={1} max={100} value={nSeqs} onChange={e => setNSeqs(parseInt(e.target.value) || 10)} />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">
                Sampling temperature
              </label>
              <Input type="number" min={0.05} max={1.0} step={0.05} value={temperature} onChange={e => setTemperature(parseFloat(e.target.value) || 0.1)} />
              <p className="text-xs text-muted-foreground mt-1">0.1 = conservative · 0.3 = diverse</p>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">PDB path (leave blank for best docking model)</label>
            <Input value={pdbPath} onChange={e => setPdbPath(e.target.value)} placeholder="Optional: /path/to/model.pdb" />
          </div>
          <div className="mt-4 flex items-center gap-2">
            <input
              type="checkbox"
              id="ifaceonly"
              checked={interfaceOnly}
              onChange={e => setInterfaceOnly(e.target.checked)}
              className="rounded"
            />
            <label htmlFor="ifaceonly" className="text-sm cursor-pointer">
              Redesign interface residues only (recommended)
            </label>
          </div>
        </div>

        <Button onClick={handleRun} disabled={running || !project} className="w-full mb-8" size="lg">
          {running
            ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Running ProteinMPNN...</>
            : <><Sparkles className="h-4 w-4 mr-2" /> Design Sequences</>
          }
        </Button>

        {/* Results */}
        {results !== null && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold flex items-center gap-2">
                <Dna className="h-4 w-4 text-purple-400" />
                {results.length} Designed Sequences
                {nInterfaceRes !== null && (
                  <span className="text-xs font-normal text-muted-foreground ml-1">
                    ({nInterfaceRes} interface residues redesigned)
                  </span>
                )}
              </h2>
              <div className="flex gap-3 text-xs text-muted-foreground">
                <span><span className="text-green-500 font-bold">■</span> score &lt; −1.5 (best)</span>
                <span><span className="text-blue-500 font-bold">■</span> −1.5 to −1.0</span>
                <span><span className="text-yellow-500 font-bold">■</span> −1.0 to −0.5</span>
              </div>
            </div>

            {results.length === 0 ? (
              <div className="text-center text-muted-foreground py-12">No sequences generated. Check chain ID and PDB path.</div>
            ) : (
              <div className="space-y-2">
                {results.map(seq => (
                  <SequenceCard key={seq.rank} seq={seq} wtSeq={wtSeq} />
                ))}
              </div>
            )}

            {results.length > 0 && (
              <div className="mt-6 bg-card border border-border rounded-lg p-4 text-sm">
                <p className="font-semibold mb-2">Next steps</p>
                <ol className="list-decimal list-inside space-y-1 text-muted-foreground text-xs">
                  <li>Take the top 3 sequences (lowest score)</li>
                  <li>Predict their structures with ColabFold via the Docking page</li>
                  <li>Re-dock against your receptor to confirm improved interface</li>
                  <li>Run alanine scanning on promising designs to validate hotspots</li>
                </ol>
              </div>
            )}
          </div>
        )}

      </main>
    </div>
  );
}
