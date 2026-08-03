import * as React from 'react';
import { cn } from '../../utils/cn';

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  width?: string | number;
  height?: string | number;
  variant?: 'circle' | 'rect' | 'rounded';
}

export const Skeleton = React.forwardRef<HTMLDivElement, SkeletonProps>(
  ({ className, style, width, height, variant = 'rounded', ...props }, ref) => {
    const variantClasses = {
      rect: 'rounded-none',
      rounded: 'rounded-md',
      circle: 'rounded-full',
    };

    const customStyle: React.CSSProperties = {
      width: typeof width === 'number' ? `${width}px` : width,
      height: typeof height === 'number' ? `${height}px` : height,
      ...style,
    };

    return (
      <div
        ref={ref}
        className={cn(
          'animate-pulse bg-muted dark:bg-zinc-800',
          variantClasses[variant],
          className
        )}
        style={customStyle}
        data-testid="skeleton"
        {...props}
      />
    );
  }
);

Skeleton.displayName = 'Skeleton';
