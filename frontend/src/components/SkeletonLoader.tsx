import { Skeleton } from '@/components/ui/skeleton';

export function TableSkeleton() {
  return (
    <div className="space-y-3 animate-fade-in">
      <div className="flex gap-3">
        <Skeleton className="h-10 flex-1 shimmer" />
        <Skeleton className="h-10 w-32 shimmer" />
      </div>
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-4" style={{ animationDelay: `${i * 50}ms` }}>
            <Skeleton className="h-12 flex-1 shimmer" />
            <Skeleton className="h-12 w-24 shimmer" />
            <Skeleton className="h-12 w-32 shimmer" />
            <Skeleton className="h-12 w-24 shimmer" />
            <Skeleton className="h-12 w-32 shimmer" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="panel-card animate-fade-in">
      <div className="panel-header">
        <Skeleton className="h-6 w-32 shimmer" />
        <Skeleton className="h-6 w-16 shimmer" />
      </div>
      <div className="p-4 space-y-4">
        <Skeleton className="h-10 w-full shimmer" />
        <Skeleton className="h-24 w-full shimmer" />
        <div className="flex gap-2">
          <Skeleton className="h-10 flex-1 shimmer" />
          <Skeleton className="h-10 w-32 shimmer" />
        </div>
      </div>
    </div>
  );
}

export function ProgressSkeleton() {
  return (
    <div className="space-y-4 p-4 bg-primary/5 rounded-xl border border-primary/20 animate-fade-in">
      <div className="flex justify-between items-center">
        <Skeleton className="h-5 w-40 shimmer" />
        <Skeleton className="h-6 w-16 shimmer" />
      </div>
      <Skeleton className="h-4 w-full rounded-full shimmer" />
      <div className="flex justify-between">
        <Skeleton className="h-4 w-32 shimmer" />
        <Skeleton className="h-4 w-24 shimmer" />
      </div>
    </div>
  );
}

export function ResultsSkeleton() {
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="panel-card">
        <div className="panel-header">
          <Skeleton className="h-6 w-48 shimmer" />
        </div>
        <div className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-24 w-full shimmer" />
            <Skeleton className="h-24 w-full shimmer" />
          </div>
          <Skeleton className="h-12 w-full shimmer" />
        </div>
      </div>
      <CardSkeleton />
    </div>
  );
}
