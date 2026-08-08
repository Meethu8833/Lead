import * as React from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../../components/ui/Dialog';
import { Button } from '../../../components/ui/Button';
import { CurrencyInput } from '../../../components/ui/CurrencyInput';
import { Input } from '../../../components/ui/Input';
import { Textarea } from '../../../components/ui/Textarea';
import { Badge } from '../../../components/ui/Badge';
import { ProductSelector } from './ProductSelector';
import { QuantityEditor } from './QuantityEditor';
import { DiscountEditor } from './DiscountEditor';
import { PriceBreakdown } from './PriceBreakdown';
import { orderItemEditSchema, OrderItemEditFormValues } from '../validation';
import { OrderItem, OrderItemUpdatePayload, Product, isProductionStageLocked } from '../types';
import { RotateCcw } from 'lucide-react';

interface OrderItemEditorProps {
  isOpen: boolean;
  item: OrderItem | null;
  products: Product[];
  onClose: () => void;
  onSave: (itemId: string, payload: OrderItemUpdatePayload) => Promise<void>;
  isSubmitting?: boolean;
}

const toFormValues = (item: OrderItem): OrderItemEditFormValues => ({
  product_id: item.product_id || '',
  unit_price: item.unit_price,
  quantity: item.quantity,
  discount: item.discount,
  album_size: item.album_size || '',
  sheet_type: item.sheet_type || '',
  cover_type: item.cover_type || '',
  remarks: item.remarks || '',
});

export const OrderItemEditor = ({ isOpen, item, products, onClose, onSave, isSubmitting = false }: OrderItemEditorProps) => {
  const locked = item ? isProductionStageLocked(item.production_stage) : false;

  const {
    register,
    handleSubmit,
    control,
    watch,
    reset,
    formState: { errors },
  } = useForm<OrderItemEditFormValues>({
    resolver: zodResolver(orderItemEditSchema),
    defaultValues: item ? toFormValues(item) : undefined,
  });

  React.useEffect(() => {
    if (isOpen && item) {
      reset(toFormValues(item));
    }
  }, [isOpen, item, reset]);

  const values = watch();
  const gross = (values.unit_price || 0) * (values.quantity || 0);

  const handleUndo = () => {
    if (item) reset(toFormValues(item));
  };

  const submitHandler = handleSubmit(async (formValues) => {
    if (!item) return;
    await onSave(item.id, {
      product_id: formValues.product_id,
      unit_price: formValues.unit_price,
      quantity: formValues.quantity,
      discount: formValues.discount,
      album_size: formValues.album_size || null,
      sheet_type: formValues.sheet_type || null,
      cover_type: formValues.cover_type || null,
      remarks: formValues.remarks || null,
    });
  });

  if (!item) return null;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !isSubmitting && onClose()}>
      <DialogContent size="lg" data-testid="order-item-editor">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Edit Order Item
            {locked && (
              <Badge variant="warning" size="sm" data-testid="order-item-editor-locked-badge">
                Locked
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {locked
              ? 'This item has reached the Packing stage or later and is treated as locked in the UI. It can still be viewed but not edited.'
              : 'Change the product, quantity, pricing, or discount for this line item.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submitHandler} className="space-y-4">
          <Controller
            control={control}
            name="product_id"
            render={({ field }) => (
              <ProductSelector
                products={products}
                value={field.value}
                onSelect={(product) => field.onChange(product.id)}
                disabled={locked || isSubmitting}
                error={errors.product_id?.message}
                required
              />
            )}
          />

          <div className="grid grid-cols-2 gap-4">
            <Controller
              control={control}
              name="quantity"
              render={({ field }) => (
                <QuantityEditor
                  label="Quantity"
                  value={field.value}
                  onChange={field.onChange}
                  disabled={locked || isSubmitting}
                  error={errors.quantity?.message}
                  fullWidth
                  data-testid="order-item-editor-quantity"
                />
              )}
            />

            <Controller
              control={control}
              name="unit_price"
              render={({ field }) => (
                <CurrencyInput
                  label="Unit Price"
                  value={field.value}
                  onChangeValue={(val) => field.onChange(val ?? 0)}
                  disabled={locked || isSubmitting}
                  error={errors.unit_price?.message}
                  fullWidth
                  data-testid="order-item-editor-unit-price"
                />
              )}
            />
          </div>

          <Controller
            control={control}
            name="discount"
            render={({ field }) => (
              <DiscountEditor
                value={field.value}
                max={gross}
                onChange={field.onChange}
                disabled={locked || isSubmitting}
                error={errors.discount?.message}
                data-testid="order-item-editor-discount"
              />
            )}
          />

          <PriceBreakdown unitPrice={values.unit_price || 0} quantity={values.quantity || 0} discount={values.discount || 0} />

          <div className="grid grid-cols-3 gap-4">
            <Input label="Album Size" disabled={locked || isSubmitting} {...register('album_size')} fullWidth data-testid="order-item-editor-album-size" />
            <Input label="Sheet Type" disabled={locked || isSubmitting} {...register('sheet_type')} fullWidth data-testid="order-item-editor-sheet-type" />
            <Input label="Cover Type" disabled={locked || isSubmitting} {...register('cover_type')} fullWidth data-testid="order-item-editor-cover-type" />
          </div>

          <Textarea label="Remarks" disabled={locked || isSubmitting} {...register('remarks')} fullWidth data-testid="order-item-editor-remarks" />

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              leftIcon={<RotateCcw className="h-4 w-4" />}
              onClick={handleUndo}
              disabled={locked || isSubmitting}
              data-testid="order-item-editor-undo"
            >
              Undo Changes
            </Button>
            <Button type="button" variant="outline" onClick={onClose} disabled={isSubmitting} data-testid="order-item-editor-cancel">
              Cancel
            </Button>
            <Button type="submit" isLoading={isSubmitting} disabled={locked} data-testid="order-item-editor-save">
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
