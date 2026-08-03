import * as React from 'react';
import { SearchBox } from '../../../components/ui/SearchBox';
import { Select } from '../../../components/ui/Select';
import { cn } from '../../../utils/cn';
import { formatCurrency } from '../../../utils/helpers';
import { Product } from '../types';
import { getRecentProductIds, addRecentProductId } from '../recentProducts';

interface ProductSelectorProps {
  products: Product[];
  value: string;
  onSelect: (product: Product) => void;
  disabled?: boolean;
  error?: string;
  label?: string;
  required?: boolean;
}

// Client-side search/filter over the already-fetched product catalog (same "no server-side
// pagination/filtering" convention the Orders foundation phase established for orders — see
// task.md gap #4 — since GET /products/search has no total-count/cursor support either).
export const ProductSelector = ({
  products,
  value,
  onSelect,
  disabled = false,
  error,
  label = 'Product',
  required,
}: ProductSelectorProps) => {
  const [searchTerm, setSearchTerm] = React.useState('');
  const [category, setCategory] = React.useState('');
  const [isOpen, setIsOpen] = React.useState(false);
  const [activeIndex, setActiveIndex] = React.useState(0);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const categories = React.useMemo(
    () => Array.from(new Set(products.map((p) => p.category))).sort(),
    [products]
  );

  const filtered = React.useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return products.filter((p) => {
      if (category && p.category !== category) return false;
      if (!term) return true;
      return p.name.toLowerCase().includes(term) || p.category.toLowerCase().includes(term);
    });
  }, [products, searchTerm, category]);

  const recentProducts = React.useMemo(() => {
    if (searchTerm) return [];
    const recentIds = getRecentProductIds();
    return recentIds
      .map((id) => products.find((p) => p.id === id && (!category || p.category === category)))
      .filter((p): p is Product => !!p);
  }, [products, searchTerm, category]);

  const visibleProducts = recentProducts.length > 0 ? recentProducts : filtered;
  const selectedProduct = products.find((p) => p.id === value);

  React.useEffect(() => {
    setActiveIndex(0);
  }, [searchTerm, category, isOpen]);

  React.useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = (product: Product) => {
    addRecentProductId(product.id);
    onSelect(product);
    setIsOpen(false);
    setSearchTerm('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setIsOpen(true);
        e.preventDefault();
      }
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, visibleProducts.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const product = visibleProducts[activeIndex];
      if (product) handleSelect(product);
    } else if (e.key === 'Escape') {
      setIsOpen(false);
    }
  };

  return (
    <div className="flex flex-col gap-1.5" ref={containerRef} data-testid="product-selector">
      {label && (
        <label className="text-sm font-medium text-foreground select-none">
          {label}
          {required && <span className="text-destructive ml-1">*</span>}
        </label>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-[1fr,160px] gap-2">
        <SearchBox
          placeholder={selectedProduct ? selectedProduct.name : 'Search products by name or category...'}
          onSearch={(term) => {
            setSearchTerm(term);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          showShortcut={false}
          data-testid="product-selector-search"
        />
        <Select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          disabled={disabled}
          placeholder="All categories"
          options={categories.map((c) => ({ label: c, value: c }))}
          data-testid="product-selector-category"
        />
      </div>

      {isOpen && !disabled && (
        <div className="relative" data-testid="product-selector-dropdown-anchor">
          <div
            className="absolute z-20 mt-1 w-full max-h-64 overflow-y-auto rounded-md border border-border bg-popover shadow-lg"
            role="listbox"
            data-testid="product-selector-list"
          >
            {recentProducts.length > 0 && (
              <div className="px-3 py-1.5 text-xs font-semibold text-muted-foreground" data-testid="product-selector-recent-label">
                Recently Used
              </div>
            )}

            {visibleProducts.length === 0 ? (
              <div className="px-3 py-4 text-sm text-muted-foreground text-center">No products found</div>
            ) : (
              visibleProducts.map((product, idx) => (
                <button
                  key={product.id}
                  type="button"
                  role="option"
                  aria-selected={value === product.id}
                  onMouseEnter={() => setActiveIndex(idx)}
                  onClick={() => handleSelect(product)}
                  className={cn(
                    'flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition-colors',
                    idx === activeIndex ? 'bg-muted' : 'hover:bg-muted',
                    value === product.id && 'font-semibold text-primary'
                  )}
                  data-testid={`product-selector-option-${product.id}`}
                >
                  <span className="flex flex-col min-w-0">
                    <span className="truncate">{product.name}</span>
                    <span className="text-xs text-muted-foreground truncate">
                      {product.category}
                      {!product.is_active ? ' · Inactive' : ''}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs font-medium text-muted-foreground">
                    {formatCurrency(product.base_price)}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {selectedProduct && (
        <div className="text-xs text-muted-foreground" data-testid="product-selector-selected">
          Selected: <span className="font-medium text-foreground">{selectedProduct.name}</span> · Catalog price{' '}
          {formatCurrency(selectedProduct.base_price)}
        </div>
      )}

      {error && (
        <p className="text-xs font-medium text-destructive mt-0.5" data-testid="product-selector-error">
          {error}
        </p>
      )}
    </div>
  );
};
