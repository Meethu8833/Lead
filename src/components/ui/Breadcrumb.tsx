import * as React from 'react';
import { cn } from '../../utils/cn';
import { ChevronRight, Home, MoreHorizontal } from 'lucide-react';

export interface BreadcrumbItemType {
  label: React.ReactNode;
  href?: string;
  icon?: React.ReactNode;
  isCurrent?: boolean;
}

export interface BreadcrumbProps {
  items: BreadcrumbItemType[];
  separator?: React.ReactNode;
  maxItems?: number;
  showHome?: boolean;
  homeHref?: string;
  className?: string;
}

export const Breadcrumb = ({
  items,
  separator = <ChevronRight className="h-4 w-4" />,
  maxItems,
  showHome = true,
  homeHref = '/',
  className,
}: BreadcrumbProps) => {
  const allItems = React.useMemo(() => {
    const list: BreadcrumbItemType[] = [];
    if (showHome) {
      list.push({
        label: 'Home',
        href: homeHref,
        icon: <Home className="h-3.5 w-3.5" />,
      });
    }
    return [...list, ...items];
  }, [items, showHome, homeHref]);

  const visibleItems = React.useMemo(() => {
    if (!maxItems || allItems.length <= maxItems || allItems.length <= 3) {
      return allItems;
    }

    // Keep first item (Home), ellipsis, and last items
    const keepLastCount = Math.max(1, maxItems - 2);
    const first = allItems[0];
    const last = allItems.slice(allItems.length - keepLastCount);

    return [
      first,
      { label: <MoreHorizontal className="h-4 w-4" />, isEllipsis: true } as any,
      ...last,
    ];
  }, [allItems, maxItems]);

  return (
    <nav
      aria-label="Breadcrumb Navigation"
      className={cn('flex items-center text-sm font-medium text-muted-foreground', className)}
      data-testid="breadcrumb-nav"
    >
      <ol className="flex items-center flex-wrap gap-1.5" data-testid="breadcrumb-list">
        {visibleItems.map((item, idx) => {
          const isLast = idx === visibleItems.length - 1;
          const isEllipsis = (item as any).isEllipsis;
          const isCurrent = item.isCurrent || (isLast && !isEllipsis);

          return (
            <li key={idx} className="flex items-center gap-1.5" data-testid="breadcrumb-item">
              {/* Separator (rendered before item, except for the first one) */}
              {idx > 0 && (
                <span className="text-muted-foreground/50 select-none" role="presentation" data-testid="breadcrumb-separator">
                  {separator}
                </span>
              )}

              {/* Item Content */}
              {isEllipsis ? (
                <span
                  className="flex items-center justify-center h-5 w-5 rounded-md hover:bg-muted transition-colors cursor-help"
                  title="Show collapsed path"
                  data-testid="breadcrumb-ellipsis"
                >
                  {item.label}
                </span>
              ) : isCurrent ? (
                <span
                  className="font-semibold text-foreground select-none"
                  aria-current="page"
                  data-testid="breadcrumb-current"
                >
                  <span className="flex items-center gap-1">
                    {item.icon && <span className="shrink-0">{item.icon}</span>}
                    <span>{item.label}</span>
                  </span>
                </span>
              ) : item.href ? (
                <a
                  href={item.href}
                  className="flex items-center gap-1 hover:text-foreground transition-colors"
                  data-testid="breadcrumb-link"
                >
                  {item.icon && <span className="shrink-0">{item.icon}</span>}
                  <span>{item.label}</span>
                </a>
              ) : (
                <span className="flex items-center gap-1" data-testid="breadcrumb-text">
                  {item.icon && <span className="shrink-0">{item.icon}</span>}
                  <span>{item.label}</span>
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};
