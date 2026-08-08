/**
 * src/features/leads/pages/ImportLeadsPage.tsx
 *
 * The Lead Import screen: pick a source, run a collection, see what landed.
 *
 * Composition only — every request, cache invalidation and toast lives in
 * `importHooks.ts`, every pure rule in `importUtils.ts`, and the sub-sections are the
 * presentational components in `components/`. What remains here is the form wiring and the
 * decision of which section to show.
 *
 * Three things shape the layout:
 *
 *  - **The form is replaced by the result, not stacked under it.** A finished run is the
 *    thing the operator came for, so it takes the form's place until "Import Again" is
 *    pressed. Keeping both mounted would push the summary below the fold on a laptop.
 *
 *  - **The schema is rebuilt per provider.** Whether a keyword is required is a property of
 *    the provider in the registry, not a constant, so `buildImportSchema` is called with
 *    the selected provider's flags — see `importValidation.ts`.
 *
 *  - **The import request stays open for the whole run.** Collection is synchronous
 *    server-side, so there is no job to poll: the button spins, an indeterminate progress
 *    bar reports that work is happening, and the response *is* the result.
 *
 * ## Two modes
 *
 * The screen offers two ways to acquire leads, because the backend genuinely has two:
 *
 *  - **City Discovery** (`POST /leads/discover`) names a *place* and runs the fixed
 *    collect -> website -> contacts -> normalise -> dedup -> save pipeline over it. This is
 *    the default, since it is the path that needs no keyword and no file.
 *  - **Provider Import** (`POST /leads/import`) names a *source* — Google Maps, Instagram,
 *    a CSV upload — and hands it a keyword.
 *
 * They share this screen, the `leads:import` permission, the lifetime statistics row and
 * the run history, because to an operator they are one job. They share no state: switching
 * mode does not carry a city into a keyword, and each mode's result clears independently.
 * Everything mode-specific lives in `discovery*` or `import*` modules alongside this file.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useNavigate } from 'react-router-dom';
import { Compass, Download, Search, Upload } from 'lucide-react';

import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ErrorState,
  Input,
  NumberInput,
  ProgressBar,
  Spinner,
} from '../../../components/ui';
import { CsvDropZone } from '../components/CsvDropZone';
import { DiscoveryForm } from '../components/DiscoveryForm';
import { DiscoveryProgress } from '../components/DiscoveryProgress';
import { DiscoveryResults } from '../components/DiscoveryResults';
import { DiscoveryStats } from '../components/DiscoveryStats';
import { ImportHistoryTable } from '../components/ImportHistoryTable';
import { ImportResultSummary } from '../components/ImportResultSummary';
import { ImportStatsCards } from '../components/ImportStatsCards';
import { ProviderSelector } from '../components/ProviderSelector';
import {
  useImportHistory,
  useImportProviders,
  useImportStatistics,
  useLeadImport,
  useProviderBreakdown,
  useRetryImport,
} from '../importHooks';
import {
  DEFAULT_IMPORT_LIMIT,
  MAX_IMPORT_LIMIT,
  MIN_IMPORT_LIMIT,
  PROVIDER_GOOGLE_MAPS,
  providerUnavailableReason,
} from '../importUtils';
import { buildImportSchema, ImportFormSchema } from '../importValidation';
import { useDiscoveryProgress, useRunDiscovery } from '../discoveryHooks';
import { DEFAULT_CATEGORY, DEFAULT_DISCOVERY_LIMIT } from '../discoveryUtils';
import { discoverySchema, DiscoveryFormSchema } from '../discoveryValidation';
import { cn } from '../../../utils/cn';
import { useAuthStore } from '../../../app/store';
import { checkPermission } from '../../../components/auth/PermissionGuard';

export default function ImportLeadsPage() {
  const navigate = useNavigate();

  const permissions = useAuthStore((state) => state.permissions);
  const canImport = useMemo(
    () => checkPermission(permissions, 'leads:import'),
    [permissions]
  );

  const providersQuery = useImportProviders();
  const statisticsQuery = useImportStatistics();
  const historyQuery = useImportHistory();
  const retryMutation = useRetryImport();
  const { run, isImporting, result, uploadPercent, reset } = useLeadImport();

  // ----------------------------------------------------------------------------------
  // Mode
  // ----------------------------------------------------------------------------------
  // Discovery is the default: it needs neither a keyword nor a file, so it is the shortest
  // path to leads for an operator who just wants to work a city.
  const [mode, setMode] = useState<'discovery' | 'provider'>('discovery');

  // ----------------------------------------------------------------------------------
  // City discovery
  // ----------------------------------------------------------------------------------
  const discovery = useRunDiscovery();
  const [isCustomCity, setIsCustomCity] = useState(false);

  const discoveryForm = useForm<DiscoveryFormSchema>({
    resolver: zodResolver(discoverySchema),
    defaultValues: {
      city: '',
      category: DEFAULT_CATEGORY,
      radius_km: null,
      limit: DEFAULT_DISCOVERY_LIMIT,
      discover_websites: true,
      extract_contacts: true,
    },
  });

  const discoveryValues = discoveryForm.watch();

  const discoveryProgress = useDiscoveryProgress({
    isRunning: discovery.isRunning,
    discoverWebsites: discoveryValues.discover_websites,
    extractContacts: discoveryValues.extract_contacts,
  });

  const onDiscoverySubmit = discoveryForm.handleSubmit((values) => {
    if (!canImport || discovery.isRunning) return;
    discovery.run(values);
  });

  const handleDiscoverAgain = useCallback(() => {
    discovery.reset();
    discoveryForm.reset({
      city: '',
      category: DEFAULT_CATEGORY,
      radius_km: null,
      limit: DEFAULT_DISCOVERY_LIMIT,
      discover_websites: true,
      extract_contacts: true,
    });
    setIsCustomCity(false);
  }, [discovery, discoveryForm]);

  const providers = providersQuery.providers;

  const [selectedKey, setSelectedKey] = useState<string>('');

  // Settle on a provider once the registry arrives: Google Maps when present, otherwise
  // whatever the server actually offers. Runs only while nothing is selected, so it never
  // fights the user's own choice.
  useEffect(() => {
    if (selectedKey || providers.length === 0) return;
    const preferred =
      providers.find((provider) => provider.key === PROVIDER_GOOGLE_MAPS) ?? providers[0];
    setSelectedKey(preferred.key);
  }, [providers, selectedKey]);

  const selectedProvider = providers.find((provider) => provider.key === selectedKey);
  const requiresFile = selectedProvider?.requires_file ?? false;
  const requiresQuery = selectedProvider?.requires_query ?? false;
  const unavailableReason = providerUnavailableReason(selectedProvider);

  const {
    control,
    handleSubmit,
    register,
    reset: resetForm,
    setValue,
    watch,
    formState: { errors },
  } = useForm<ImportFormSchema>({
    resolver: zodResolver(buildImportSchema({ requiresQuery, requiresFile })),
    defaultValues: {
      query: '',
      limit: DEFAULT_IMPORT_LIMIT,
      file: null,
    },
  });

  // Drop inputs that no longer apply when the source changes — carrying a CSV over to
  // Google Maps, or a keyword over to CSV, would submit a field the endpoint ignores at
  // best and rejects at worst.
  //
  // The provider itself is deliberately NOT a form field: `selectedKey` already holds it,
  // and duplicating it into the form would mean two sources of truth that have to be kept
  // in step on every render.
  useEffect(() => {
    if (!selectedKey) return;
    if (requiresFile) {
      setValue('query', '', { shouldValidate: false });
    } else {
      setValue('file', null, { shouldValidate: false });
    }
  }, [selectedKey, requiresFile, setValue]);

  const file = watch('file');

  const onSubmit = handleSubmit((values) => {
    if (unavailableReason || isImporting) return;
    run({
      provider: selectedKey,
      query: values.query,
      limit: values.limit,
      file: values.file,
    });
  });

  const handleImportAgain = useCallback(() => {
    reset();
    resetForm({
      query: '',
      limit: DEFAULT_IMPORT_LIMIT,
      file: null,
    });
  }, [reset, resetForm, selectedKey]);

  const handleViewLeads = useCallback(() => navigate('/leads'), [navigate]);

  const jobs = historyQuery.data?.items ?? [];
  const breakdown = useProviderBreakdown(jobs, historyQuery.data?.total);
  const lastImportAt = jobs[0]?.created_at ?? null;

  const examples = selectedProvider?.capability.examples ?? [];
  const isSubmitDisabled = isImporting || !canImport || Boolean(unavailableReason);

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <header>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Import Leads</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Discover photographer prospects around a city, or collect them from Google Maps,
          Instagram or a CSV file. Duplicates are detected automatically and enrich the
          existing lead instead of creating a second one.
        </p>
      </header>

      <ImportStatsCards
        statistics={statisticsQuery.data}
        isLoading={statisticsQuery.isLoading}
        lastImportAt={lastImportAt}
        breakdown={breakdown.rows}
        breakdownIsSampled={breakdown.isSampled}
      />

      {!canImport && (
        <ErrorState
          title="You cannot run imports"
          description='Importing leads needs the "leads:import" permission. Ask an administrator to grant it.'
        />
      )}

      {/*
        Mode switch. Rendered as tabs rather than a dropdown because there are exactly two
        and both deserve to be discoverable — a dropdown would hide provider import behind a
        click for no gain.
      */}
      <div
        className="flex flex-wrap gap-2"
        role="tablist"
        aria-label="Lead acquisition mode"
      >
        {([
          { key: 'discovery' as const, label: 'City Discovery', icon: Compass },
          { key: 'provider' as const, label: 'Provider Import', icon: Upload },
        ]).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={mode === key}
            onClick={() => setMode(key)}
            data-testid={`import-mode-${key}`}
            className={cn(
              'flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 dark:border-zinc-800',
              mode === key
                ? 'border-primary bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            )}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>

      {mode === 'discovery' ? (
        <>
          {/*
            The form is replaced by the result once a run finishes, matching the provider
            mode below: a finished run is what the operator came for, and keeping both
            mounted pushes the summary below the fold.
          */}
          {discovery.result ? (
            <div className="space-y-6">
              <DiscoveryStats result={discovery.result} />
              <DiscoveryResults result={discovery.result} />
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button onClick={handleDiscoverAgain} variant="outline">
                  <Compass className="mr-2 h-4 w-4" aria-hidden="true" />
                  Import Again
                </Button>
                <Button onClick={handleViewLeads}>View Leads</Button>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Discover Leads by City</CardTitle>
                  <CardDescription>
                    Search a city for photography businesses, enrich them with contact
                    details from their websites, and save what is new.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <DiscoveryForm
                    control={discoveryForm.control}
                    register={discoveryForm.register}
                    errors={discoveryForm.formState.errors}
                    onSubmit={onDiscoverySubmit}
                    isRunning={discovery.isRunning}
                    disabled={!canImport}
                    radiusKm={discoveryValues.radius_km ?? null}
                    isCustomCity={isCustomCity}
                    onCityModeChange={setIsCustomCity}
                  />
                </CardContent>
              </Card>

              {discovery.isRunning && (
                <DiscoveryProgress
                  stageIndex={discoveryProgress.stageIndex}
                  percent={discoveryProgress.percent}
                  elapsedSeconds={discoveryProgress.elapsedSeconds}
                  isEstimated={discoveryProgress.isEstimated}
                  city={discoveryValues.city}
                  discoverWebsites={discoveryValues.discover_websites}
                  extractContacts={discoveryValues.extract_contacts}
                />
              )}
            </div>
          )}
        </>
      ) : result ? (
        <ImportResultSummary
          job={result}
          onViewLeads={handleViewLeads}
          onImportAgain={handleImportAgain}
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>New Import</CardTitle>
            <CardDescription>
              Choose a source, tell it what to look for, and run the collection.
            </CardDescription>
          </CardHeader>

          <CardContent>
            {providersQuery.isError ? (
              <ErrorState
                description="Could not load the available import providers."
                onRetry={() => providersQuery.refetch()}
              />
            ) : (
              <form onSubmit={onSubmit} className="space-y-5" noValidate>
                <ProviderSelector
                  providers={providers}
                  value={selectedKey}
                  onChange={setSelectedKey}
                  isLoading={providersQuery.isLoading}
                  disabled={isImporting || !canImport}
                />

                {requiresFile ? (
                  <Controller
                    control={control}
                    name="file"
                    render={({ field }) => (
                      <CsvDropZone
                        file={field.value}
                        onSelect={(picked) => field.onChange(picked)}
                        onClear={() => field.onChange(null)}
                        error={errors.file?.message}
                        disabled={isImporting || !canImport}
                        uploadPercent={uploadPercent}
                        isUploading={isImporting}
                      />
                    )}
                  />
                ) : (
                  <div className="space-y-2">
                    <Input
                      label="Search keyword"
                      placeholder="Wedding Photographer Kozhikode"
                      prefix={<Search className="h-4 w-4" aria-hidden="true" />}
                      error={errors.query?.message}
                      helperText="What to search the provider for — a service and a place works best."
                      disabled={isImporting || !canImport}
                      fullWidth
                      {...register('query')}
                    />

                    {examples.length > 0 && (
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-muted-foreground">Examples:</span>
                        {examples.map((example) => (
                          <button
                            key={example}
                            type="button"
                            onClick={() =>
                              setValue('query', example, { shouldValidate: true })
                            }
                            disabled={isImporting || !canImport}
                            className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50 dark:border-zinc-800"
                          >
                            {example}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <Controller
                  control={control}
                  name="limit"
                  render={({ field }) => (
                    <NumberInput
                      label="Maximum results"
                      value={field.value}
                      onChange={(value) => field.onChange(value ?? null)}
                      min={MIN_IMPORT_LIMIT}
                      max={MAX_IMPORT_LIMIT}
                      step={10}
                      error={errors.limit?.message}
                      helperText={`Between ${MIN_IMPORT_LIMIT} and ${MAX_IMPORT_LIMIT}. Larger runs take longer.`}
                      disabled={isImporting || !canImport}
                      className="sm:max-w-xs"
                    />
                  )}
                />

                {isImporting && !requiresFile && (
                  <ProgressBar
                    variant="indeterminate"
                    size="sm"
                    color="primary"
                    label="Collecting leads from the provider…"
                  />
                )}

                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <Button
                    type="submit"
                    disabled={isSubmitDisabled}
                    data-testid="import-submit"
                  >
                    {isImporting ? (
                      <>
                        <Spinner size="sm" className="mr-2" />
                        Importing…
                      </>
                    ) : (
                      <>
                        <Download className="mr-2 h-4 w-4" aria-hidden="true" />
                        Import Leads
                      </>
                    )}
                  </Button>

                  {/*
                    Progress is announced rather than only drawn, so a screen-reader user
                    learns the run started and finished without watching the spinner.
                  */}
                  <p role="status" aria-live="polite" className="text-xs text-muted-foreground">
                    {isImporting
                      ? requiresFile && file
                        ? `Uploading ${file.name} — ${uploadPercent}% sent.`
                        : 'Import running. This can take up to a minute for large runs.'
                      : ''}
                  </p>
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      )}

      <ImportHistoryTable
        jobs={jobs}
        isLoading={historyQuery.isLoading}
        isError={historyQuery.isError}
        onRefresh={() => historyQuery.refetch()}
        isRefreshing={historyQuery.isFetching}
        onRetry={(id) => retryMutation.mutate(id)}
        retryingJobId={retryMutation.isPending ? retryMutation.variables : null}
        canRetry={canImport}
      />
    </div>
  );
}
