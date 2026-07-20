import { Link } from 'react-router-dom';
import {
  Dna,
  Atom,
  FlaskConical,
  TestTube,
  Zap,
  ArrowRight,
  Beaker,
  Activity,
  Server,
  Sparkles,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSettings } from '@/components/BackendSettings';

interface ModuleCardProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  href: string;
  status: 'available' | 'coming-soon';
  color?: string;
}

// Animated molecule visual (CSS-only)
function MoleculeAnimation() {
  return (
    <div className="relative w-56 h-56 lg:w-64 lg:h-64 mx-auto">
      {/* Central nucleus */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-14 h-14 rounded-full bg-gradient-scarlet shadow-glow-primary" />

      {/* Orbit ring 1 */}
      <div
        className="absolute inset-0 rounded-full border-2 border-primary/20"
        style={{ animation: 'spin 8s linear infinite' }}
      >
        <div className="absolute -top-2 left-1/2 -translate-x-1/2 w-4 h-4 rounded-full bg-primary shadow-glow-primary" />
      </div>

      {/* Orbit ring 2 */}
      <div
        className="absolute inset-6 rounded-full border-2 border-primary/15"
        style={{ animation: 'spin 12s linear infinite reverse' }}
      >
        <div className="absolute -top-2 left-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-success shadow-glow-success" />
      </div>

      {/* Orbit ring 3 */}
      <div
        className="absolute inset-12 rounded-full border-2 border-primary/10"
        style={{ animation: 'spin 6s linear infinite' }}
      >
        <div className="absolute -bottom-1.5 left-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-warning" />
      </div>

    </div>
  );
}

function ModuleCard({ title, description, icon, href, status, color = 'primary' }: ModuleCardProps) {
  const isAvailable = status === 'available';

  const colorClasses: Record<string, { bg: string; text: string; border: string }> = {
    primary: { bg: 'bg-primary/10', text: 'text-primary', border: 'hover:border-primary' },
    accent: { bg: 'bg-accent/10', text: 'text-accent', border: 'hover:border-accent' },
    secondary: { bg: 'bg-secondary/10', text: 'text-secondary-foreground', border: 'hover:border-secondary' },
    success: { bg: 'bg-success/10', text: 'text-success', border: 'hover:border-success' },
    warning: { bg: 'bg-warning/10', text: 'text-warning', border: 'hover:border-warning' },
  };

  const colors = colorClasses[color] || colorClasses.primary;

  if (isAvailable) {
    return (
      <Link to={href} className="block">
        <Card className={`
          h-full glass hover-lift cursor-pointer
          border-2 border-border/50 hover:border-primary/50
          ${colors.border} shadow-layered hover:shadow-glow-primary
          bg-gradient-card
        `}>
          <CardHeader>
            <div className="flex items-start justify-between">
              <div className={`
                p-4 rounded-xl ${colors.bg} ${colors.text}
                shadow-layered transition-smooth hover:scale-110
              `}>
                {icon}
              </div>
            </div>
            <CardTitle className="mt-4 text-xl font-bold" style={{ fontFamily: 'Oswald, sans-serif' }}>
              {title}
            </CardTitle>
            <CardDescription className="text-sm mt-2 leading-relaxed">
              {description}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full bg-gradient-scarlet hover:shadow-glow-primary transition-smooth hover:scale-105"
              style={{ fontFamily: 'Oswald, sans-serif' }}
            >
              Launch Tool
              <ArrowRight className="ml-2 w-4 h-4" />
            </Button>
          </CardContent>
        </Card>
      </Link>
    );
  }

  return (
    <div>
      <Card className="h-full opacity-70 cursor-not-allowed glass border-2 border-border/30">
        <CardHeader>
          <div className="flex items-start justify-between">
            <div className={`p-4 rounded-xl ${colors.bg} ${colors.text} opacity-60`}>
              {icon}
            </div>
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground bg-muted/80 px-3 py-1.5 rounded-full border border-border/50">
              Coming Soon
            </span>
          </div>
          <CardTitle className="mt-4 text-xl font-bold opacity-80" style={{ fontFamily: 'Oswald, sans-serif' }}>
            {title}
          </CardTitle>
          <CardDescription className="text-sm mt-2 leading-relaxed opacity-70">
            {description}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" className="w-full cursor-not-allowed opacity-50" disabled>
            Coming Soon
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

export default function Dashboard() {
  const modules = [
    {
      title: 'Protein Docking',
      description: 'Perform protein-protein docking using Rosetta with real-time progress tracking and comprehensive results analysis.',
      icon: <Dna className="w-6 h-6" />,
      href: '/docking',
      status: 'available' as const,
      color: 'primary',
    },
    {
      title: 'Alanine Scanning',
      description: 'Systematically mutate residues to alanine to identify critical positions for protein function and binding.',
      icon: <TestTube className="w-6 h-6" />,
      href: '/alanine-scanning',
      status: 'available' as const,
      color: 'accent',
    },
    {
      title: 'ncAA Optimization',
      description: 'Bayesian optimization over non-canonical amino acid mutations to intelligently improve protein binding.',
      icon: <Atom className="w-6 h-6" />,
      href: '/ncaa-optimize',
      status: 'available' as const,
      color: 'secondary',
    },
    {
      title: 'DockQ Benchmark',
      description: 'Validate docking accuracy against known co-crystal structures using DockQ scoring. Generate quantitative benchmarks for publication.',
      icon: <FlaskConical className="w-6 h-6" />,
      href: '/benchmark',
      status: 'available' as const,
      color: 'success',
    },
    {
      title: 'ProteinMPNN Redesign',
      description: 'Redesign binder interface residues using ProteinMPNN. Generate diverse sequences optimized for the docked backbone geometry.',
      icon: <Sparkles className="w-6 h-6" />,
      href: '/mpnn-design',
      status: 'available' as const,
      color: 'warning',
    },
    {
      title: 'Structure Analysis',
      description: 'Analyze protein structures, interfaces, and interactions with advanced visualization tools.',
      icon: <Activity className="w-6 h-6" />,
      href: '/structure-analysis',
      status: 'coming-soon' as const,
      color: 'primary',
    },
  ];

  return (
    <div className="min-h-screen bg-background relative overflow-hidden">
      {/* Animated background elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary/5 rounded-full blur-3xl animate-pulse" />
        <div className="absolute top-1/2 -left-40 w-96 h-96 bg-primary/3 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '1s' }} />
        <div className="absolute -bottom-40 right-1/4 w-72 h-72 bg-primary/5 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '2s' }} />
      </div>

      {/* Header */}
      <header className="relative border-b glass-strong bg-gradient-to-r from-primary/5 via-card to-primary/5">
        <div className="container mx-auto px-4 py-8">
          <div className="flex items-center justify-between">
            <div className="animate-slide-in">
              <h1
                className="text-4xl font-extrabold text-foreground mb-2"
                style={{ fontFamily: 'Oswald, sans-serif' }}
              >
                ProteinWeb Lab Suite
              </h1>
              <p className="text-muted-foreground text-base font-medium">
                Computational Biology Tools for Protein Analysis
              </p>
            </div>
            <div className="flex items-center gap-3 animate-scale-in">
              <BackendSettings />
              <ThemeToggle />
              <div className="p-3 rounded-xl bg-primary/10 text-primary shadow-layered">
                <Beaker className="w-8 h-8" />
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="relative container mx-auto px-4 py-12">
        {/* Hero Section — split layout */}
        <div className="mb-16 flex flex-col lg:flex-row items-center gap-12 animate-fade-in">
          <div className="flex-1 text-center lg:text-left">
            <h2
              className="text-5xl font-extrabold mb-6 text-gradient-scarlet"
              style={{ fontFamily: 'Oswald, sans-serif' }}
            >
              Welcome to ProteinWeb
            </h2>
            <div className="w-24 h-1 bg-gradient-scarlet mx-auto lg:mx-0 mb-6 rounded-full" />
            <p className="text-lg text-muted-foreground max-w-xl leading-relaxed">
              A comprehensive suite of computational tools for protein structure
              analysis, docking, and design. Select a module below to get started.
            </p>
            <div className="mt-8 flex gap-4 justify-center lg:justify-start">
              <Link to="/docking">
                <Button
                  className="bg-gradient-scarlet hover:shadow-glow-primary transition-smooth hover:scale-105 text-lg px-8 py-3 h-auto"
                  style={{ fontFamily: 'Oswald, sans-serif' }}
                >
                  <Dna className="w-5 h-5 mr-2" />
                  Start Docking
                </Button>
              </Link>
            </div>
          </div>
          <div className="flex-shrink-0">
            <MoleculeAnimation />
          </div>
        </div>

        {/* Stats Bar */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-12">
          {[
            { label: 'Active Module', value: 'Docking', icon: <Dna className="w-5 h-5" /> },
            { label: 'Compute Backend', value: 'SLURM HPC', icon: <Server className="w-5 h-5" /> },
            { label: 'Scoring Engine', value: 'Rosetta REF15', icon: <Activity className="w-5 h-5" /> },
            { label: 'Coming Soon', value: '3 Modules', icon: <FlaskConical className="w-5 h-5" /> },
          ].map((stat, i) => (
            <Card key={i} className="glass text-center p-4 hover-lift shadow-layered border-border/50">
              <div className="flex flex-col items-center gap-2">
                <div className="p-2 rounded-lg bg-primary/10 text-primary">{stat.icon}</div>
                <p className="text-2xl font-bold" style={{ fontFamily: 'Oswald, sans-serif' }}>{stat.value}</p>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">{stat.label}</p>
              </div>
            </Card>
          ))}
        </div>

        {/* Modules Grid — staggered animation */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
          {modules.map((module, index) => (
            <div key={module.href} className="animate-fade-in" style={{ animationDelay: `${index * 100}ms` }}>
              <ModuleCard {...module} />
            </div>
          ))}
        </div>

        {/* Info Section */}
        <div className="mt-20 grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card className="glass hover-lift shadow-layered border-border/50">
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-primary/10 text-primary">
                  <Zap className="w-5 h-5" />
                </div>
                <span className="font-bold">Fast & Efficient</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Real-time progress tracking and optimized workflows for rapid results.
              </p>
            </CardContent>
          </Card>

          <Card className="glass hover-lift shadow-layered border-border/50">
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-primary/10 text-primary">
                  <Activity className="w-5 h-5" />
                </div>
                <span className="font-bold">Comprehensive Analysis</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Detailed results tables, scoring metrics, and visualization tools for in-depth analysis.
              </p>
            </CardContent>
          </Card>

          <Card className="glass hover-lift shadow-layered border-border/50">
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-primary/10 text-primary">
                  <Beaker className="w-5 h-5" />
                </div>
                <span className="font-bold">Research-Grade</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Built on Rosetta and industry-standard tools for reliable, publication-ready results.
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Footer */}
        <footer className="mt-16 text-center text-sm text-muted-foreground">
          <p>Powered by <span className="font-bold text-primary">Rosetta</span></p>
        </footer>
      </main>
    </div>
  );
}
