export type InputMethod = 'fetch' | 'upload' | 'predict';

export type StructureRole = string;

export type ProcessingStep = 'clean' | 'normalize' | 'sanitize' | 'merge';

export type StepStatus = 'idle' | 'running' | 'complete' | 'error';

export interface ComponentInput {
  id: string;
  label: string;
  chainId: string;
  method: InputMethod;
  pdbCode?: string;
  sequence?: string;
  file?: File;
  status: 'idle' | 'loading' | 'ready' | 'error';
  filePath?: string;
  error?: string;
}

// Backward-compat alias
export type StructureInput = ComponentInput;

export interface ProcessingState {
  clean: StepStatus;
  normalize: StepStatus;
  sanitize: StepStatus;
  merge: StepStatus;
}

export interface DockingModel {
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
  [key: string]: any; // Allow other score components
}

export type DockingMode = 'group' | 'sequential';

export interface SequentialStep {
  step: number;
  status: 'pending' | 'merging' | 'docking' | 'parsing' | 'completed' | 'failed';
  best_score?: number;
  best_model?: string;
  best_pdb?: string;
}

export interface DockingState {
  status: 'idle' | 'running' | 'complete' | 'error';
  progress: number;
  logs: string[];
  mode?: DockingMode;

  // Sequential mode fields
  currentStep?: number;
  totalSteps?: number;
  stepPhase?: string;
  steps?: SequentialStep[];

  // Optional fields populated after docking
  bestScore?: number;
  bestModel?: string;
  bestPdbPath?: string;
  allModels?: DockingModel[];
}


export interface OutputFile {
  name: string;
  path: string;
  size?: string;
  type: 'pdb' | 'log' | 'image' | 'config';
}

export interface DockingResults {
  bestScore: number;
  bestModel: string;
  pdbPath: string;
  imagePath?: string;
  outputFiles: OutputFile[];
}

export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}
