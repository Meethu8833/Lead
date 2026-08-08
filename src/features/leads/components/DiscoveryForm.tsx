/**
 * src/features/leads/components/DiscoveryForm.tsx
 *
 * The city / category / radius form that starts a discovery run.
 *
 * Presentational: it renders fields, surfaces validation errors and raises `onSubmit`. It
 * owns no request, no toast and no derived business rule — the schema is in
 * `discoveryValidation.ts`, the option lists and the clamp warning are in
 * `discoveryUtils.ts`, and the run itself belongs to `useRunDiscovery`.
 *
 * The city selector allows a value outside the curated list. The backend geocodes free
 * text, so restricting the operator to twenty cities would be a UI-invented limit rather
 * than a real one — the list is a shortcut, and "Other city" opens a plain input.
 */

import { useMemo } from 'react';
import { Control, Controller, FieldErrors, UseFormRegister } from 'react-hook-form';
import { Compass, MapPin, Search } from 'lucide-react';

import {
  Button,
  Input,
  NumberInput,
  Select,
  Spinner,
  Switch,
} from '../../../components/ui';
import {
  DEFAULT_RADIUS_KM,
  DISCOVERY_CATEGORIES,
  DISCOVERY_CITIES,
  MAX_DISCOVERY_LIMIT,
  MAX_RADIUS_KM,
  MIN_DISCOVERY_LIMIT,
  MIN_RADIUS_KM,
  radiusClampNotice,
} from '../discoveryUtils';
import { DiscoveryFormSchema } from '../discoveryValidation';

/** Sentinel for the "not in the list" city option. Never sent to the API. */
export const CUSTOM_CITY = '__custom__';

export interface DiscoveryFormProps {
  control: Control<DiscoveryFormSchema>;
  register: UseFormRegister<DiscoveryFormSchema>;
  errors: FieldErrors<DiscoveryFormSchema>;
  onSubmit: (event: React.FormEvent) => void;
  /** True while a run is open — every control is locked for its duration. */
  isRunning: boolean;
  disabled?: boolean;
  /** Current radius, for the clamp warning. */
  radiusKm: number | null;
  /** Whether the city field is a free-text input rather than the curated selector. */
  isCustomCity: boolean;
  onCityModeChange: (custom: boolean) => void;
}

export const DiscoveryForm = ({
  control,
  register,
  errors,
  onSubmit,
  isRunning,
  disabled = false,
  radiusKm,
  isCustomCity,
  onCityModeChange,
}: DiscoveryFormProps) => {
  const locked = isRunning || disabled;

  const cityOptions = useMemo(
    () => [
      ...DISCOVERY_CITIES.map((city) => ({ value: city.value, label: city.label })),
      { value: CUSTOM_CITY, label: 'Other city…' },
    ],
    []
  );

  const clampNotice = radiusClampNotice(radiusKm);

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {isCustomCity ? (
          <div className="space-y-1">
            <Input
              label="City"
              placeholder="Enter a city name"
              prefix={<MapPin className="h-4 w-4" aria-hidden="true" />}
              error={errors.city?.message}
              helperText="The city is geocoded, so most place names work."
              disabled={locked}
              fullWidth
              data-testid="discovery-city-input"
              {...register('city')}
            />
            <button
              type="button"
              onClick={() => onCityModeChange(false)}
              disabled={locked}
              className="text-xs text-muted-foreground underline-offset-2 hover:underline disabled:opacity-50"
            >
              Choose from the list instead
            </button>
          </div>
        ) : (
          <Controller
            control={control}
            name="city"
            render={({ field }) => (
              <Select
                label="City"
                placeholder="Select a city"
                options={cityOptions}
                value={field.value}
                onChange={(event) => {
                  const next = event.target.value;
                  if (next === CUSTOM_CITY) {
                    // Clear rather than carry the sentinel into the field — it is a UI
                    // token, and letting it reach validation would fail confusingly.
                    field.onChange('');
                    onCityModeChange(true);
                    return;
                  }
                  field.onChange(next);
                }}
                error={errors.city?.message}
                helperText="Leads are collected around this city's centre."
                disabled={locked}
                fullWidth
                data-testid="discovery-city"
              />
            )}
          />
        )}

        <Controller
          control={control}
          name="category"
          render={({ field }) => (
            <Select
              label="Category"
              options={DISCOVERY_CATEGORIES}
              value={field.value}
              onChange={(event) => field.onChange(event.target.value)}
              error={errors.category?.message}
              helperText="Recorded on every lead this run collects."
              disabled={locked}
              fullWidth
              data-testid="discovery-category"
            />
          )}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <Controller
            control={control}
            name="radius_km"
            render={({ field }) => (
              <NumberInput
                label="Search radius (km)"
                value={field.value ?? undefined}
                onChange={(value) => field.onChange(value ?? null)}
                min={MIN_RADIUS_KM}
                max={MAX_RADIUS_KM}
                step={5}
                error={errors.radius_km?.message}
                helperText={`Leave blank to use the default ${DEFAULT_RADIUS_KM} km.`}
                disabled={locked}
                data-testid="discovery-radius"
              />
            )}
          />
          {/*
            A warning, not an error: the request is valid and will run, it just will not
            reach as far as the number implies once the source clamps it.
          */}
          {clampNotice && (
            <p className="text-xs text-amber-600 dark:text-amber-500" role="status">
              {clampNotice}
            </p>
          )}
        </div>

        <Controller
          control={control}
          name="limit"
          render={({ field }) => (
            <NumberInput
              label="Maximum records"
              value={field.value}
              onChange={(value) => field.onChange(value ?? null)}
              min={MIN_DISCOVERY_LIMIT}
              max={MAX_DISCOVERY_LIMIT}
              step={25}
              error={errors.limit?.message}
              helperText={`Between ${MIN_DISCOVERY_LIMIT} and ${MAX_DISCOVERY_LIMIT}. Larger runs take longer.`}
              disabled={locked}
              data-testid="discovery-limit"
            />
          )}
        />
      </div>

      {/*
        Both stages are network-bound and dominate a run's duration, so they are exposed
        rather than hidden: re-running an already-enriched city with them off is minutes
        faster and loses nothing.
      */}
      <fieldset className="space-y-3 rounded-lg border p-4 dark:border-zinc-800">
        <legend className="px-1 text-sm font-medium">Enrichment</legend>

        <Controller
          control={control}
          name="discover_websites"
          render={({ field }) => (
            <Switch
              label="Discover websites"
              description="Look up the official site of businesses that have none on the map. Slower, but finds far more contact details."
              checked={field.value}
              onChange={(event) => field.onChange(event.target.checked)}
              disabled={locked}
              data-testid="discovery-websites"
            />
          )}
        />

        <Controller
          control={control}
          name="extract_contacts"
          render={({ field }) => (
            <Switch
              label="Extract contacts"
              description="Visit discovered websites to read the phone numbers and emails they publish."
              checked={field.value}
              onChange={(event) => field.onChange(event.target.checked)}
              disabled={locked}
              data-testid="discovery-contacts"
            />
          )}
        />
      </fieldset>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Button type="submit" disabled={locked} data-testid="discovery-submit">
          {isRunning ? (
            <>
              <Spinner size="sm" className="mr-2" />
              Importing…
            </>
          ) : (
            <>
              <Compass className="mr-2 h-4 w-4" aria-hidden="true" />
              Start Import
            </>
          )}
        </Button>

        <p className="text-xs text-muted-foreground">
          <Search className="mr-1 inline h-3 w-3" aria-hidden="true" />
          Duplicates are detected automatically and enrich the existing lead.
        </p>
      </div>
    </form>
  );
};
