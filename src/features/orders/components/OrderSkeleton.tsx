import { Skeleton } from '../../../components/ui/Skeleton';
import { PageContainer } from '../../../components/ui/LayoutHelpers';

export const OrdersListSkeleton = () => (
  <PageContainer data-testid="orders-list-skeleton">
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-5 border-b border-border">
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-72" />
      </div>
      <Skeleton className="h-10 w-36" />
    </div>

    <div className="h-16 w-full bg-card border border-border/80 rounded-lg p-3 flex items-center gap-3">
      <Skeleton className="h-9 w-64" />
      <Skeleton className="h-9 w-32" />
      <Skeleton className="h-9 w-32" />
      <Skeleton className="h-9 w-32" />
    </div>

    <div className="border border-border rounded-lg overflow-hidden">
      <div className="h-12 w-full bg-muted/50" />
      {Array.from({ length: 6 }).map((_, idx) => (
        <div key={idx} className="flex items-center gap-4 p-4 border-t border-border">
          {Array.from({ length: 7 }).map((__, cellIdx) => (
            <Skeleton key={cellIdx} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  </PageContainer>
);

export const OrderDetailsSkeleton = () => (
  <PageContainer data-testid="order-details-skeleton">
    <div className="space-y-2 pb-5 border-b border-border">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-40" />
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-6">
        <div className="border rounded-lg p-6 bg-card space-y-4">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-24 w-full" />
        </div>
        <div className="border rounded-lg p-6 bg-card space-y-4">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-40 w-full" />
        </div>
      </div>
      <div className="space-y-6">
        <div className="border rounded-lg p-6 bg-card space-y-4 h-56">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    </div>
  </PageContainer>
);

export const OrderFormSkeleton = () => (
  <PageContainer data-testid="order-form-skeleton">
    <div className="space-y-2 pb-5 border-b border-border">
      <Skeleton className="h-8 w-56" />
    </div>
    <div className="border rounded-lg p-6 bg-card space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {Array.from({ length: 6 }).map((_, idx) => (
          <Skeleton key={idx} className="h-10 w-full" />
        ))}
      </div>
      <Skeleton className="h-24 w-full" />
    </div>
  </PageContainer>
);
