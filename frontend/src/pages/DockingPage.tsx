import { useState, useCallback, useRef, useEffect } from 'react';
import { Check } from 'lucide-react';
import { Header } from '@/components/Header';
import { StructureInputPanel } from '@/components/StructureInputPanel';
import { PreprocessingPanel } from '@/components/PreprocessingPanel';
import { DockingPanel } from '@/components/DockingPanel';
import { AnalysisPanel } from '@/components/AnalysisPanel';
import { DownloadsPanel } from '@/components/DownloadsPanel';
import { Input } from '@/components/ui/input';
import { useToast } from '@/hooks/use-toast';
import type {
  ComponentInput,
  ProcessingState,
  DockingState,
  DockingMode,
  OutputFile,
} from '@/types/docking';
import * as api from '@/services/api';
import type { DockingScore } from '@/services/api';

const CHAIN_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

const defaultComponent = (index: number): ComponentInput => ({
  id: `comp_${index}_${Date.now()}`,
  label: index === 0 ? 'Receptor' : index === 1 ? 'Binder' : `Component ${index + 1}`,
  chainId: CHAIN_LETTERS[index],
  method: 'fetch',
  status: 'idle',
});

// Helper to generate project name
const generateProjectName = () => {
  const now = new Date();
  return `project_${now.toISOString().slice(0, 10).replace(/-/g, '')}_${now.getTime().toString(36)}`;
};

