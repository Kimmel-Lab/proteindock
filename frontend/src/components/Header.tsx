import { Atom, FolderOpen, Settings, Plus, RotateCcw, ArrowLeft, ChevronDown, Check, Loader2 } from 'lucide-react';
import { BASE } from '@/services/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Link } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { ThemeToggle } from '@/components/ThemeToggle';

interface HeaderProps {
  workingDir: string;
  onWorkingDirChange: (path: string) => void;
  projectName: string;
  onProjectNameChange: (name: string) => void;
  nstruct: number;
  onNstructChange: (n: number) => void;
  onNewProject: () => void;
  onProjectSelect?: (name: string) => void;
  showBackButton?: boolean;
  backButtonLabel?: string;
}

interface ProjectInfo {
  name: string;
  has_results: boolean;
  has_complex: boolean;
  created: number;
}

export function Header({
  workingDir,
  onWorkingDirChange,
  projectName,
  onProjectNameChange,
  nstruct,
  onNstructChange,
  onNewProject,
  onProjectSelect,
  showBackButton = false,
  backButtonLabel = 'Back to Dashboard',
}: HeaderProps) {
  const [tempDir, setTempDir] = useState(workingDir);
  const [tempProject, setTempProject] = useState(projectName);
  const [tempNstruct, setTempNstruct] = useState(nstruct);
  const [open, setOpen] = useState(false);

  // Project browser state
  const [projectsOpen, setProjectsOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);

  // Fetch projects when popover opens
  useEffect(() => {
    if (!projectsOpen) return;
    setLoadingProjects(true);
    fetch(`${BASE}/projects`)
      .then(r => r.json())
      .then(data => setProjects(data.projects || []))
      .catch(() => setProjects([]))
      .finally(() => setLoadingProjects(false));
  }, [projectsOpen]);

  const handleSave = () => {
    onWorkingDirChange(tempDir);
    onProjectNameChange(tempProject);
    onNstructChange(tempNstruct);
    setOpen(false);
  };

  return (
    <header className="relative bg-gradient-scarlet border-b-4 border-black/20 px-6 py-5 shadow-layered-lg overflow-hidden">
      {/* Subtle animated background pattern */}
      <div className="absolute inset-0 opacity-10">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_50%,rgba(255,255,255,0.1)_1px,transparent_1px)] bg-[length:20px_20px]" />
      </div>
      
      <div className="relative max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-xl bg-white/15 backdrop-blur-md flex items-center justify-center border-2 border-white/30 shadow-glow-primary hover:scale-110 transition-smooth">
            <Atom className="w-8 h-8 text-white drop-shadow-lg" />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-white tracking-wider drop-shadow-md" style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}>
              ProteinWeb Lab Suite
            </h1>
            <Popover open={projectsOpen} onOpenChange={setProjectsOpen}>
              <PopoverTrigger asChild>
                <button className="flex items-center gap-1.5 text-xs text-white/80 font-medium tracking-wide mt-1 hover:text-white transition-colors group">
                  Project: <span className="font-mono text-white bg-black/30 px-2.5 py-1 rounded-md border border-white/20 shadow-layered max-w-[140px] sm:max-w-none truncate inline-block align-middle group-hover:border-white/40">{projectName}</span>
                  <ChevronDown className="w-3 h-3 text-white/60 group-hover:text-white" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-72 p-0" align="start">
                <div className="p-3 border-b">
                  <p className="text-sm font-semibold">Switch Project</p>
                  <p className="text-xs text-muted-foreground">Select an existing project to load</p>
                </div>
                <div className="max-h-64 overflow-y-auto">
                  {loadingProjects ? (
                    <div className="p-4 text-center">
                      <Loader2 className="w-4 h-4 animate-spin mx-auto text-muted-foreground" />
                    </div>
                  ) : projects.length === 0 ? (
                    <div className="p-4 text-center text-xs text-muted-foreground">
                      No projects yet
                    </div>
                  ) : (
                    projects.map((p) => (
                      <button
                        key={p.name}
                        className={`w-full text-left px-3 py-2 text-sm hover:bg-muted flex items-center gap-2 border-b border-border/30 last:border-0 ${
                          p.name === projectName ? 'bg-primary/10' : ''
                        }`}
                        onClick={() => {
                          if (p.name !== projectName && onProjectSelect) {
                            onProjectSelect(p.name);
                          }
                          setProjectsOpen(false);
                        }}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="font-mono text-xs truncate">{p.name}</div>
                          <div className="flex items-center gap-2 mt-0.5">
                            {p.has_results && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-success/15 text-success border border-success/30 font-semibold">
                                Results
                              </span>
                            )}
                            {p.has_complex && !p.has_results && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-warning/15 text-warning border border-warning/30 font-semibold">
                                Ready to dock
                              </span>
                            )}
                            {!p.has_complex && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground border font-semibold">
                                In progress
                              </span>
                            )}
                          </div>
                        </div>
                        {p.name === projectName && (
                          <Check className="w-4 h-4 text-primary flex-shrink-0" />
                        )}
                      </button>
                    ))
                  )}
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Theme Toggle */}
          <ThemeToggle variant="header" />
          
          {/* Back Button */}
          {showBackButton && (
            <Link to="/">
              <Button 
                variant="ghost" 
                size="sm" 
                className="gap-2 bg-white/10 hover:bg-white/25 text-white border border-white/30 hover:border-white/50 backdrop-blur-sm transition-smooth hover:scale-105 shadow-layered"
              >
                <ArrowLeft className="w-4 h-4" />
                <span className="hidden sm:inline">{backButtonLabel}</span>
              </Button>
            </Link>
          )}
          
          {/* New Project Button */}
          <Button 
            variant="ghost" 
            size="sm" 
            className="gap-2 bg-white text-primary hover:bg-white/95 font-bold shadow-layered-lg hover:shadow-glow-primary transition-smooth hover:scale-105"
            onClick={onNewProject}
          >
            <Plus className="w-4 h-4" />
            <span className="hidden sm:inline">New Project</span>
          </Button>

          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-2 bg-white/10 hover:bg-white/25 text-white border border-white/30 hover:border-white/50 backdrop-blur-sm transition-smooth hover:scale-105 shadow-layered">
                <Settings className="w-4 h-4" />
                <span className="hidden sm:inline">Settings</span>
              </Button>
            </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Project Settings</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 pt-4">
              <div className="space-y-2">
                <Label htmlFor="project-name">Project Name</Label>
                <Input
                  id="project-name"
                  value={tempProject}
                  onChange={(e) => setTempProject(e.target.value.replace(/[^a-zA-Z0-9_-]/g, '_'))}
                  placeholder="my_project"
                  className="font-mono text-sm"
                />
                <p className="text-xs text-muted-foreground">
                  Each project gets its own folder. Use only letters, numbers, underscores, and hyphens.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="nstruct">Docking Structures (nstruct)</Label>
                <Input
                  id="nstruct"
                  type="number"
                  min={1}
                  max={1000}
                  value={tempNstruct}
                  onChange={(e) => setTempNstruct(Math.max(1, parseInt(e.target.value) || 1))}
                  className="font-mono text-sm"
                />
                <p className="text-xs text-muted-foreground">
                  Number of docking models to generate. More = better sampling but slower. (1-1000)
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="workdir">Working Directory (display only)</Label>
                <Input
                  id="workdir"
                  value={tempDir}
                  onChange={(e) => setTempDir(e.target.value)}
                  placeholder="/path/to/working/directory"
                  className="font-mono text-sm"
                  disabled
                />
                <p className="text-xs text-muted-foreground">
                  Base directory is configured on the backend.
                </p>
              </div>

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button onClick={handleSave}>Save</Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
        </div>
      </div>
    </header>
  );
}
