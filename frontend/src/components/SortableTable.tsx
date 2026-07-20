import { useState, useMemo } from 'react';
import { ArrowUpDown, ArrowUp, ArrowDown, Download, Search, X } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import type { DockingModel } from '@/types/docking';

type SortField = 'score' | 'rms' | 'CAPRI_rank' | 'Fnat' | 'I_sc' | 'Irms' | 'index';
type SortDirection = 'asc' | 'desc';

interface SortableTableProps {
  models: DockingModel[];
  bestModelDesc?: string;
  onExport?: () => void;
}

export function SortableTable({ models, bestModelDesc, onExport }: SortableTableProps) {
  const [sortField, setSortField] = useState<SortField>('score');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [searchTerm, setSearchTerm] = useState('');

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const filteredAndSortedModels = useMemo(() => {
    let filtered = models;

    // Search filter
    if (searchTerm) {
      filtered = models.filter(model =>
        model.desc?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        model.score.toString().includes(searchTerm) ||
        model.index?.toString().includes(searchTerm)
      );
    }

    // Sort
    const sorted = [...filtered].sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];

      if (aVal === undefined || aVal === null) return 1;
      if (bVal === undefined || bVal === null) return -1;

      const comparison = (aVal as number) - (bVal as number);
      return sortDirection === 'asc' ? comparison : -comparison;
    });

    return sorted;
  }, [models, sortField, sortDirection, searchTerm]);

  const handleExportCSV = () => {
    const headers = ['Rank', 'Model', 'Score', 'RMS', 'CAPRI Rank', 'Fnat', 'I_sc', 'Irms'];
    const rows = filteredAndSortedModels.map((model, idx) => [
      (idx + 1).toString(),
      model.desc || '',
      model.score.toFixed(2),
      model.rms?.toFixed(2) || '-',
      model.CAPRI_rank?.toFixed(0) || '-',
      model.Fnat?.toFixed(3) || '-',
      model.I_sc?.toFixed(2) || '-',
      model.Irms?.toFixed(2) || '-',
    ]);

    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `docking-results-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);

    if (onExport) {
      onExport();
    }
  };

  const SortButton = ({ field, label }: { field: SortField; label: string }) => {
    const isActive = sortField === field;
    return (
      <Button
        variant="ghost"
        size="sm"
        className="h-auto p-0 font-bold hover:bg-transparent gap-1"
        onClick={() => handleSort(field)}
      >
        {label}
        {isActive ? (
          sortDirection === 'asc' ? (
            <ArrowUp className="w-3 h-3" />
          ) : (
            <ArrowDown className="w-3 h-3" />
          )
        ) : (
          <ArrowUpDown className="w-3 h-3 opacity-50" />
        )}
      </Button>
    );
  };

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search models..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-9"
          />
          {searchTerm && (
            <Button
              variant="ghost"
              size="sm"
              className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 p-0"
              onClick={() => setSearchTerm('')}
            >
              <X className="w-4 h-4" />
            </Button>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleExportCSV}
          className="gap-2"
        >
          <Download className="w-4 h-4" />
          Export CSV
        </Button>
      </div>

      {/* Results count */}
      {searchTerm && (
        <p className="text-sm text-muted-foreground">
          Showing {filteredAndSortedModels.length} of {models.length} models
        </p>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="bg-gradient-to-r from-primary/5 to-transparent border-b-2 border-primary/20">
              <TableHead className="w-16">
                <SortButton field="index" label="Rank" />
              </TableHead>
              <TableHead className="font-mono font-bold">Model</TableHead>
              <TableHead className="text-right">
                <SortButton field="score" label="Total Score" />
              </TableHead>
              <TableHead className="text-right">
                <SortButton field="rms" label="RMS" />
              </TableHead>
              <TableHead className="text-right">
                <SortButton field="CAPRI_rank" label="CAPRI Rank" />
              </TableHead>
              <TableHead className="text-right">
                <SortButton field="Fnat" label="Fnat" />
              </TableHead>
              <TableHead className="text-right">
                <SortButton field="I_sc" label="I_sc" />
              </TableHead>
              <TableHead className="text-right">
                <SortButton field="Irms" label="Irms" />
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredAndSortedModels.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                  No models found matching your search.
                </TableCell>
              </TableRow>
            ) : (
              filteredAndSortedModels.map((model, idx) => {
                const isBest = model.desc === bestModelDesc;
                return (
                  <TableRow
                    key={model.index ?? idx}
                    className={`
                      transition-all duration-200 hover:bg-primary/5 cursor-pointer
                      ${isBest
                        ? 'bg-gradient-to-r from-success/15 via-success/10 to-transparent border-l-4 border-l-success shadow-md'
                        : ''
                      }
                    `}
                  >
                    <TableCell className="font-bold">
                      {idx + 1}
                      {isBest && (
                        <span className="ml-2 text-xs text-success font-semibold">★</span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs font-medium">
                      {model.desc}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono font-extrabold ${
                        isBest ? 'text-success' : 'text-foreground'
                      }`}
                    >
                      {model.score.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {model.rms?.toFixed(2) ?? '-'}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {model.CAPRI_rank?.toFixed(0) ?? '-'}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {model.Fnat?.toFixed(3) ?? '-'}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {model.I_sc?.toFixed(2) ?? '-'}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {model.Irms?.toFixed(2) ?? '-'}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

