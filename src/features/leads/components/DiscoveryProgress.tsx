/**
 * src/features/leads/components/DiscoveryProgress.tsx
 *
 * Live progress for a running discovery: a bar, an elapsed clock, and the six pipeline
 * stages with the current one marked.
 *
 * Presentational. Every number it renders is computed by `useDiscoveryProgress`; this file
 * decides only how to draw them.
 *
 * **The estimate is labelled as one.** While the backend runs discovery synchronously there
 * is no job to observe, so the stage shown is inferred from elapsed time. Presenting a
 * guess as a reading would be the wrong kind of polish — the operator is told, in the
 * component, that stages are estimated. When a pollable job lands, `isEstimated` goes false
 * and the same layout renders real state.
 */

import { Check, Circle, Loader2 } from 'lucide-react';

import { Card, CardContent, ProgressBar } from '../../../components/ui';
import { cn } from '../../../utils/cn';
import {
  DISCOVERY_STAGES,
  formatElapsed,
  isStageSkipped,
} from '../discoveryUtils';

export interface DiscoveryProgressProps {
  /** Index into `DISCOVERY_STAGES`; -1 when not running. */
  stageIndex: number;
  percent: number;
  elapsedSeconds: number;
  /** True while the stage shown is a time-based estimate rather than a server reading. */
  isEstimated: boolean;
  city: string;
  discoverWebsites: boolean;
  extractContacts: boolean;
}

export const DiscoveryProgress = ({
  stageIndex,
  percent,
  elapsedSeconds,
  isEstimated,
  city,
  discoverWebsites,
  extractContacts,
}: DiscoveryProgressProps) => {
  const toggles = { discoverWebsites, extractContacts };

  return (
    <Card data-testid="discovery-progress">
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold">
            Importing leads from {city || 'the selected city'}…
          </h3>
          <span
            className="text-sm tabular-nums text-muted-foreground"
            data-testid="discovery-elapsed"
          >
            {formatElapsed(elapsedSeconds)} elapsed
          </span>
        </div>

        {/*
          Determinate on purpose, despite the value being an estimate: an indeterminate bar
          says only "something is happening", while a moving one tied to named stages tells
          the operator roughly how far along a multi-minute run is. `percent` is capped
          below 100 so the bar never claims completion the response has not confirmed.
        */}
        <ProgressBar
          value={percent}
          variant="determinate"
          size="sm"
          color="primary"
          showPercentage
          label="Discovery progress"
        />

        <ol className="space-y-2" data-testid="discovery-stages">
          {DISCOVERY_STAGES.map((stage, index) => {
            const skipped = isStageSkipped(index, toggles);
            const isDone = !skipped && index < stageIndex;
            const isActive = !skipped && index === stageIndex;

            return (
              <li
                key={stage.key}
                className={cn(
                  'flex items-start gap-3 text-sm transition-colors',
                  skipped && 'opacity-50',
                  isActive ? 'text-foreground' : 'text-muted-foreground'
                )}
                data-testid={`discovery-stage-${stage.key}`}
                aria-current={isActive ? 'step' : undefined}
              >
                <span className="mt-0.5 shrink-0">
                  {isDone ? (
                    <Check className="h-4 w-4 text-emerald-600" aria-hidden="true" />
                  ) : isActive ? (
                    <Loader2
                      className="h-4 w-4 animate-spin text-primary"
                      aria-hidden="true"
                    />
                  ) : (
                    <Circle className="h-4 w-4 opacity-40" aria-hidden="true" />
                  )}
                </span>

                <span className="min-w-0">
                  <span
                    className={cn('font-medium', skipped && 'line-through')}
                  >
                    {stage.label}
                  </span>
                  <span className="block text-xs">
                    {skipped ? 'Skipped for this run' : stage.detail}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>

        {/*
          Announced rather than only drawn, so a screen-reader user learns the run is
          progressing without watching the spinner.
        */}
        <p role="status" aria-live="polite" className="text-xs text-muted-foreground">
          {isEstimated
            ? 'Stages are estimated from elapsed time — the run reports its exact results when it finishes.'
            : 'Live stage reported by the server.'}{' '}
          Large runs can take several minutes. Leaving this page does not stop the import.
        </p>
      </CardContent>
    </Card>
  );
};
