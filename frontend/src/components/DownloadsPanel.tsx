import { Download, FileText, Image, Code, Database } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { OutputFile } from '@/types/docking';

interface DownloadsPanelProps {
  files: OutputFile[];
  onDownload: (file: OutputFile) => void;
}

function getFileIcon(type: OutputFile['type']) {
  switch (type) {
    case 'pdb':
      return <Database className="w-4 h-4 text-primary" />;
    case 'log':
      return <FileText className="w-4 h-4 text-muted-foreground" />;
    case 'image':
      return <Image className="w-4 h-4 text-accent" />;
    case 'config':
      return <Code className="w-4 h-4 text-warning" />;
    default:
      return <FileText className="w-4 h-4" />;
  }
}

function getFileTypeLabel(type: OutputFile['type']) {
  switch (type) {
    case 'pdb':
      return 'Structure';
    case 'log':
      return 'Log';
    case 'image':
      return 'Image';
    case 'config':
      return 'Config';
    default:
      return 'File';
  }
}

export function DownloadsPanel({ files, onDownload }: DownloadsPanelProps) {
  if (files.length === 0) {
    return null;
  }

  return (
    <div className="panel-card">
      <div className="panel-header">
        <Download className="w-4 h-4" />
        <span>Output Files</span>
        <span className="text-xs text-muted-foreground ml-auto">
          {files.length} files available
        </span>
      </div>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-12"></TableHead>
              <TableHead>Filename</TableHead>
              <TableHead className="w-24">Type</TableHead>
              <TableHead className="w-20">Size</TableHead>
              <TableHead className="w-24 text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {files.map((file, index) => (
              <TableRow key={index}>
                <TableCell>{getFileIcon(file.type)}</TableCell>
                <TableCell className="font-mono text-sm">{file.name}</TableCell>
                <TableCell>
                  <span className="text-xs px-2 py-1 rounded-full bg-muted">
                    {getFileTypeLabel(file.type)}
                  </span>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {file.size || '—'}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onDownload(file)}
                  >
                    <Download className="w-4 h-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
