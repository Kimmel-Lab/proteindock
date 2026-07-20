/** Detect OOD reverse-proxy prefix (e.g. /node/<host>/<port>). Returns "" when running directly. */
function getBase(): string {
  if (typeof window === "undefined") return "";
  const match = window.location.pathname.match(/^(\/r?node\/[^/]+\/\d+)/);
  return match ? match[1] : "";
}
export const BASE = getBase();

export async function fetchPDB(project: string, role: string, pdb: string) {
  const form = new FormData();
  form.append("project", project);
  form.append("role", role);
  form.append("pdbCode", pdb);
  const res = await fetch(`${BASE}/fetch`, { method: "POST", body: form });
  return res.json();
}

export async function uploadFile(project: string, role: string, file: File) {
  const form = new FormData();
  form.append("project", project);
  form.append("role", role);
  form.append("file", file);

  const res = await fetch(`${BASE}/upload`, {
    method: "POST",
    body: form
  });

  return res.json();
}


export async function predict(project: string, role: string, sequence: string) {
  const form = new FormData();
  form.append("project", project);
  form.append("role", role);
  form.append("sequence", sequence);
  const res = await fetch(`${BASE}/predict`, { method: "POST", body: form });
  return res.json();
}

export async function clean(project: string, rec: string, bin: string) {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("rec", rec);
  fd.append("bin", bin);
  const res = await fetch(`${BASE}/clean`, { method: "POST", body: fd });
  return res.json();
}

export async function normalize(project: string, rec: string, bin: string) {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("rec", rec);
  fd.append("bin", bin);
  const res = await fetch(`${BASE}/normalize`, { method: "POST", body: fd });
  return res.json();
}

export async function sanitize(project: string, rec: string, bin: string) {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("rec", rec);
  fd.append("bin", bin);
  const res = await fetch(`${BASE}/sanitize`, { method: "POST", body: fd });
  return res.json();
}

export async function merge(project: string, rec: string, bin: string) {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("rec", rec);
  fd.append("bin", bin);
  const res = await fetch(`${BASE}/merge`, { method: "POST", body: fd });
  return res.json();
}

// ── Multi-component preprocessing ─────────────────────────

export async function cleanMulti(project: string, filePaths: string[]) {
  const res = await fetch(`${BASE}/clean-multi`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, components: filePaths }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function normalizeMulti(project: string, filePaths: string[]) {
  const res = await fetch(`${BASE}/normalize-multi`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, components: filePaths }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function sanitizeMulti(project: string, filePaths: string[]) {
  const res = await fetch(`${BASE}/sanitize-multi`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, components: filePaths }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function mergeMulti(
  project: string,
  filePaths: string[],
  partners?: string,
) {
  const res = await fetch(`${BASE}/merge-multi`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, components: filePaths, partners }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function dock(project: string, nstruct: number = 10) {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("nstruct", nstruct.toString());
  const res = await fetch(`${BASE}/dock`, { method: "POST", body: fd });
  return res.json();
}

// Types for streaming callbacks
export interface DockingProgress {
  current: number;
  total: number;
  percent: number;
}

export interface DockingScore {
  score: number;
  desc: string;
  line: string;
}

export interface DockingResult {
  bestScore: number;
  bestModel: string;
  pdbPath: string;
  index: number;
  allModels?: Array<{
    score: number;
    total_score: number;
    rms?: number;
    CAPRI_rank?: number;
    Fnat?: number;
    I_sc?: number;
    Irms?: number;
    Irms_leg?: number;
    cen_rms?: number;
    dslf_fa13?: number;
    fa_atr?: number;
    fa_dun?: number;
    fa_elec?: number;
    fa_intra_rep?: number;
    fa_intra_sol_xover4?: number;
    fa_rep?: number;
    fa_sol?: number;
    hbond_bb_sc?: number;
    hbond_lr_bb?: number;
    hbond_sc?: number;
    hbond_sr_bb?: number;
    lk_ball_wtd?: number;
    omega?: number;
    p_aa_pp?: number;
    pro_close?: number;
    rama_prepro?: number;
    ref?: number;
    st_rmsd?: number;
    yhh_planarity?: number;
    desc: string;
    index: number | null;
    pdb_path: string | null;
    [key: string]: any;
  }>;
}

export interface DockingCallbacks {
  onStart?: (data: { total: number; message: string }) => void;
  onProgress?: (data: DockingProgress) => void;
  onScore?: (data: DockingScore) => void;
  onComplete?: (result: DockingResult) => void;
  onError?: (error: string) => void;
}

/**
 * Run docking with real-time progress streaming via SSE
 */
export async function dockWithProgress(
  project: string,
  nstruct: number,
  callbacks: DockingCallbacks
): Promise<void> {
  const formData = new FormData();
  formData.append('project', project);
  formData.append('nstruct', nstruct.toString());

  const response = await fetch(`${BASE}/dock-stream`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.text();
    callbacks.onError?.(error);
    return;
  }

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();

  if (!reader) {
    callbacks.onError?.('Failed to start stream');
    return;
  }

  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      
      // Process complete SSE messages
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || ''; // Keep incomplete message in buffer

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            
            switch (data.type) {
              case 'start':
                callbacks.onStart?.(data);
                break;
              case 'progress':
                callbacks.onProgress?.(data);
                break;
              case 'score':
                callbacks.onScore?.(data);
                break;
              case 'complete':
                callbacks.onComplete?.(data);
                break;
              case 'error':
                callbacks.onError?.(data.message);
                break;
            }
          } catch (e) {
            console.error('Failed to parse SSE data:', line, e);
          }
        }
      }
    }
  } catch (error) {
    callbacks.onError?.(String(error));
  }
}

