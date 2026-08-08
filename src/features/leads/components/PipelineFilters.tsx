/**
 * src/features/leads/components/PipelineFilters.tsx
 *
 * The board's filter and sort toolbar.
 *
 * Fully controlled: it holds no state of its own and reports every change upward, so the
 * board is the single source of truth for what is being shown and the toolbar can be
 * rendered from a URL or a saved view later without changing it.
 *
 * City and District are free-text rather than selects because the backend matches them
 * partially (`ILIKE %value%`) and exposes no endpoint enumerating the distinct values —
 * a dropdown would have to be built by scanning a lead sample, which would silently omit
 * every place not in that sample.
 */

import { X } from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import { Input } from '../../../components/ui/Input';
import { SearchBox } from '../../../components/ui/SearchBox';
import { Select } from '../../../components/ui/Select';
import {
  EmployeeSummary,
  LeadSource,
  PipelineFilters as PipelineFiltersState,
  PipelineSort,
} from '../types';
import { PIPELINE_SORT_OPTIONS, hasActiveFilters } from '../pipelineUtils';

/** Every lead source, matching LeadSource in app/models/lead.py. */
const LEAD_SOURCES: LeadSource[] = [
  'MANUAL',
  'GOOGLE_MAPS',
  'INSTAGRAM',
  'FACEBOOK',
  'JUSTDIAL',
  'REFERRAL',
  'CSV_IMPORT',
  'OTHER',
];

/** "GOOGLE_MAPS" -> "Google Maps". */
const humanize = (value: string): string =>
  value
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');

export interface PipelineFiltersProps {
  filters: PipelineFiltersState;
  sort: PipelineSort;
  employees: EmployeeSummary[];
  onChange: (patch: Partial<PipelineFiltersState>) => void;
  onSortChange: (sort: PipelineSort) => void;
  onClear: () => void;
}

export const PipelineFiltersBar = ({
  filters,
  sort,
  employees,
  onChange,
  onSortChange,
  onClear,
}: PipelineFiltersProps) => {
  const isFiltered = hasActiveFilters(filters);

  return (
    <div
      className="grid grid-cols-1 gap-3 rounded-xl border border-border bg-card p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
      data-testid="pipeline-filters"
    >
      {/* Search spans two columns on wide layouts — it is the control reached for most,
          and business names need the room. */}
      <div className="sm:col-span-2 xl:col-span-2">
        <SearchBox
          label="Search"
          placeholder="Business, contact, phone, email…"
          value={filters.search}
          onSearch={(value) => onChange({ search: value })}
          showShortcut={false}
          data-testid="pipeline-search"
        />
      </div>

      <Select
        label="Lead source"
        value={filters.source}
        onChange={(event) => onChange({ source: event.target.value as LeadSource | '' })}
        options={[
          { label: 'All sources', value: '' },
          ...LEAD_SOURCES.map((source) => ({ label: humanize(source), value: source })),
        ]}
        fullWidth
        data-testid="pipeline-filter-source"
      />

      <Select
        label="Assigned to"
        value={filters.assigned_employee_id}
        onChange={(event) => onChange({ assigned_employee_id: event.target.value })}
        options={[
          { label: 'Anyone', value: '' },
          ...employees.map((employee) => ({
            label: employee.full_name ?? employee.name ?? employee.email ?? employee.id,
            value: employee.id,
          })),
        ]}
        fullWidth
        data-testid="pipeline-filter-assignee"
      />

      <Input
        label="City"
        placeholder="e.g. Kochi"
        value={filters.city}
        onChange={(event) => onChange({ city: event.target.value })}
        fullWidth
        data-testid="pipeline-filter-city"
      />

      <Input
        label="District"
        placeholder="e.g. Ernakulam"
        value={filters.district}
        onChange={(event) => onChange({ district: event.target.value })}
        fullWidth
        data-testid="pipeline-filter-district"
      />

      <div className="flex items-end gap-2 sm:col-span-2 xl:col-span-6">
        <div className="w-full sm:w-56">
          <Select
            label="Sort cards by"
            value={sort}
            onChange={(event) => onSortChange(event.target.value as PipelineSort)}
            options={PIPELINE_SORT_OPTIONS.map((option) => ({
              label: option.label,
              value: option.value,
            }))}
            fullWidth
            data-testid="pipeline-sort"
          />
        </div>

        {isFiltered && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onClear}
            data-testid="pipeline-clear-filters"
          >
            <X className="mr-1.5 h-3.5 w-3.5" />
            Clear filters
          </Button>
        )}
      </div>
    </div>
  );
};
