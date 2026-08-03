import { FilterBar } from '../../../components/ui/LayoutHelpers';
import { SearchBox } from '../../../components/ui/SearchBox';
import { Select } from '../../../components/ui/Select';
import { Input } from '../../../components/ui/Input';
import { Button } from '../../../components/ui/Button';
import { X } from 'lucide-react';
import { DEFAULT_ORDER_FILTERS, ORDER_STATUSES, OrderFiltersState, PAYMENT_STATUSES, Photographer } from '../types';

interface OrderFiltersProps {
  filters: OrderFiltersState;
  onFilterChange: (filters: OrderFiltersState) => void;
  photographers: Photographer[];
}

const isDefaultFilters = (filters: OrderFiltersState) =>
  Object.entries(filters).every(
    ([key, value]) => value === (DEFAULT_ORDER_FILTERS as any)[key]
  );

export const OrderFilters = ({ filters, onFilterChange, photographers }: OrderFiltersProps) => {
  const update = (patch: Partial<OrderFiltersState>) => onFilterChange({ ...filters, ...patch });

  return (
    <FilterBar className="flex flex-col gap-3 w-full" data-testid="order-filters">
      <div className="flex flex-wrap items-center gap-3 w-full">
        <SearchBox
          defaultValue={filters.search}
          onSearch={(value) => update({ search: value })}
          placeholder="Search by order number, job name, photographer..."
          className="min-w-[260px] flex-1"
          data-testid="order-filter-search"
        />

        <Select
          placeholder="Status / Production Stage"
          value={filters.status}
          onChange={(e) => update({ status: e.target.value as OrderFiltersState['status'] })}
          options={ORDER_STATUSES.map((s) => ({ label: s.replace(/_/g, ' '), value: s }))}
          className="w-52"
          data-testid="order-filter-status"
        />

        <Select
          placeholder="Payment Status"
          value={filters.paymentStatus}
          onChange={(e) => update({ paymentStatus: e.target.value as OrderFiltersState['paymentStatus'] })}
          options={PAYMENT_STATUSES.map((s) => ({ label: s.replace(/_/g, ' '), value: s }))}
          className="w-48"
          data-testid="order-filter-payment-status"
        />

        <Select
          placeholder="Photographer"
          value={filters.photographerId}
          onChange={(e) => update({ photographerId: e.target.value })}
          options={photographers.map((p) => ({ label: `${p.name} (${p.studio_name})`, value: p.id }))}
          className="w-56"
          data-testid="order-filter-photographer"
        />

        <Button
          variant="outline"
          size="sm"
          leftIcon={<X className="h-4 w-4" />}
          onClick={() => onFilterChange(DEFAULT_ORDER_FILTERS)}
          disabled={isDefaultFilters(filters)}
          data-testid="order-filter-clear"
        >
          Clear Filters
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground shrink-0">Booking Date</span>
          <Input
            type="date"
            value={filters.bookingDateFrom}
            onChange={(e) => update({ bookingDateFrom: e.target.value })}
            className="h-9 w-36 text-xs"
            data-testid="order-filter-booking-from"
          />
          <span className="text-xs text-muted-foreground">to</span>
          <Input
            type="date"
            value={filters.bookingDateTo}
            onChange={(e) => update({ bookingDateTo: e.target.value })}
            className="h-9 w-36 text-xs"
            data-testid="order-filter-booking-to"
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground shrink-0">Expected Delivery</span>
          <Input
            type="date"
            value={filters.expectedDeliveryFrom}
            onChange={(e) => update({ expectedDeliveryFrom: e.target.value })}
            className="h-9 w-36 text-xs"
            data-testid="order-filter-delivery-from"
          />
          <span className="text-xs text-muted-foreground">to</span>
          <Input
            type="date"
            value={filters.expectedDeliveryTo}
            onChange={(e) => update({ expectedDeliveryTo: e.target.value })}
            className="h-9 w-36 text-xs"
            data-testid="order-filter-delivery-to"
          />
        </div>
      </div>
    </FilterBar>
  );
};
