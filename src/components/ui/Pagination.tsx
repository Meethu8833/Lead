import { Button } from './Button';
import { Select } from './Select';
import { cn } from '../../utils/cn';
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';

export interface PaginationProps {
  page: number;
  pageSize: number;
  totalItems: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  className?: string;
}

export const Pagination = ({
  page,
  pageSize,
  totalItems,
  onPageChange,
  onPageSizeChange,
  className,
}: PaginationProps) => {
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= totalPages && newPage !== page) {
      onPageChange(newPage);
    }
  };

  const getPageNumbers = () => {
    const siblingCount = 1;
    const totalPageNumbers = siblingCount + 5; // siblingCount + firstPage + lastPage + currentPage + 2*ellipsis

    if (totalPages <= totalPageNumbers) {
      return Array.from({ length: totalPages }, (_, i) => i + 1);
    }

    const leftSiblingIndex = Math.max(page - siblingCount, 1);
    const rightSiblingIndex = Math.min(page + siblingCount, totalPages);

    const shouldShowLeftDots = leftSiblingIndex > 2;
    const shouldShowRightDots = rightSiblingIndex < totalPages - 1;

    if (!shouldShowLeftDots && shouldShowRightDots) {
      const leftItemCount = 3 + 2 * siblingCount;
      const leftRange = Array.from({ length: leftItemCount }, (_, i) => i + 1);
      return [...leftRange, 'ellipsis-right', totalPages];
    }

    if (shouldShowLeftDots && !shouldShowRightDots) {
      const rightItemCount = 3 + 2 * siblingCount;
      const rightRange = Array.from(
        { length: rightItemCount },
        (_, i) => totalPages - rightItemCount + 1 + i
      );
      return [1, 'ellipsis-left', ...rightRange];
    }

    if (shouldShowLeftDots && shouldShowRightDots) {
      const middleRange = Array.from(
        { length: rightSiblingIndex - leftSiblingIndex + 1 },
        (_, i) => leftSiblingIndex + i
      );
      return [1, 'ellipsis-left', ...middleRange, 'ellipsis-right', totalPages];
    }

    return [];
  };

  const pages = getPageNumbers();
  const startItem = (page - 1) * pageSize + 1;
  const endItem = Math.min(page * pageSize, totalItems);

  return (
    <nav
      role="navigation"
      aria-label="Pagination Navigation"
      className={cn(
        'flex flex-col sm:flex-row items-center justify-between gap-4 py-3 px-4 border-t border-border bg-card text-card-foreground',
        className
      )}
      data-testid="pagination-nav"
    >
      {/* Total records display */}
      <div className="text-sm text-muted-foreground" data-testid="pagination-info">
        Showing <span className="font-semibold text-foreground">{totalItems === 0 ? 0 : startItem}</span> to{' '}
        <span className="font-semibold text-foreground">{endItem}</span> of{' '}
        <span className="font-semibold text-foreground">{totalItems}</span> entries
      </div>

      {/* Controls Container */}
      <div className="flex flex-wrap items-center justify-center gap-4 sm:gap-6">
        {/* Page Size Selector */}
        {onPageSizeChange && (
          <div className="flex items-center gap-2" data-testid="pagination-limit-selector">
            <span className="text-sm text-muted-foreground whitespace-nowrap">
              Rows per page
            </span>
            <Select
              value={pageSize.toString()}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
              aria-label="Select number of pages"
              className="w-20 h-9"
              options={[
                { label: '5', value: '5' },
                { label: '10', value: '10' },
                { label: '25', value: '25' },
                { label: '50', value: '50' },
                { label: '100', value: '100' },
              ]}
            />
          </div>
        )}

        {/* Buttons List */}
        <div className="flex items-center gap-1">
          {/* First Page */}
          <Button
            variant="outline"
            size="sm"
            className="h-9 w-9 p-0"
            onClick={() => handlePageChange(1)}
            disabled={page === 1}
            aria-label="Go to first page"
            data-testid="pagination-first"
          >
            <ChevronsLeft className="h-4 w-4" />
          </Button>

          {/* Previous Page */}
          <Button
            variant="outline"
            size="sm"
            className="h-9 w-9 p-0"
            onClick={() => handlePageChange(page - 1)}
            disabled={page === 1}
            aria-label="Go to previous page"
            data-testid="pagination-prev"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>

          {/* Page Numbers */}
          <div className="flex items-center gap-1" data-testid="pagination-numbers">
            {pages.map((p, idx) => {
              if (typeof p === 'string') {
                return (
                  <span
                    key={`${p}-${idx}`}
                    className="px-2 text-sm text-muted-foreground select-none"
                    data-testid="pagination-ellipsis"
                  >
                    &#8230;
                  </span>
                );
              }

              const isCurrent = p === page;
              return (
                <Button
                  key={p}
                  variant={isCurrent ? 'primary' : 'outline'}
                  size="sm"
                  className={cn(
                    'h-9 w-9 p-0 text-sm font-medium',
                    isCurrent && 'pointer-events-none'
                  )}
                  onClick={() => handlePageChange(p)}
                  aria-label={`Go to page ${p}`}
                  aria-current={isCurrent ? 'page' : undefined}
                >
                  {p}
                </Button>
              );
            })}
          </div>

          {/* Next Page */}
          <Button
            variant="outline"
            size="sm"
            className="h-9 w-9 p-0"
            onClick={() => handlePageChange(page + 1)}
            disabled={page === totalPages}
            aria-label="Go to next page"
            data-testid="pagination-next"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>

          {/* Last Page */}
          <Button
            variant="outline"
            size="sm"
            className="h-9 w-9 p-0"
            onClick={() => handlePageChange(totalPages)}
            disabled={page === totalPages}
            aria-label="Go to last page"
            data-testid="pagination-last"
          >
            <ChevronsRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </nav>
  );
};
