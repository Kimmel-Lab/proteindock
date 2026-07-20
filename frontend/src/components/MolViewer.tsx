import { useEffect, useRef, useState, useCallback } from 'react';
import { fetchPdbContent } from '@/services/api';
import { Loader2, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

// 3Dmol.js loaded via local script in index.html — BSD-3-Clause
declare global {
  interface Window {
    $3Dmol: any;
  }
}

interface MolViewerProps {
  pdbPath: string | null;
  label?: string;
  height?: number;
}

/**
 * Initialize a 3Dmol.js viewer on a fresh DOM element.
 * Returns the viewer instance or null on failure.
 */
const VALID_PDB_RE =
  /^(HEADER|OBSLTE|TITLE|COMPND|SOURCE|KEYWDS|EXPDTA|NUMMDL|AUTHOR|REVDAT|JRNL|REMARK|DBREF|SEQRES|MODRES|HET |HETNAM|HETSYN|FORMUL|HELIX|SHEET|SSBOND|LINK|SITE|ATOM|ANISOU|TER|HETATM|CONECT|MODEL|ENDMDL|MASTER|END)/;

function cleanPdbForViewer(pdb: string): string {
  const lines = pdb.split('\n').filter((l) => VALID_PDB_RE.test(l));
  if (!lines.some((l) => l.startsWith('END'))) lines.push('END');
  return lines.join('\n');
}

function initViewer(container: HTMLElement, pdbText: string, h: number): any {
  // Wipe any previous content
  container.innerHTML = '';

  // Create a dedicated inner div with explicit pixel dimensions
  // (3Dmol needs non-zero width/height on the element it attaches to)
  const inner = document.createElement('div');
  inner.style.width = container.clientWidth + 'px';
  inner.style.height = h + 'px';
  inner.style.position = 'relative';
  container.appendChild(inner);

  const viewer = window.$3Dmol.createViewer(inner, {
    backgroundColor: '0x1a1a2e',
    antialias: true,
  });

  // Clean Rosetta PDB output for 3Dmol (strip energy table + crystal records)
  const cleanPdb = cleanPdbForViewer(pdbText);

  viewer.addModel(cleanPdb, 'pdb', { doAssembly: false });
  viewer.setStyle({ chain: 'A' }, { cartoon: { color: '0x2dd4bf' } });
  viewer.setStyle({ chain: 'B' }, { cartoon: { color: '0xfb923c' } });
  viewer.zoomTo();
  viewer.render();

  return viewer;
}

export function MolViewer({ pdbPath, label, height = 420 }: MolViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pdbPath || !containerRef.current) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    // Destroy old viewer
    viewerRef.current = null;
    if (containerRef.current) containerRef.current.innerHTML = '';

    fetchPdbContent(pdbPath)
      .then((pdbText) => {
        if (cancelled || !containerRef.current) return;

        if (!window.$3Dmol) {
          throw new Error('3Dmol.js not loaded');
        }
        if (!pdbText || !pdbText.includes('ATOM')) {
          throw new Error('Invalid PDB data received');
        }

        // Delay viewer creation to next frame so the container is fully laid out
        requestAnimationFrame(() => {
          if (cancelled || !containerRef.current) return;
          try {
            viewerRef.current = initViewer(containerRef.current, pdbText, height);
          } catch (e: any) {
            console.error('3Dmol init error:', e);
            setError(e.message || 'Viewer initialization failed');
          } finally {
            setLoading(false);
          }
        });
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e.message || 'Failed to load PDB');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
      viewerRef.current = null;
    };
  }, [pdbPath, height]);

  const handleReset = useCallback(() => {
    if (viewerRef.current) {
      viewerRef.current.zoomTo();
      viewerRef.current.render();
    }
  }, []);

  if (!pdbPath) {
    return (
      <div
        className="flex items-center justify-center rounded-xl border border-dashed border-border bg-muted/30"
        style={{ height }}
      >
        <p className="text-sm text-muted-foreground">Select a model to view its 3D structure</p>
      </div>
    );
  }

  return (
    <div className="relative rounded-xl overflow-hidden border border-border shadow-layered">
      {label && (
        <div className="absolute top-2 left-2 z-10 bg-black/60 text-white text-xs px-2 py-1 rounded font-mono">
          {label}
        </div>
      )}
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <Button size="icon" variant="ghost" className="h-7 w-7 bg-black/40 text-white hover:bg-black/60" onClick={handleReset}>
          <RotateCcw className="w-3.5 h-3.5" />
        </Button>
      </div>
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/60 z-20">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80 z-20 p-4">
          <p className="text-sm text-destructive text-center">{error}</p>
        </div>
      )}
      <div ref={containerRef} style={{ width: '100%', height, position: 'relative' }} />
    </div>
  );
}
