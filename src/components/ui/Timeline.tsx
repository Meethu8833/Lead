import * as React from 'react';
import { cn } from '../../utils/cn';
import { Check, Circle } from 'lucide-react';

export interface TimelineItem {
  id: string | number;
  title: React.ReactNode;
  description?: React.ReactNode;
  timestamp?: React.ReactNode;
  status?: 'completed' | 'current' | 'upcoming';
  icon?: React.ReactNode;
  color?: 'primary' | 'success' | 'warning' | 'danger' | 'muted';
}

export interface TimelineProps {
  items: TimelineItem[];
  className?: string;
}

export const Timeline = ({ items, className }: TimelineProps) => {
  const colorClasses = {
    primary: {
      line: 'bg-primary/30 dark:bg-primary/20',
      lineCompleted: 'bg-primary',
      dotBorder: 'border-primary',
      dotBg: 'bg-primary',
      text: 'text-primary',
      glow: 'shadow-[0_0_8px_rgba(37,99,235,0.5)]',
    },
    success: {
      line: 'bg-emerald-500/30 dark:bg-emerald-500/20',
      lineCompleted: 'bg-emerald-500',
      dotBorder: 'border-emerald-500',
      dotBg: 'bg-emerald-500',
      text: 'text-emerald-600 dark:text-emerald-500',
      glow: 'shadow-[0_0_8px_rgba(16,185,129,0.5)]',
    },
    warning: {
      line: 'bg-amber-500/30 dark:bg-amber-500/20',
      lineCompleted: 'bg-amber-500',
      dotBorder: 'border-amber-500',
      dotBg: 'bg-amber-500',
      text: 'text-amber-600 dark:text-amber-500',
      glow: 'shadow-[0_0_8px_rgba(245,158,11,0.5)]',
    },
    danger: {
      line: 'bg-destructive/30 dark:bg-destructive/20',
      lineCompleted: 'bg-destructive',
      dotBorder: 'border-destructive',
      dotBg: 'bg-destructive',
      text: 'text-destructive',
      glow: 'shadow-[0_0_8px_rgba(239,68,68,0.5)]',
    },
    muted: {
      line: 'bg-muted dark:bg-zinc-800',
      lineCompleted: 'bg-muted-foreground',
      dotBorder: 'border-muted-foreground/30 dark:border-zinc-700',
      dotBg: 'bg-muted dark:bg-zinc-800',
      text: 'text-muted-foreground',
      glow: '',
    },
  };

  return (
    <div className={cn('relative pl-6 space-y-6', className)} data-testid="timeline">
      {items.map((item, idx) => {
        const isLast = idx === items.length - 1;
        const status = item.status || 'upcoming';
        const color = item.color || (status === 'completed' ? 'success' : status === 'current' ? 'primary' : 'muted');
        const activeColor = colorClasses[color];

        return (
          <div key={item.id} className="relative flex gap-4 text-sm" data-testid={`timeline-item-${status}`}>
            {/* Timeline Line */}
            {!isLast && (
              <div
                className={cn(
                  'absolute left-[-15px] top-5 bottom-[-24px] w-[2px]',
                  status === 'completed' ? activeColor.lineCompleted : activeColor.line
                )}
                data-testid="timeline-line"
              />
            )}

            {/* Timeline Dot/Icon */}
            <div
              className={cn(
                'absolute left-[-24px] top-1.5 flex h-5.5 w-5.5 items-center justify-center rounded-full border-2 bg-background z-10 transition-all select-none',
                status === 'completed' && cn(activeColor.dotBorder, activeColor.dotBg, 'text-background-foreground text-white'),
                status === 'current' && cn(activeColor.dotBorder, activeColor.glow, 'animate-pulse'),
                status === 'upcoming' && 'border-muted-foreground/30 dark:border-zinc-700 text-muted-foreground'
              )}
              data-testid="timeline-dot"
            >
              {item.icon ? (
                <span className="h-3 w-3 flex items-center justify-center shrink-0">{item.icon}</span>
              ) : status === 'completed' ? (
                <Check className="h-3.5 w-3.5 stroke-[3.5]" />
              ) : status === 'current' ? (
                <Circle className={cn('h-2 w-2 fill-current', activeColor.text)} />
              ) : (
                <div className="h-2 w-2 rounded-full bg-muted-foreground/30 dark:bg-zinc-700" />
              )}
            </div>

            {/* Timeline Content */}
            <div className="flex-1 pb-2 space-y-1">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
                <h4
                  className={cn(
                    'font-semibold text-foreground/90 leading-tight',
                    status === 'current' && 'text-foreground font-bold'
                  )}
                  data-testid="timeline-title"
                >
                  {item.title}
                </h4>
                {item.timestamp && (
                  <span
                    className="text-xs text-muted-foreground shrink-0 select-none"
                    data-testid="timeline-timestamp"
                  >
                    {item.timestamp}
                  </span>
                )}
              </div>
              {item.description && (
                <div className="text-muted-foreground text-xs leading-relaxed whitespace-pre-wrap" data-testid="timeline-description">
                  {item.description}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
