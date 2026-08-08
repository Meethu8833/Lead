/**
 * src/features/leads/components/ProviderSelector.tsx
 *
 * Provider picker plus the capability panel for the selected provider.
 *
 * Rendered as a radio group rather than a `<Select>`: there are three options, each needs
 * a subtitle and an availability badge, and the whole set should be visible at once.
 * Native `<input type="radio">` elements carry the roving-focus and arrow-key behaviour
 * screen readers expect, so the styling wraps them instead of replacing them.
 *
 * An unavailable provider (no API credentials on the server) stays visible and selectable
 * so the reason can be explained — hiding it would leave an operator wondering where
 * Instagram went. The page refuses to submit it; see `providerUnavailableReason`.
 */

import { Check, Info } from 'lucide-react';
import { Badge, Card, CardContent, Spinner } from '../../../components/ui';
import { cn } from '../../../utils/cn';
import { DescribedProvider, providerUnavailableReason } from '../importUtils';

export interface ProviderSelectorProps {
  providers: DescribedProvider[];
  value: string;
  onChange: (providerKey: string) => void;
  isLoading?: boolean;
  disabled?: boolean;
}

export const ProviderSelector = ({
  providers,
  value,
  onChange,
  isLoading = false,
  disabled = false,
}: ProviderSelectorProps) => {
  const selected = providers.find((provider) => provider.key === value);
  const unavailableReason = providerUnavailableReason(selected);

  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 rounded-lg border border-dashed p-6 text-sm text-muted-foreground dark:border-zinc-800"
        role="status"
      >
        <Spinner size="sm" />
        Loading providers…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <fieldset disabled={disabled} className="space-y-2">
        <legend className="mb-2 text-sm font-medium">Source</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {providers.map((provider) => {
            const isSelected = provider.key === value;
            return (
              <label
                key={provider.key}
                data-testid={`provider-option-${provider.key}`}
                className={cn(
                  'relative flex cursor-pointer flex-col gap-1 rounded-lg border p-3 transition-colors',
                  'focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2',
                  isSelected
                    ? 'border-primary bg-primary/5 ring-1 ring-primary'
                    : 'border-border bg-card hover:border-primary/40 hover:bg-accent/40 dark:border-zinc-800 dark:bg-zinc-950/20',
                  disabled && 'cursor-not-allowed opacity-60'
                )}
              >
                <input
                  type="radio"
                  name="import-provider"
                  value={provider.key}
                  checked={isSelected}
                  onChange={() => onChange(provider.key)}
                  disabled={disabled}
                  className="sr-only"
                />
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-semibold">{provider.display_name}</span>
                  {isSelected && (
                    <Check className="h-4 w-4 flex-shrink-0 text-primary" aria-hidden="true" />
                  )}
                </div>
                <span className="text-xs text-muted-foreground">
                  {provider.capability.summary}
                </span>
                {!provider.is_available && (
                  <Badge variant="warning" size="sm" className="mt-1 self-start">
                    Not configured
                  </Badge>
                )}
              </label>
            );
          })}
        </div>
      </fieldset>

      {selected && (
        <Card data-testid="provider-info-panel">
          <CardContent className="space-y-3 p-4">
            <div className="flex items-center gap-2">
              <Info className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h3 className="text-sm font-semibold">{selected.display_name}</h3>
            </div>

            {selected.capability.features.length > 0 && (
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {selected.capability.features.map((feature) => (
                  <li key={feature} className="flex items-start gap-2 text-xs">
                    <Check
                      className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-600 dark:text-emerald-400"
                      aria-hidden="true"
                    />
                    <span className="text-muted-foreground">{feature}</span>
                  </li>
                ))}
              </ul>
            )}

            {unavailableReason && (
              <p
                role="alert"
                className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300"
              >
                {unavailableReason}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
};
