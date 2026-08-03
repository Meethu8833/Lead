import * as React from 'react';
import { Button } from '../../../components/ui/Button';
import { FilterBar } from '../../../components/ui/LayoutHelpers';
import { Input } from '../../../components/ui/Input';
import { RefreshCw, Calendar } from 'lucide-react';
import { DashboardFiltersState } from '../types';

interface DashboardFiltersProps {
  filters: DashboardFiltersState;
  onFilterChange: (filters: DashboardFiltersState) => void;
  onRefresh: () => void;
  isRefreshing?: boolean;
}

export const DashboardFilters = ({
  filters,
  onFilterChange,
  onRefresh,
  isRefreshing = false,
}: DashboardFiltersProps) => {
  const handleRangePreset = (preset: 'today' | 'week' | 'month' | 'custom') => {
    if (preset === 'custom') {
      onFilterChange({
        ...filters,
        dateRange: preset,
      });
    } else {
      onFilterChange({
        dateRange: preset,
        startDate: undefined,
        endDate: undefined,
      });
    }
  };

  const handleStartDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onFilterChange({
      ...filters,
      startDate: e.target.value,
    });
  };

  const handleEndDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onFilterChange({
      ...filters,
      endDate: e.target.value,
    });
  };

  return (
    <FilterBar className="flex items-center justify-between gap-4 w-full select-none" data-testid="dashboard-filters">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md bg-zinc-100 dark:bg-zinc-800 p-0.5 border border-border/80">
          {(['today', 'week', 'month', 'custom'] as const).map((preset) => {
            const isActive = filters.dateRange === preset;
            const labelMap = {
              today: 'Today',
              week: 'This Week',
              month: 'This Month',
              custom: 'Custom Range',
            };

            return (
              <button
                key={preset}
                type="button"
                onClick={() => handleRangePreset(preset)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                  isActive
                    ? 'bg-white dark:bg-zinc-700 text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
                data-testid={`filter-preset-${preset}`}
              >
                {labelMap[preset]}
              </button>
            );
          })}
        </div>

        {filters.dateRange === 'custom' && (
          <div className="flex items-center gap-2 transition-opacity duration-200">
            <Calendar className="h-4 w-4 text-muted-foreground ml-2" />
            <Input
              type="date"
              value={filters.startDate || ''}
              onChange={handleStartDateChange}
              className="h-8 py-1 px-2 text-xs w-36"
              placeholder="Start Date"
              data-testid="filter-start-date"
            />
            <span className="text-xs text-muted-foreground">to</span>
            <Input
              type="date"
              value={filters.endDate || ''}
              onChange={handleEndDateChange}
              className="h-8 py-1 px-2 text-xs w-36"
              placeholder="End Date"
              data-testid="filter-end-date"
            />
          </div>
        )}
      </div>

      <Button
        variant="outline"
        size="sm"
        leftIcon={<RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />}
        onClick={onRefresh}
        isLoading={isRefreshing}
        data-testid="filter-refresh-btn"
      >
        Refresh
      </Button>
    </FilterBar>
  );
};
