import { useState, useCallback } from 'react';
import { Upload, Download, Dna, Check, Loader2, AlertCircle, Plus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import type { ComponentInput } from '@/types/docking';

interface StructureInputPanelProps {
  components: ComponentInput[];
  onComponentChange: (id: string, update: Partial<ComponentInput>) => void;
  onAddComponent: () => void;
  onRemoveComponent: (id: string) => void;
  onFetch: (componentId: string, pdbCode: string) => void;
  onUpload: (componentId: string, file: File) => void;
  onPredict: (componentId: string, sequence: string) => void;
}

function StatusBadge({ status }: { status: ComponentInput['status'] }) {
  if (status === 'ready') {
    return (
      <Badge variant="outline" className="status-badge ready">
        <Check className="w-3 h-3" />
        Ready
      </Badge>
    );
  }
  if (status === 'loading') {
    return (
      <Badge variant="outline" className="status-badge pending">
        <Loader2 className="w-3 h-3 animate-spin" />
        Loading
      </Badge>
    );
  }
  if (status === 'error') {
    return (
      <Badge variant="outline" className="status-badge error">
        <AlertCircle className="w-3 h-3" />
        Error
      </Badge>
    );
  }
  return null;
}

interface StructureCardProps {
  component: ComponentInput;
  canRemove: boolean;
  onComponentChange: (id: string, update: Partial<ComponentInput>) => void;
  onRemove: () => void;
  onFetch: (componentId: string, pdbCode: string) => void;
  onUpload: (componentId: string, file: File) => void;
  onPredict: (componentId: string, sequence: string) => void;
}

function StructureCard({
  component,
  canRemove,
  onComponentChange,
  onRemove,
  onFetch,
  onUpload,
  onPredict,
}: StructureCardProps) {
  const [pdbCode, setPdbCode] = useState('');
  const [sequence, setSequence] = useState('');
  const [isDragging, setIsDragging] = useState(false);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith('.pdb')) {
      onUpload(component.id, file);
    }
  }, [component.id, onUpload]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onUpload(component.id, file);
    }
  };

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-primary text-primary-foreground text-xs font-bold">
            {component.chainId}
          </span>
          <span className="capitalize">{component.label}</span>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={component.status} />
          {canRemove && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
              onClick={onRemove}
            >
              <X className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </div>
      <div className="p-4">
        <Tabs defaultValue="fetch" className="w-full">
          <TabsList className="grid w-full grid-cols-3 mb-4">
            <TabsTrigger value="fetch" className="text-xs">
              <Download className="w-3 h-3 mr-1" />
              Fetch PDB
            </TabsTrigger>
            <TabsTrigger value="upload" className="text-xs">
              <Upload className="w-3 h-3 mr-1" />
              Upload
            </TabsTrigger>
            <TabsTrigger value="predict" className="text-xs">
              <Dna className="w-3 h-3 mr-1" />
              Predict
            </TabsTrigger>
          </TabsList>

          <TabsContent value="fetch" className="space-y-3">
            <div className="flex gap-2">
              <Input
                placeholder="e.g., 1ABC"
                value={pdbCode}
                onChange={(e) => setPdbCode(e.target.value.toUpperCase())}
                className="font-mono uppercase"
                maxLength={4}
              />
              <Button
                onClick={() => onFetch(component.id, pdbCode)}
                disabled={pdbCode.length !== 4}
                variant="scientific"
              >
                Fetch
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Enter a 4-character PDB code to fetch from RCSB
            </p>
          </TabsContent>

          <TabsContent value="upload" className="space-y-3">
            <div
              className={`file-drop-zone ${isDragging ? 'active' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              onClick={() => document.getElementById(`file-${component.id}`)?.click()}
            >
              <Upload className="w-8 h-8 mx-auto mb-2 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Drop PDB file here or click to browse
              </p>
              <input
                id={`file-${component.id}`}
                type="file"
                accept=".pdb"
                className="hidden"
                onChange={handleFileSelect}
              />
            </div>
            {component.file && (
              <p className="text-xs text-muted-foreground text-center">
                Selected: <span className="font-mono">{component.file.name}</span>
              </p>
            )}
          </TabsContent>

          <TabsContent value="predict" className="space-y-3">
            <Textarea
              placeholder="Paste amino acid sequence (single letter codes)..."
              value={sequence}
              onChange={(e) => setSequence(e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))}
              className="font-mono text-xs h-24 resize-none"
            />
            <Button
              onClick={() => onPredict(component.id, sequence)}
              disabled={sequence.length < 10}
              variant="scientific"
              className="w-full"
            >
              <Dna className="w-4 h-4 mr-2" />
              Run ColabFold Prediction
            </Button>
            <p className="text-xs text-muted-foreground">
              Uses ColabFold to predict structure from sequence (GPU required)
            </p>
          </TabsContent>
        </Tabs>

        {component.filePath && (
          <div className="mt-4 p-2 bg-muted rounded-md">
            <p className="text-xs text-muted-foreground">File path:</p>
            <p className="text-xs font-mono truncate">{component.filePath}</p>
          </div>
        )}

        {component.error && (
          <div className="mt-4 p-2 bg-destructive/10 rounded-md">
            <p className="text-xs text-destructive">{component.error}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export function StructureInputPanel({
  components,
  onComponentChange,
  onAddComponent,
  onRemoveComponent,
  onFetch,
  onUpload,
  onPredict,
}: StructureInputPanelProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-6 h-6 rounded-full bg-primary flex items-center justify-center text-xs font-bold text-primary-foreground">
          1
        </div>
        <h2 className="font-semibold">Input Structures</h2>
        <span className="text-xs text-muted-foreground ml-auto">
          {components.length} components
        </span>
      </div>

      {components.map((comp) => (
        <StructureCard
          key={comp.id}
          component={comp}
          canRemove={components.length > 2}
          onComponentChange={onComponentChange}
          onRemove={() => onRemoveComponent(comp.id)}
          onFetch={onFetch}
          onUpload={onUpload}
          onPredict={onPredict}
        />
      ))}

      {components.length < 26 && (
        <Button
          variant="outline"
          className="w-full border-dashed border-2 hover:border-primary/50"
          onClick={onAddComponent}
        >
          <Plus className="w-4 h-4 mr-2" />
          Add Component
        </Button>
      )}
    </div>
  );
}
