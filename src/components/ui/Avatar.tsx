import * as React from 'react';
import * as AvatarPrimitive from '@radix-ui/react-avatar';
import { cn } from '../../utils/cn';

export interface AvatarProps extends React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root> {
  image?: string;
  fallback?: string;
  size?: 'sm' | 'md' | 'lg';
  isOnline?: boolean;
}

export const Avatar = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Root>,
  AvatarProps
>(({ className, image, fallback, size = 'md', isOnline = false, ...props }, ref) => {
  const sizeClasses = {
    sm: 'h-8 w-8 text-xs',
    md: 'h-10 w-10 text-sm',
    lg: 'h-14 w-14 text-lg',
  };

  const indicatorSizes = {
    sm: 'h-2 w-2 right-0 bottom-0',
    md: 'h-2.5 w-2.5 right-0.5 bottom-0.5',
    lg: 'h-3.5 w-3.5 right-0.5 bottom-0.5',
  };

  return (
    <div className="relative inline-flex shrink-0" data-testid="avatar-container">
      <AvatarPrimitive.Root
        ref={ref}
        className={cn(
          'relative flex shrink-0 overflow-hidden rounded-full bg-muted dark:bg-zinc-800 border select-none',
          sizeClasses[size],
          className
        )}
        {...props}
      >
        <AvatarPrimitive.Image
          src={image}
          className="aspect-square h-full w-full object-cover"
          data-testid="avatar-image"
        />
        <AvatarPrimitive.Fallback
          className="flex h-full w-full items-center justify-center rounded-full bg-muted text-muted-foreground font-semibold dark:bg-zinc-800"
          data-testid="avatar-fallback"
        >
          {fallback || '?'}
        </AvatarPrimitive.Fallback>
      </AvatarPrimitive.Root>

      {isOnline && (
        <span
          className={cn(
            'absolute rounded-full bg-emerald-500 ring-2 ring-background border-white block',
            indicatorSizes[size]
          )}
          data-testid="avatar-online-indicator"
        />
      )}
    </div>
  );
});

Avatar.displayName = 'Avatar';