export default function Index() {
  const { toast } = useToast();

  // Project name - each project gets its own folder
  const [projectName, setProjectName] = useState(generateProjectName);

  // Docking parameters
  const [nstruct, setNstruct] = useState(10);

  // Working directory (still shown in Header; backend uses its own paths)
  const [workingDir, setWorkingDir] = useState('./inputs');

  // ── Multi-component state ─────────────────────────────────
  const [components, setComponents] = useState<ComponentInput[]>([
    defaultComponent(0),
    defaultComponent(1),
  ]);

  // Partners string: auto-generated but user-editable
  const [partnersString, setPartnersString] = useState('A_B');

  // Docking mode: 'group' (dock to complex) or 'sequential' (assembly)
  const [dockingMode, setDockingMode] = useState<DockingMode>('group');

  // Auto-update partners when component count changes
  useEffect(() => {
    if (components.length >= 2) {
      const firstChain = CHAIN_LETTERS[0];
      const restChains = components.slice(1).map((_, i) => CHAIN_LETTERS[i + 1]).join('');
      setPartnersString(`${firstChain}_${restChains}`);
    }
  }, [components.length]);

  // Processing state
  const [processingState, setProcessingState] = useState<ProcessingState>({
    clean: 'idle',
    normalize: 'idle',
    sanitize: 'idle',
    merge: 'idle',
  });
  const [processingLogs, setProcessingLogs] = useState<string[]>([]);

  // Docking state
  const [dockingState, setDockingState] = useState<DockingState>({
    status: 'idle',
    progress: 0,
    logs: [],
  });

  // Live streaming state
  const [liveScores, setLiveScores] = useState<DockingScore[]>([]);
  const [currentStructure, setCurrentStructure] = useState(0);
  const [totalStructures, setTotalStructures] = useState(0);
  const [dockingStartTime, setDockingStartTime] = useState<Date | undefined>();

  // SLURM job tracking
  const [slurmJobId, setSlurmJobId] = useState<string | null>(null);

  // Stop polling (moved before handleNewProject which depends on it)
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  // ── Component management ──────────────────────────────────

  const addComponent = useCallback(() => {
    if (components.length >= 26) return;
    setComponents(prev => [...prev, defaultComponent(prev.length)]);
  }, [components.length]);

  const removeComponent = useCallback((id: string) => {
    setComponents(prev => {
      if (prev.length <= 2) return prev;
      const filtered = prev.filter(c => c.id !== id);
      // Re-assign chain IDs
      return filtered.map((c, i) => ({
        ...c,
        chainId: CHAIN_LETTERS[i],
        label: i === 0 ? 'Receptor' : i === 1 ? 'Binder' : (c.label.startsWith('Component') ? `Component ${i + 1}` : c.label),
      }));
    });
  }, []);

  const updateComponent = useCallback((id: string, update: Partial<ComponentInput>) => {
    setComponents(prev => prev.map(c => c.id === id ? { ...c, ...update } : c));
  }, []);

  // Reset everything for a new project
  const handleNewProject = useCallback(() => {
    const newProjectName = generateProjectName();
    setProjectName(newProjectName);

    setComponents([defaultComponent(0), defaultComponent(1)]);
    setPartnersString('A_B');

    setProcessingState({ clean: 'idle', normalize: 'idle', sanitize: 'idle', merge: 'idle' });
    setProcessingLogs([]);

    setDockingState({ status: 'idle', progress: 0, logs: [] });
    setDockingMode('group');
    setLiveScores([]);
    setCurrentStructure(0);
    setTotalStructures(0);
    setSlurmJobId(null);
    stopPolling();
    setOutputFiles([]);

    toast({ title: 'New Project Started', description: `Project: ${newProjectName}` });
  }, [toast, stopPolling]);

  // Load an existing project by name
  const handleProjectSelect = useCallback(async (name: string) => {
    setProjectName(name);

    setComponents([defaultComponent(0), defaultComponent(1)]);
    setPartnersString('A_B');
    setProcessingState({ clean: 'idle', normalize: 'idle', sanitize: 'idle', merge: 'idle' });
    setProcessingLogs([]);
    setLiveScores([]);
    setCurrentStructure(0);
    setTotalStructures(0);
    setSlurmJobId(null);
    stopPolling();
    setOutputFiles([]);

    try {
      const results = await fetch(`${api.BASE}/dock-results?project=${encodeURIComponent(name)}`);
      if (results.ok) {
        const data = await results.json();
        setDockingState({
          status: 'complete',
          progress: 100,
          logs: ['Loaded existing results.'],
          bestScore: data.best?.score,
          bestModel: data.best?.desc,
          bestPdbPath: data.best?.pdb_path,
          allModels: data.allModels,
        });
        toast({ title: 'Project loaded', description: `${name} — ${data.allModels?.length || 0} models` });
        return;
      }
    } catch { /* no results yet */ }

    setDockingState({ status: 'idle', progress: 0, logs: [] });
    toast({ title: 'Project loaded', description: name });
  }, [toast, stopPolling]);

  // Config content (display — backend uses nstruct from state, not from this text)
  const [optionsContent, setOptionsContent] = useState(
    `-s complex_input.pdb
-parser:protocol docking_full.xml
-nstruct ${nstruct}
-out:suffix _full`
  );

  const updateOptionsNstruct = useCallback((newNstruct: number) => {
    setNstruct(newNstruct);
    setOptionsContent((prev) =>
      prev.replace(/-nstruct\s+\d+/, `-nstruct ${newNstruct}`)
    );
  }, []);

  const [xmlContent] = useState(`<ROSETTASCRIPTS>
  <SCOREFXNS>
    <ScoreFunction name="ref15" weights="ref15"/>
  </SCOREFXNS>
  <MOVERS>
    <DockingProtocol name="dock" low_res_protocol_only="0"/>
  </MOVERS>
  <PROTOCOLS>
    <Add mover="dock"/>
  </PROTOCOLS>
</ROSETTASCRIPTS>`);

  // Output files (for Downloads panel)
  const [outputFiles, setOutputFiles] = useState<OutputFile[]>([]);

  // Log deduplication
  const lastRunningLogIndexRef = useRef<number>(-1);

  const addLog = (message: string) => {
    const timestamp = new Date().toLocaleTimeString();
    setProcessingLogs((prev) => [...prev, `[${timestamp}] ${message}`]);
  };

  const addDockingLog = (message: string) => {
    const timestamp = new Date().toLocaleTimeString();
    lastRunningLogIndexRef.current = -1;
    setDockingState((prev) => ({
      ...prev,
      logs: [...prev.logs, `[${timestamp}] ${message}`],
    }));
  };

  const updateOrAddRunningLog = (message: string) => {
    const timestamp = new Date().toLocaleTimeString();
    const formatted = `[${timestamp}] ${message}`;
    setDockingState((prev) => {
      const logs = [...prev.logs];
      if (lastRunningLogIndexRef.current >= 0 && lastRunningLogIndexRef.current < logs.length) {
        logs[lastRunningLogIndexRef.current] = formatted;
      } else {
        lastRunningLogIndexRef.current = logs.length;
        logs.push(formatted);
      }
      return { ...prev, logs };
    });
  };

  const canProcess = components.length >= 2 && components.every(c => c.status === 'ready');
  const canDock = processingState.merge === 'complete';

  // ============================================================
  // STRUCTURE INPUT HANDLERS
  // ============================================================

  const handleFetch = useCallback(
    async (componentId: string, pdbCode: string) => {
      const comp = components.find(c => c.id === componentId);
      if (!comp) return;
      updateComponent(componentId, { status: 'loading', pdbCode });
      addLog(`Fetching ${pdbCode} for ${comp.label}... (project: ${projectName})`);

      try {
        const result: any = await api.fetchPDB(projectName, componentId, pdbCode);
        const filePath = result.filePath || result.file_path;
        updateComponent(componentId, { status: 'ready', filePath });
        addLog(`${pdbCode} fetched successfully`);
        toast({ title: 'PDB Fetched', description: `${pdbCode} downloaded for ${comp.label}` });
      } catch (err: any) {
        updateComponent(componentId, { status: 'error', error: err.message || String(err) });
        addLog(`Fetch error: ${err.message || String(err)}`);
        toast({ title: 'Fetch failed', description: err.message || String(err), variant: 'destructive' });
      }
    },
    [components, toast, projectName, updateComponent]
  );

  const handleUpload = useCallback(
    async (componentId: string, file: File) => {
      const comp = components.find(c => c.id === componentId);
      if (!comp) return;
      updateComponent(componentId, { status: 'loading', file });
      addLog(`Uploading ${file.name} for ${comp.label}... (project: ${projectName})`);

      try {
        const result: any = await api.uploadFile(projectName, componentId, file);
        const filePath = result.filePath || result.file_path;
        updateComponent(componentId, { status: 'ready', filePath });
        addLog('Upload successful');
        toast({ title: 'File Uploaded', description: `${file.name} uploaded for ${comp.label}` });
      } catch (err: any) {
        updateComponent(componentId, { status: 'error', error: err.message || String(err) });
        addLog(`Upload failed: ${err.message || String(err)}`);
        toast({ title: 'Upload failed', description: err.message || String(err), variant: 'destructive' });
      }
    },
    [components, toast, projectName, updateComponent]
  );

  const handlePredict = useCallback(
    async (componentId: string, sequence: string) => {
      const comp = components.find(c => c.id === componentId);
      if (!comp) return;
      updateComponent(componentId, { status: 'loading', sequence });
      addLog(`Starting ColabFold prediction for ${comp.label}... (project: ${projectName})`);
      addLog(`Sequence length: ${sequence.length} residues`);

      try {
        const result: any = await api.predict(projectName, componentId, sequence);
        const filePath = result.filePath || result.file_path;
        updateComponent(componentId, { status: 'ready', filePath });
        addLog(`ColabFold prediction complete for ${comp.label}`);
        toast({ title: 'Prediction Complete', description: `Structure predicted for ${comp.label}` });
      } catch (err: any) {
        updateComponent(componentId, { status: 'error', error: err.message || String(err) });
        addLog(`Prediction failed: ${err.message || String(err)}`);
        toast({ title: 'Prediction failed', description: err.message || String(err), variant: 'destructive' });
      }
    },
    [components, toast, projectName, updateComponent]
  );

  // ============================================================
  // PREPROCESSING HANDLERS (multi-component)
  // ============================================================

  const handleClean = useCallback(async () => {
    const filePaths = components.map(c => c.filePath).filter(Boolean) as string[];
    if (filePaths.length < 2) {
      addLog('Cannot clean: not all components have file paths');
      return;
    }

    setProcessingState((prev) => ({ ...prev, clean: 'running' }));
    addLog(`Running Rosetta clean_pdb.py on ${components.length} components...`);

    try {
      const result: any = await api.cleanMulti(projectName, filePaths);

      addLog('All structures cleaned successfully');
      setProcessingState((prev) => ({ ...prev, clean: 'complete' }));

      // Update component file paths to cleaned versions
      const cleaned: string[] = result.cleaned || [];
      cleaned.forEach((path: string, i: number) => {
        if (components[i]) {
          updateComponent(components[i].id, { filePath: path });
        }
        setOutputFiles((prev) => [
          ...prev,
          { name: `${components[i]?.label.toLowerCase() || `component_${i}`}_clean.pdb`, path, type: 'pdb' },
        ]);
      });
    } catch (err: any) {
      setProcessingState((prev) => ({ ...prev, clean: 'error' }));
      addLog(`Clean failed: ${err.message || String(err)}`);
      toast({ title: 'Clean failed', description: err.message || String(err), variant: 'destructive' });
    }
  }, [components, toast, projectName, updateComponent]);

  const handleNormalize = useCallback(async () => {
    const filePaths = components.map(c => c.filePath).filter(Boolean) as string[];
    if (filePaths.length < 2) {
      addLog('Cannot normalize: not all components have file paths');
      return;
    }

    setProcessingState((prev) => ({ ...prev, normalize: 'running' }));
    addLog('Normalizing chain IDs...');

    try {
      const result: any = await api.normalizeMulti(projectName, filePaths);
      setProcessingState((prev) => ({ ...prev, normalize: 'complete' }));

      // Update component file paths
      const normalized: string[] = result.normalized || [];
      normalized.forEach((path: string, i: number) => {
        if (components[i]) {
          updateComponent(components[i].id, { filePath: path });
        }
      });

      const chainList = components.map((_, i) => CHAIN_LETTERS[i]).join(', ');
      addLog(`Chain IDs assigned: ${chainList}`);
    } catch (err: any) {
      setProcessingState((prev) => ({ ...prev, normalize: 'error' }));
      addLog(`Normalize failed: ${err.message || String(err)}`);
      toast({ title: 'Normalize failed', description: err.message || String(err), variant: 'destructive' });
    }
  }, [components, toast, projectName, updateComponent]);

  const handleSanitize = useCallback(async () => {
    const filePaths = components.map(c => c.filePath).filter(Boolean) as string[];
    if (filePaths.length < 2) {
      addLog('Cannot sanitize: not all components have file paths');
      return;
    }

    setProcessingState((prev) => ({ ...prev, sanitize: 'running' }));
    addLog('Renumbering residues...');

    try {
      const result: any = await api.sanitizeMulti(projectName, filePaths);
      setProcessingState((prev) => ({ ...prev, sanitize: 'complete' }));

      // Update component file paths
      const sanitized: string[] = result.sanitized || [];
      sanitized.forEach((path: string, i: number) => {
        if (components[i]) {
          updateComponent(components[i].id, { filePath: path });
        }
      });

      addLog('Residue numbering fixed');
    } catch (err: any) {
      setProcessingState((prev) => ({ ...prev, sanitize: 'error' }));
      addLog(`Sanitize failed: ${err.message || String(err)}`);
      toast({ title: 'Sanitize failed', description: err.message || String(err), variant: 'destructive' });
    }
  }, [components, toast, projectName, updateComponent]);

  const handleMerge = useCallback(async () => {
    const filePaths = components.map(c => c.filePath).filter(Boolean) as string[];
    if (filePaths.length < 2) {
      addLog('Cannot merge: not all components have file paths');
      return;
    }

    setProcessingState((prev) => ({ ...prev, merge: 'running' }));
    addLog(`Merging ${components.length} structures with 2A gap (partners: ${partnersString})...`);

    try {
      const result: any = await api.mergeMulti(projectName, filePaths, partnersString);

      const complexPath = result.output || result.path;
      setProcessingState((prev) => ({ ...prev, merge: 'complete' }));
      addLog(`Complex merged -> ${complexPath} (partners: ${result.partners || partnersString})`);

      if (result.partners) {
        setPartnersString(result.partners);
      }

      setOutputFiles((prev) => [
        ...prev,
        { name: 'complex_input.pdb', path: complexPath, type: 'pdb' },
      ]);

      toast({ title: 'Complex Ready', description: `${components.length} structures merged. Ready for docking.` });
    } catch (err: any) {
      setProcessingState((prev) => ({ ...prev, merge: 'error' }));
      addLog(`Merge failed: ${err.message || String(err)}`);
      toast({ title: 'Merge failed', description: err.message || String(err), variant: 'destructive' });
    }
  }, [components, projectName, partnersString, toast]);

  // ============================================================
  // DOCKING HANDLERS
  // ============================================================

  const handleRunDocking = useCallback(async () => {
    const startTime = new Date();
    setDockingStartTime(startTime);
    setDockingState({ status: 'running', progress: 0, logs: [], mode: dockingMode });
    setLiveScores([]);
    setCurrentStructure(0);
    setTotalStructures(nstruct);
    setSlurmJobId(null);
    stopPolling();

    const isSequential = dockingMode === 'sequential' && components.length > 2;

    try {
      if (isSequential) {
        // Sequential assembly mode
        const filePaths = components.map(c => c.filePath).filter(Boolean) as string[];
        addDockingLog(`Submitting sequential assembly (${components.length} components, ${components.length - 1} steps, nstruct=${nstruct})...`);
        const submitResult = await api.dockSlurmSequential(projectName, nstruct, filePaths);
        setSlurmJobId(submitResult.job_id);
        addDockingLog(`SLURM job submitted: ${submitResult.job_id} (${submitResult.num_steps} steps)`);
      } else {
        // Group mode (standard)
        addDockingLog(`Submitting SLURM job (nstruct=${nstruct}, project=${projectName}, partners=${partnersString})...`);
        const submitResult = await api.dockSlurm(projectName, nstruct);
        setSlurmJobId(submitResult.job_id);
        addDockingLog(`SLURM job submitted: ${submitResult.job_id}`);
        addDockingLog(`Output directory: ${submitResult.output_dir}`);
      }

      // Unified polling for both modes
      pollIntervalRef.current = setInterval(async () => {
        try {
          const status = await api.checkSlurmStatus(projectName);

          // Sequential mode progress
          if (status.mode === 'sequential') {
            const completedSteps = status.steps?.filter(s => s.status === 'completed').length || 0;
            const totalSteps = status.total_steps || 1;
            const overallPercent = Math.round((completedSteps / totalSteps) * 100);
            setDockingState((prev) => ({
              ...prev,
              mode: 'sequential',
              progress: overallPercent,
              currentStep: status.current_step,
              totalSteps: status.total_steps,
              stepPhase: status.step_phase,
              steps: status.steps,
            }));
            if (status.step_phase && status.current_step) {
              updateOrAddRunningLog(
                `Step ${status.current_step}/${status.total_steps}: ${status.step_phase}`
              );
            }
          } else {
            // Group mode progress
            if (status.structures_done !== undefined && status.nstruct) {
              const done = status.structures_done;
              const total = status.nstruct;
              const percent = Math.round((done / total) * 100);
              setCurrentStructure(done);
              setTotalStructures(total);
              setDockingState((prev) => ({ ...prev, progress: percent }));
            }
          }

          if (status.status === 'PENDING') {
            updateOrAddRunningLog(`Job ${status.job_id} is queued, waiting for resources...`);
          } else if (status.status === 'RUNNING' && !status.mode?.startsWith('seq')) {
            if (status.structures_done !== undefined) {
              const elapsedSec = dockingStartTime
                ? Math.floor((Date.now() - dockingStartTime.getTime()) / 1000)
                : 0;
              const elapsedStr = `${Math.floor(elapsedSec / 60)}:${(elapsedSec % 60).toString().padStart(2, '0')}`;
              updateOrAddRunningLog(
                `Running: ${status.structures_done}/${status.nstruct} structures completed (${elapsedStr} elapsed)`
              );
            }
          } else if (status.status === 'COMPLETED') {
            stopPolling();

            if (status.results) {
              setDockingState((prev) => ({
                ...prev,
                status: 'complete',
                progress: 100,
                bestScore: status.results!.bestScore,
                bestModel: status.results!.bestModel,
                bestPdbPath: status.results!.pdbPath,
                allModels: status.results!.allModels,
              }));

              addDockingLog('Docking complete!');
              addDockingLog(`Best score: ${status.results.bestScore.toFixed(2)} (${status.results.bestModel})`);

              setOutputFiles((prev) => [
                ...prev,
                { name: status.results!.bestModel + '.pdb', path: status.results!.pdbPath, type: 'pdb' },
              ]);

              toast({ title: 'Docking Complete!', description: `Best score: ${status.results.bestScore.toFixed(2)}` });
            } else {
              setDockingState((prev) => ({ ...prev, status: 'error' }));
              addDockingLog(`Job completed but no results: ${status.error || 'unknown error'}`);
            }
          } else if (status.status === 'FAILED' || status.status === 'CANCELLED') {
            stopPolling();
            setDockingState((prev) => ({ ...prev, status: 'error' }));
            addDockingLog(`Job ${status.status}: ${status.error || 'check SLURM logs'}`);
            if (status.log_tail) {
              addDockingLog(`Log tail:\n${status.log_tail}`);
            }
            toast({
              title: `Docking ${status.status}`,
              description: status.error || 'Check logs for details',
              variant: 'destructive',
            });
          }
        } catch (pollErr: any) {
          console.error('Poll error:', pollErr);
        }
      }, 5000);

    } catch (err: any) {
      setDockingState((prev) => ({ ...prev, status: 'error' }));
      addDockingLog(`Failed to submit SLURM job: ${err.message || String(err)}`);
      toast({ title: 'SLURM submission failed', description: err.message || String(err), variant: 'destructive' });
    }
  }, [toast, projectName, nstruct, partnersString, dockingMode, components, stopPolling, dockingStartTime]);

  const handleCancelDocking = useCallback(async () => {
    try {
      stopPolling();
      await api.cancelDocking(projectName);
      setDockingState((prev) => ({ ...prev, status: 'idle', progress: 0 }));
      setSlurmJobId(null);
      addDockingLog('Docking cancelled by user');
      toast({
        title: 'Docking Cancelled',
        description: slurmJobId ? `SLURM job ${slurmJobId} cancelled.` : 'The docking job was stopped.',
      });
    } catch (err: any) {
      addDockingLog(`Failed to cancel: ${err.message || String(err)}`);
    }
  }, [projectName, toast, slurmJobId, stopPolling]);

  const handleVisualize = useCallback(async () => {
    try {
      addDockingLog("Requesting PyMOL visualization (backend selects best model)");
      await api.visualize(projectName);
      toast({ title: "Opening PyMOL", description: "Launching visualization on backend..." });
    } catch (err: any) {
      toast({ title: "Visualization failed", description: err.message || String(err), variant: "destructive" });
      addDockingLog(`Visualization failed: ${err.message || String(err)}`);
    }
  }, [toast, projectName]);

  // ============================================================
  // DOWNLOAD HANDLER
  // ============================================================

  const handleDownload = useCallback(
    (file: OutputFile) => {
      toast({ title: 'Downloading', description: file.name });
      window.open(`${api.BASE}/download?path=${encodeURIComponent(file.path)}`, "_blank");
    },
    [toast]
  );

  // ============================================================
  // RENDER
  // ============================================================

  return (
    <div className="min-h-screen bg-background relative overflow-hidden">
      {/* Animated background elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary/5 rounded-full blur-3xl animate-pulse" />
        <div className="absolute top-1/2 -left-40 w-96 h-96 bg-primary/3 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '1s' }} />
        <div className="absolute -bottom-40 right-1/4 w-72 h-72 bg-primary/5 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '2s' }} />
      </div>

      <Header
        workingDir={workingDir}
        onWorkingDirChange={setWorkingDir}
        projectName={projectName}
        onProjectNameChange={setProjectName}
        nstruct={nstruct}
        onNstructChange={updateOptionsNstruct}
        onNewProject={handleNewProject}
        onProjectSelect={handleProjectSelect}
        showBackButton={true}
        backButtonLabel="Back to Dashboard"
      />

      <main className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Pipeline Progress Bar */}
        <div className="mb-8 p-3 sm:p-4 bg-card/80 backdrop-blur rounded-2xl border-2 border-border shadow-lg">
          <div className="flex items-center justify-between gap-2 sm:gap-4">
            <PipelineStep
              number={1}
              label="Input"
              active={!canProcess}
              complete={canProcess}
            />
            <div className="flex-1 h-1.5 bg-border/50 rounded-full overflow-hidden relative">
              <div
                className={`h-full rounded-full transition-all duration-700 ease-out ${
                  canProcess ? 'bg-gradient-to-r from-success to-success/60' : ''
                }`}
                style={{ width: canProcess ? '100%' : '0%' }}
              />
              {!canProcess && <div className="absolute inset-0 shimmer" />}
            </div>
            <PipelineStep
              number={2}
              label="Process"
              active={canProcess && !canDock}
              complete={canDock}
            />
            <div className="flex-1 h-1.5 bg-border/50 rounded-full overflow-hidden relative">
              <div
                className={`h-full rounded-full transition-all duration-700 ease-out ${
                  canDock ? 'bg-gradient-to-r from-success to-success/60' : ''
                }`}
                style={{ width: canDock ? '100%' : '0%' }}
              />
              {canProcess && !canDock && <div className="absolute inset-0 shimmer" />}
            </div>
            <PipelineStep
              number={3}
              label="Dock"
              active={canDock && dockingState.status !== 'complete'}
              complete={dockingState.status === 'complete'}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Panel 1: Input */}
          <div className="transform transition-all duration-300 hover:scale-[1.01]">
            <StructureInputPanel
              components={components}
              onComponentChange={updateComponent}
              onAddComponent={addComponent}
              onRemoveComponent={removeComponent}
              onFetch={handleFetch}
              onUpload={handleUpload}
              onPredict={handlePredict}
            />
          </div>

          {/* Panel 2: Preprocessing + Partners Editor */}
          <div className="transform transition-all duration-300 hover:scale-[1.01]">
            <PreprocessingPanel
              processingState={processingState}
              canProcess={canProcess}
              onClean={handleClean}
              onNormalize={handleNormalize}
              onSanitize={handleSanitize}
              onMerge={handleMerge}
              logs={processingLogs}
            />
            {/* Partners & Mode Editor */}
            {canProcess && (
              <div className="mt-4 p-4 bg-card/80 backdrop-blur rounded-xl border-2 border-border space-y-4">
                {/* Mode selector — only when 3+ components */}
                {components.length > 2 && (
                  <div>
                    <label className="text-xs font-bold uppercase tracking-wide" style={{ fontFamily: 'Oswald, sans-serif' }}>
                      Docking Mode
                    </label>
                    <div className="flex gap-2 mt-2">
                      <button
                        onClick={() => setDockingMode('group')}
                        className={`flex-1 px-3 py-2.5 rounded-lg text-sm font-semibold border-2 transition-all duration-200 ${
                          dockingMode === 'group'
                            ? 'border-primary bg-primary/10 text-primary shadow-md'
                            : 'border-border bg-card text-muted-foreground hover:border-primary/40'
                        }`}
                      >
                        <div className="font-bold">Dock to Complex</div>
                        <div className="text-xs mt-0.5 opacity-80">
                          Group chains and dock as 2-body
                        </div>
                      </button>
                      <button
                        onClick={() => setDockingMode('sequential')}
                        className={`flex-1 px-3 py-2.5 rounded-lg text-sm font-semibold border-2 transition-all duration-200 ${
                          dockingMode === 'sequential'
                            ? 'border-primary bg-primary/10 text-primary shadow-md'
                            : 'border-border bg-card text-muted-foreground hover:border-primary/40'
                        }`}
                      >
                        <div className="font-bold">Sequential Assembly</div>
                        <div className="text-xs mt-0.5 opacity-80">
                          Dock pairs: A+B → AB+C → ...
                        </div>
                      </button>
                    </div>
                  </div>
                )}

                {/* Partners string — hidden in sequential mode */}
                {dockingMode !== 'sequential' && (
                  <div>
                    <label className="text-xs font-bold uppercase tracking-wide" style={{ fontFamily: 'Oswald, sans-serif' }}>
                      Docking Partners
                    </label>
                    <div className="flex gap-2 mt-2">
                      <Input
                        value={partnersString}
                        onChange={(e) => setPartnersString(e.target.value.toUpperCase())}
                        className="font-mono text-sm"
                        placeholder="e.g. A_BCD"
                      />
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      Underscore separates docking groups (e.g., A_BCD = chain A docks against B+C+D)
                    </p>
                  </div>
                )}

                {/* Sequential info */}
                {dockingMode === 'sequential' && components.length > 2 && (
                  <div className="p-3 bg-primary/5 rounded-lg border border-primary/20">
                    <p className="text-xs text-muted-foreground">
                      <span className="font-bold text-primary">{components.length - 1} steps:</span>{' '}
                      {components.map((c, i) => {
                        if (i === 0) return c.chainId;
                        const prev = components.slice(0, i).map(p => p.chainId).join('');
                        return `${prev}+${c.chainId}`;
                      }).join(' → ')}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Panel 3: Docking */}
          <div className="transform transition-all duration-300 hover:scale-[1.01]">
            <DockingPanel
              dockingState={dockingState}
              canDock={canDock}
              optionsContent={optionsContent}
              xmlContent={xmlContent}
              projectName={projectName}
              onOptionsChange={setOptionsContent}
              onRunDocking={handleRunDocking}
              onVisualize={handleVisualize}
              onCancelDocking={handleCancelDocking}
              liveScores={liveScores}
              currentStructure={currentStructure}
              totalStructures={totalStructures}
              dockingStartTime={dockingStartTime}
            />
          </div>
        </div>

        {/* Deep Analysis -- appears after docking completes */}
        {dockingState.status === 'complete' && (
          <div className="mt-8">
            <AnalysisPanel
              projectName={projectName}
              pdbPath={dockingState.bestPdbPath}
            />
          </div>
        )}

        {/* Downloads Section */}
        <div className="mt-8">
          <DownloadsPanel files={outputFiles} onDownload={handleDownload} />
        </div>

        {/* Footer */}
        <footer className="mt-12 text-center text-sm text-muted-foreground">
          <p>Powered by <span className="font-bold text-primary">Rosetta</span></p>
        </footer>
      </main>
    </div>
  );
}

// Pipeline Step Component
function PipelineStep({ number, label, active, complete }: {
  number: number;
  label: string;
  active: boolean;
  complete: boolean;
}) {
  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className={`
          relative w-10 h-10 sm:w-12 sm:h-12 rounded-full flex items-center justify-center
          font-bold text-sm transition-all duration-500
          ${complete
            ? 'bg-success text-white shadow-lg shadow-success/40'
            : active
              ? 'bg-primary text-white shadow-lg shadow-primary/40'
              : 'bg-muted text-muted-foreground'
          }
        `}
        style={{ fontFamily: 'Oswald, sans-serif' }}
      >
        {complete ? (
          <Check className="w-5 h-5 animate-scale-in" />
        ) : (
          <span>{number}</span>
        )}
        {active && !complete && (
          <span className="absolute inset-0 rounded-full border-2 border-primary animate-ping opacity-30" />
        )}
      </div>
      <span className={`
        text-xs font-bold uppercase tracking-wider transition-colors duration-300
        ${complete ? 'text-success' : active ? 'text-primary' : 'text-muted-foreground'}
      `}>
        {label}
      </span>
    </div>
  );
}
