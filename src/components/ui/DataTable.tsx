import * as React from 'react';
import { cn } from '../../utils/cn';
import { Checkbox } from './Checkbox';
import { Skeleton } from './Skeleton';
import { EmptyState } from './EmptyState';
import { Pagination } from './Pagination';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

export interface ColumnDef<T> {
  header: React.ReactNode | string;
  accessorKey?: keyof T | string;
  cell?: (value: any, row: T, index: number) => React.ReactNode;
  sortable?: boolean;
  className?: string;
}

export interface DataTableProps<T> {
  columns: ColumnDef<T>[];
  data: T[];
  loading?: boolean;
  pagination?: {
    page: number;
    pageSize: number;
    totalItems: number;
    onPageChange: (page: number) => void;
    onPageSizeChange?: (size: number) => void;
  };
  sorting?: {
    key: string;
    direction: 'asc' | 'desc';
  };
  onSort?: (key: string, direction: 'asc' | 'desc') => void;
  selectedRows?: (string | number)[];
  onSelectionChange?: (selectedIds: (string | number)[]) => void;
  getRowId?: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  emptyComponent?: React.ReactNode;
  stripe?: boolean;
  stickyHeader?: boolean;
  hoverEffect?: boolean;
  className?: string;
}

export function DataTable<T>({
  columns,
  data,
  loading = false,
  pagination,
  sorting,
  onSort,
  selectedRows = [],
  onSelectionChange,
  getRowId,
  onRowClick,
  emptyComponent,
  stripe = false,
  stickyHeader = true,
  hoverEffect = true,
  className,
}: DataTableProps<T>) {
  const [localSort, setLocalSort] = React.useState<{
    key: string;
    direction: 'asc' | 'desc';
  } | null>(null);

  const activeSort = sorting !== undefined ? sorting : localSort;

  const handleSort = (key: string) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (activeSort && activeSort.key === key) {
      direction = activeSort.direction === 'asc' ? 'desc' : 'asc';
    }

    if (onSort) {
      onSort(key, direction);
    } else {
      setLocalSort({ key, direction });
    }
  };

  const getRowIdentifier = React.useCallback(
    (row: T, index: number): string | number => {
      if (getRowId) return getRowId(row);
      return (row as any).id ?? (row as any)._id ?? index;
    },
    [getRowId]
  );

  // Client-side sorting logic
  const sortedData = React.useMemo(() => {
    if (onSort || !activeSort) return data;

    return [...data].sort((a, b) => {
      const aVal = a[activeSort.key as keyof T];
      const bVal = b[activeSort.key as keyof T];

      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      const modifier = activeSort.direction === 'asc' ? 1 : -1;

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return aVal.localeCompare(bVal) * modifier;
      }
      return (aVal < bVal ? -1 : 1) * modifier;
    });
  }, [data, activeSort, onSort]);

  // Selection handlers
  const handleSelectAll = (checked: boolean) => {
    if (!onSelectionChange) return;

    if (checked) {
      const allIds = sortedData.map((row, idx) => getRowIdentifier(row, idx));
      onSelectionChange(allIds);
    } else {
      onSelectionChange([]);
    }
  };

  const handleSelectRow = (checked: boolean, id: string | number) => {
    if (!onSelectionChange) return;

    if (checked) {
      onSelectionChange([...selectedRows, id]);
    } else {
      onSelectionChange(selectedRows.filter((item) => item !== id));
    }
  };

  const rowIds = React.useMemo(
    () => sortedData.map((row, idx) => getRowIdentifier(row, idx)),
    [sortedData, getRowIdentifier]
  );

  const allSelected = React.useMemo(
    () => rowIds.length > 0 && rowIds.every((id) => selectedRows.includes(id)),
    [rowIds, selectedRows]
  );

  const someSelected = React.useMemo(
    () =>
      rowIds.some((id) => selectedRows.includes(id)) && !allSelected,
    [rowIds, selectedRows, allSelected]
  );

  const masterCheckboxRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (masterCheckboxRef.current) {
      masterCheckboxRef.current.indeterminate = someSelected;
    }
  }, [someSelected]);

  const showSelection = !!onSelectionChange;

  return (
    <div className={cn('w-full flex flex-col border border-border rounded-lg bg-card overflow-hidden', className)}>
      <div className="w-full overflow-x-auto relative">
        <table className="w-full border-collapse text-left text-sm">
          <thead
            className={cn(
              'bg-muted/50 dark:bg-zinc-900/50 text-muted-foreground font-semibold',
              stickyHeader && 'sticky top-0 z-10 backdrop-blur-sm'
            )}
            data-testid="table-header"
          >
            <tr>
              {showSelection && (
                <th className="p-4 w-12 border-b border-border">
                  <Checkbox
                    ref={masterCheckboxRef}
                    checked={allSelected}
                    onChange={(e) => handleSelectAll(e.target.checked)}
                    aria-label="Select all rows"
                    data-testid="table-select-all"
                  />
                </th>
              )}
              {columns.map((col, idx) => {
                const isSortable = col.sortable && col.accessorKey;
                const isSorted = activeSort && activeSort.key === col.accessorKey;

                return (
                  <th
                    key={idx}
                    className={cn(
                      'p-4 border-b border-border font-medium select-none',
                      isSortable && 'cursor-pointer hover:text-foreground transition-colors',
                      col.className
                    )}
                    onClick={() => isSortable && handleSort(String(col.accessorKey))}
                    data-testid={`table-th-${String(col.accessorKey || idx)}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span>{col.header}</span>
                      {isSortable && (
                        <span className="text-muted-foreground/60">
                          {isSorted ? (
                            activeSort.direction === 'asc' ? (
                              <ArrowUp className="h-3.5 w-3.5 text-primary" />
                            ) : (
                              <ArrowDown className="h-3.5 w-3.5 text-primary" />
                            )
                          ) : (
                            <ArrowUpDown className="h-3.5 w-3.5" />
                          )}
                        </span>
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>

          <tbody className="divide-y divide-border" data-testid="table-body">
            {loading ? (
              // Skeleton loading state
              Array.from({ length: pagination?.pageSize || 5 }).map((_, rIdx) => (
                <tr key={rIdx} className="bg-background">
                  {showSelection && (
                    <td className="p-4">
                      <Skeleton className="h-4 w-4" />
                    </td>
                  )}
                  {columns.map((_, cIdx) => (
                    <td key={cIdx} className="p-4">
                      <Skeleton className="h-4 w-full max-w-[120px]" />
                    </td>
                  ))}
                </tr>
              ))
            ) : sortedData.length === 0 ? (
              // Empty state
              <tr>
                <td colSpan={columns.length + (showSelection ? 1 : 0)} className="p-8">
                  {emptyComponent || (
                    <EmptyState
                      title="No data found"
                      description="There are no items matching this criteria."
                    />
                  )}
                </td>
              </tr>
            ) : (
              // Data rows
              sortedData.map((row, rIdx) => {
                const id = getRowIdentifier(row, rIdx);
                const isSelected = selectedRows.includes(id);

                return (
                  <tr
                    key={id}
                    className={cn(
                      'transition-colors bg-background',
                      stripe && rIdx % 2 === 1 && 'bg-muted/20 dark:bg-zinc-900/10',
                      hoverEffect && 'hover:bg-muted/40 dark:hover:bg-zinc-900/35',
                      isSelected && 'bg-primary/5 hover:bg-primary/10 dark:bg-primary/10 dark:hover:bg-primary/15',
                      onRowClick && 'cursor-pointer'
                    )}
                    onClick={() => onRowClick && onRowClick(row)}
                    data-testid={`table-tr-${rIdx}`}
                  >
                    {showSelection && (
                      <td
                        className="p-4 w-12"
                        onClick={(e) => e.stopPropagation()} // Prevent triggering onRowClick
                      >
                        <Checkbox
                          checked={isSelected}
                          onChange={(e) => handleSelectRow(e.target.checked, id)}
                          aria-label={`Select row ${id}`}
                          data-testid={`table-row-select-${id}`}
                        />
                      </td>
                    )}
                    {columns.map((col, cIdx) => {
                      const value = col.accessorKey
                        ? row[col.accessorKey as keyof T]
                        : undefined;

                      return (
                        <td key={cIdx} className={cn('p-4 align-middle text-foreground/90', col.className)}>
                          {col.cell
                            ? col.cell(value, row, rIdx)
                            : value !== undefined
                            ? String(value)
                            : null}
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Integration */}
      {!loading && pagination && (
        <Pagination
          page={pagination.page}
          pageSize={pagination.pageSize}
          totalItems={pagination.totalItems}
          onPageChange={pagination.onPageChange}
          onPageSizeChange={pagination.onPageSizeChange}
          className="border-t-0"
        />
      )}
    </div>
  );
}