/**
 * Cancel a running docking job
 */
export async function cancelDocking(project: string): Promise<{ status: string }> {
  const fd = new FormData();
  fd.append("project", project);
  const res = await fetch(`${BASE}/dock-cancel`, { method: "POST", body: fd });
  return res.json();
}

/**
 * Fetch raw PDB file content for 3Dmol.js rendering
 */
export async function fetchPdbContent(pdbPath: string): Promise<string> {
  const res = await fetch(`${BASE}/pdb-content?path=${encodeURIComponent(pdbPath)}`);
  if (!res.ok) throw new Error(`Failed to load PDB: ${res.statusText}`);
  return res.text();
}

/**
 * Download a self-contained shareable HTML report for a docking result.
 * Triggers browser download of the file.
 */
export async function downloadShareHtml(project: string, pdbPath?: string): Promise<void> {
  const params = new URLSearchParams({ project });
  if (pdbPath) params.append("pdb_path", pdbPath);
  const res = await fetch(`${BASE}/share?${params}`);
  if (!res.ok) throw new Error(`Failed to generate report: ${res.statusText}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${project}_report.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ============================================================
// ANALYSIS ENDPOINTS
// ============================================================

export interface InterfaceResidue {
  chain: string;
  resname: string;
  resid: number;
  delta_sasa: number;
  n_contacts: number;
  classification: string;
}

export interface InterfaceContact {
  type: string;
  chain_a: string;
  resname_a: string;
  resid_a: number;
  atom_a: string;
  chain_b: string;
  resname_b: string;
  resid_b: number;
  atom_b: string;
  distance: number;
}

export interface InterfaceData {
  project: string;
  pdb_path: string;
  residues_a: InterfaceResidue[];
  residues_b: InterfaceResidue[];
  hbonds: InterfaceContact[];
  salt_bridges: InterfaceContact[];
  hydrophobic_contacts: InterfaceContact[];
  total_buried_sasa: number;
  partners?: string;
  receptor_chains?: string[];
  binder_chains?: string[];
  summary: {
    n_interface_residues_a: number;
    n_interface_residues_b: number;
    n_hbonds: number;
    n_salt_bridges: number;
    n_hydrophobic_contacts: number;
    total_buried_sasa: number;
    dominant_interaction: string;
  };
}

export interface AIInterpretation {
  project: string;
  pdb_path: string;
  rule_based: string[];
  llm_interpretation: string | null;
  interface_summary: Record<string, any>;
}

export interface HotSpot {
  chain: string;
  resname: string;
  resid: number;
  one_letter: string;
  delta_sasa: number;
  n_contacts: number;
  classification: string;
  hotspot_score: number;
  reason: string;
  mutation: string;
  side?: 'receptor' | 'binder';
}

export interface ExperimentPlanData {
  project: string;
  pdb_path: string;
  hotspots: HotSpot[];
  mutations: string[];
  experiments: Array<{ name: string; description: string; priority: string }>;
  summary: string;
}

export async function analyzeInterface(project: string, pdbPath?: string): Promise<InterfaceData> {
  const params = new URLSearchParams({ project });
  if (pdbPath) params.append("pdb_path", pdbPath);
  const res = await fetch(`${BASE}/analyze-interface?${params}`);
  if (!res.ok) throw new Error(`Interface analysis failed: ${res.statusText}`);
  return res.json();
}

export async function aiInterpret(project: string, pdbPath?: string): Promise<AIInterpretation> {
  const params = new URLSearchParams({ project });
  if (pdbPath) params.append("pdb_path", pdbPath);
  const res = await fetch(`${BASE}/ai-interpret?${params}`);
  if (!res.ok) throw new Error(`AI interpretation failed: ${res.statusText}`);
  return res.json();
}

export async function experimentPlan(project: string, pdbPath?: string): Promise<ExperimentPlanData> {
  const params = new URLSearchParams({ project });
  if (pdbPath) params.append("pdb_path", pdbPath);
  const res = await fetch(`${BASE}/experiment-plan?${params}`);
  if (!res.ok) throw new Error(`Experiment plan failed: ${res.statusText}`);
  return res.json();
}

export async function visualize(project: string, pdb?: string) {
  const fd = new FormData();
  fd.append("project", project);
  if (pdb) fd.append("pdb", pdb);
  const res = await fetch(`${BASE}/visualize`, { method: "POST", body: fd });
  return res.json();
}

// ============================================================
// SLURM DOCKING
// ============================================================

export interface SlurmSubmitResult {
  job_id: string;
  status: string;
  project: string;
  output_dir: string;
}

export interface SlurmStatusResult {
  job_id: string;
  status: string;
  project: string;
  structures_done?: number;
  nstruct?: number;
  log_tail?: string;
  error?: string;
  results?: DockingResult & { allModels?: DockingResult['allModels'] };
  // Sequential assembly fields
  mode?: 'group' | 'sequential';
  current_step?: number;
  total_steps?: number;
  step_phase?: string;
  steps?: Array<{
    step: number;
    status: string;
    best_score?: number;
    best_model?: string;
    best_pdb?: string;
  }>;
}

/**
 * Submit docking as a SLURM job (returns immediately with job_id)
 */
export async function dockSlurm(
  project: string,
  nstruct: number,
  timeLimit: string = "01:00:00",
  cpus: number = 4,
): Promise<SlurmSubmitResult> {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("nstruct", nstruct.toString());
  fd.append("time_limit", timeLimit);
  fd.append("cpus", cpus.toString());
  const res = await fetch(`${BASE}/dock-slurm`, { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

/**
 * Submit sequential assembly docking as a SLURM job.
 */
export async function dockSlurmSequential(
  project: string,
  nstruct: number,
  components: string[],
  timeLimit: string = "01:00:00",
  cpus: number = 4,
): Promise<SlurmSubmitResult & { mode: string; num_steps: number }> {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("nstruct", nstruct.toString());
  fd.append("time_limit", timeLimit);
  fd.append("cpus", cpus.toString());
  fd.append("components", JSON.stringify(components));
  const res = await fetch(`${BASE}/dock-slurm-sequential`, { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

/**
 * Check SLURM job status (poll this until status is COMPLETED or FAILED)
 */
export async function checkSlurmStatus(project: string): Promise<SlurmStatusResult> {
  const res = await fetch(`${BASE}/dock-slurm-status?project=${encodeURIComponent(project)}`);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

// ============================================================
// ALANINE SCANNING (ΔΔG)
// ============================================================

export interface AlaScanMutation {
  mutation: string;
  chain: string;
  resname: string;
  resid: number;
  side?: 'receptor' | 'binder';
  wt_dG: number;
  mut_dG: number | null;
  mut_std?: number;
  ddG: number | null;
  classification: string;
  error?: string;
  // Publication-grade fields
  ci_lower?: number;
  ci_upper?: number;
  snr?: number;
  energy_decomp?: Record<string, number | string>;
  // Multi-pose fields
  per_pose?: Array<{ pose: string; ddG: number; mut_std: number; wt_dG: number }>;
  n_poses_ok?: number;
  cross_pose_std?: number;
  mean_ddG?: number;
}

export interface AlaScanResults {
  wt_dG: number;
  wt_std?: number;
  wt_n_replicates?: number;
  wt_warning?: string;
  wt_noise_floor?: number;
  mutations: AlaScanMutation[];
  // Multi-pose fields
  mode?: "single_pose" | "multi_pose";
  n_poses?: number;
  per_pose_results?: Record<string, { wt_dG: number; wt_std: number; mutations: AlaScanMutation[] }>;
}

export interface AlaScanSubmitResult {
  job_id: string;
  status: string;
  project: string;
  mutations: string[];
  num_mutations: number;
  n_poses?: number;
  mode?: string;
}

export interface AlaScanStatusResult {
  job_id: string;
  status: string;
  project: string;
  tasks_done: number;
  tasks_total: number;
  tasks_failed: number;
  mutations: string[];
  results?: AlaScanResults;
  error?: string;
  mode?: string;
  n_poses?: number;
  per_pose_status?: Array<{ job_id: string; pose_dir: string; status: string; done: number; total: number }>;
}

/**
 * Submit Rosetta computational alanine scanning (SLURM array job)
 * nPoses > 1 triggers multi-decoy averaging across top N docking poses.
 */
export async function submitAlaScan(
  project: string,
  pdbPath?: string,
  nstruct: number = 3,
  maxMutations: number = 8,
  nPoses: number = 1,
): Promise<AlaScanSubmitResult> {
  const fd = new FormData();
  fd.append("project", project);
  if (pdbPath) fd.append("pdb_path", pdbPath);
  fd.append("nstruct", nstruct.toString());
  fd.append("max_mutations", maxMutations.toString());
  fd.append("n_poses", nPoses.toString());
  const res = await fetch(`${BASE}/ala-scan`, { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

/**
 * Check alanine scan status (poll until COMPLETED or FAILED)
 */
export async function checkAlaScanStatus(project: string): Promise<AlaScanStatusResult> {
  const res = await fetch(`${BASE}/ala-scan-status?project=${encodeURIComponent(project)}`);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

/**
 * Cancel a running alanine scan SLURM job
 */
export async function cancelAlaScan(project: string): Promise<{ status: string }> {
  const fd = new FormData();
  fd.append("project", project);
  const res = await fetch(`${BASE}/ala-scan-cancel`, { method: "POST", body: fd });
  return res.json();
}

// ═══════════════════════════════════════════════════════════════
//  ncAA Bayesian Optimization
// ═══════════════════════════════════════════════════════════════

export interface NcaaOptResult {
  ncaa: string;
  position: number;
  chain: string;
  resid: number;
  wt_aa: string;
  wt_aa3?: string;
  sasa?: number;
  ddg_bind: number;
  ddg_fold: number;
  objective_score: number;
  status: string;
  error_msg?: string;
  iteration?: number;
  timestamp?: string;
  // multi-mutation fields
  mutations?: string[];
  n_mutations?: number;
}

export interface NcaaOptResults {
  best: NcaaOptResult | null;
  top5: NcaaOptResult[];
  history: NcaaOptResult[];
  pareto?: { ncaa: string; position: number; ddg_bind: number; abs_ddg_fold: number }[];
  best_score?: number;
  best_params?: string[];
  mode: string;
  n_calls: number;
}

export interface NcaaOptSubmitResult {
  job_id: string;
  status: string;
  project: string;
  ncaa_list: string[];
  mode: string;
  n_calls: number;
}

export interface NcaaOptStatusResult {
  job_id: string;
  status: string;
  project: string;
  evaluations_done: number;
  evaluations_total: number;
  mode: string;
  ncaa_list: string[];
  results?: NcaaOptResults;
  error?: string;
}

export interface NcaaBuiltinEntry {
  code: string;
  label: string;
}

/**
 * Fetch the list of built-in ncAA residue types from PyRosetta database
 */
export async function fetchNcaaBuiltinLibrary(): Promise<{ count: number; entries: NcaaBuiltinEntry[] }> {
  const res = await fetch(`${BASE}/ncaa-builtin-library`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/**
 * Upload .params files for non-canonical amino acids
 */
export async function uploadNcaaParams(
  project: string,
  files: File[],
): Promise<{ count: number; ncaa_names: string[]; params_dir: string }> {
  const fd = new FormData();
  fd.append("project", project);
  for (const f of files) {
    fd.append("files", f);
  }
  const res = await fetch(`${BASE}/ncaa-upload-params`, { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

/**
 * Submit ncAA Bayesian optimization SLURM job
 */
export async function submitNcaaOptimize(
  project: string,
  ncaaList: string[],
  positions: string = "auto",
  mode: string = "single",
  nCalls: number = 20,
  trials: number = 1,
  useAlaScanSeed: boolean = false,
  timeLimit: string = "02:00:00",
  cpus: number = 4,
): Promise<NcaaOptSubmitResult> {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("ncaa_list", ncaaList.join(","));
  fd.append("positions", positions);
  fd.append("mode", mode);
  fd.append("n_calls", nCalls.toString());
  fd.append("trials", trials.toString());
  fd.append("use_ala_scan_seed", useAlaScanSeed.toString());
  fd.append("time_limit", timeLimit);
  fd.append("cpus", cpus.toString());
  const res = await fetch(`${BASE}/ncaa-optimize`, { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

/**
 * Check ncAA optimization SLURM job status
 */
export async function checkNcaaOptStatus(project: string): Promise<NcaaOptStatusResult> {
  const res = await fetch(`${BASE}/ncaa-optimize-status?project=${encodeURIComponent(project)}`);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

/**
 * Cancel a running ncAA optimization SLURM job
 */
export async function cancelNcaaOptimize(project: string): Promise<{ status: string }> {
  const fd = new FormData();
  fd.append("project", project);
  const res = await fetch(`${BASE}/ncaa-optimize-cancel`, { method: "POST", body: fd });
  return res.json();
}

// ── Benchmarking (DockQ) ──────────────────────────────────────────────────────

export interface BenchmarkEntry {
  pdb_code: string;
  receptor_chains: string[];
  binder_chains: string[];
  category: string;
  description: string;
}

export interface BenchmarkResult extends BenchmarkEntry {
  status: "running" | "success" | "failed";
  DockQ?: number;
  Fnat?: number;
  iRMS?: number;
  LRMS?: number;
  classification?: string;
  rosetta_score?: number;
  error?: string;
  started_at?: string;
  finished_at?: string;
}

export interface BenchmarkSummary {
  mean_DockQ: number | null;
  median_DockQ: number | null;
  success_rate: number;
  acceptable_or_better: number;
  by_classification: Record<string, number>;
  n_total: number;
  n_success: number;
}

export interface BenchmarkStatusResult {
  status: string;
  done: number;
  total: number;
  results: BenchmarkResult[];
  summary?: BenchmarkSummary;
}

export async function fetchBenchmarkPresets(): Promise<{ presets: BenchmarkEntry[] }> {
  const res = await fetch(`${BASE}/benchmark-presets`);
  return res.json();
}

export async function submitBenchmark(
  entries: BenchmarkEntry[],
  nstruct: number = 10,
  timeLimit: string = "04:00:00",
  cpus: number = 4,
): Promise<{ job_id: string; num_entries: number }> {
  const fd = new FormData();
  fd.append("entries", JSON.stringify(entries));
  fd.append("nstruct", nstruct.toString());
  fd.append("time_limit", timeLimit);
  fd.append("cpus", cpus.toString());
  const res = await fetch(`${BASE}/benchmark`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function checkBenchmarkStatus(
  jobId: string,
  numEntries: number,
): Promise<BenchmarkStatusResult> {
  const res = await fetch(
    `${BASE}/benchmark-status?job_id=${encodeURIComponent(jobId)}&num_entries=${numEntries}`
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── ProteinMPNN Interface Redesign ────────────────────────────────────────────

export interface MpnnSequence {
  rank: number;
  sequence: string;
  score: number;
  recovery: number;
  chain: string;
  temperature: number;
}

export interface MpnnDesignResult {
  project: string;
  pdb_path: string;
  binder_chain: string;
  n_interface_residues: number | null;
  sequences: MpnnSequence[];
}

export async function designMpnn(
  project: string,
  pdbPath: string,
  binderChain: string = "B",
  nSeqs: number = 10,
  temperature: number = 0.1,
  redesignInterfaceOnly: boolean = true,
): Promise<MpnnDesignResult> {
  const fd = new FormData();
  fd.append("project", project);
  fd.append("pdb_path", pdbPath);
  fd.append("binder_chain", binderChain);
  fd.append("n_seqs", nSeqs.toString());
  fd.append("temperature", temperature.toString());
  fd.append("redesign_interface_only", redesignInterfaceOnly.toString());
  const res = await fetch(`${BASE}/design-mpnn`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

