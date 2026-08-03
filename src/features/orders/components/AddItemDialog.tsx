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
import { NumberInput } from '../../../components/ui/NumberInput';
import { CurrencyInput } from '../../../components/ui/CurrencyInput';
import { Input } from '../../../components/ui/Input';
import { Textarea } from '../../../components/ui/Textarea';
import { ProductSelector } from './ProductSelector';
import { DiscountEditor } from './DiscountEditor';
import { PriceSummary } from './PriceSummary';
import { addItemSchema, AddItemFormValues } from '../validation';
import { OrderItemCreatePayload, Product } from '../types';

interface AddItemDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (payload: OrderItemCreatePayload) => Promise<void>;
  products: Product[];
  isSubmitting?: boolean;
}

export const AddItemDialog = ({ isOpen, onClose, onSubmit, products, isSubmitting = false }: AddItemDialogProps) => {
  const {
    register,
    handleSubmit,
    control,
    watch,
    reset,
    setError,
    formState: { errors },
  } = useForm<AddItemFormValues>({
    resolver: zodResolver(addItemSchema),
    defaultValues: {
      product_id: '',
      quantity: 1,
      discount: 0,
    },
  });

  React.useEffect(() => {
    if (isOpen) {
      reset({ product_id: '', quantity: 1, discount: 0 });
    }
  }, [isOpen, reset]);

  const [selectedProductId, quantity, unitPrice, discount] = watch(['product_id', 'quantity', 'unit_price', 'discount']);
  const selectedProduct = products.find((p) => p.id === selectedProductId);
  const effectiveUnitPrice = unitPrice ?? selectedProduct?.base_price ?? 0;
  const grossAmount = effectiveUnitPrice * (quantity || 0);

  const submitHandler = handleSubmit(async (values) => {
    const effectivePrice = values.unit_price ?? selectedProduct?.base_price ?? 0;
    const gross = effectivePrice * values.quantity;
    if (values.discount > gross) {
      setError('discount', {
        type: 'manual',
        message: "Discount cannot exceed the item's gross amount.",
      });
      return;
    }

    await onSubmit({
      product_id: values.product_id,
      unit_price: values.unit_price,
      quantity: values.quantity,
      discount: values.discount,
      album_size: values.album_size || undefined,
      sheet_type: values.sheet_type || undefined,
      cover_type: values.cover_type || undefined,
      remarks: values.remarks || undefined,
    });
  });

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !isSubmitting && onClose()}>
      <DialogContent size="lg" data-testid="add-item-dialog">
        <DialogHeader>
          <DialogTitle>Add Order Item</DialogTitle>
          <DialogDescription>Select a product from the catalog and configure the line item.</DialogDescription>
        </DialogHeader>

        <form onSubmit={submitHandler} className="space-y-4">
          <Controller
            control={control}
            name="product_id"
            render={({ field }) => (
              <ProductSelector
                value={field.value}
                onSelect={(product) => field.onChange(product.id)}
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
                <NumberInput
                  label="Quantity"
                  required
                  min={1}
                  step={1}
                  value={field.value}
                  onChange={(val) => field.onChange(val ?? 1)}
                  error={errors.quantity?.message}
                  fullWidth
                  data-testid="add-item-quantity"
                />
              )}
            />

            <Controller
              control={control}
              name="unit_price"
              render={({ field }) => (
                <CurrencyInput
                  label="Unit Price"
                  helperText={selectedProduct ? `Catalog price: ${selectedProduct.base_price}` : 'Leave blank to use catalog price'}
                  value={field.value ?? null}
                  onChangeValue={(val) => field.onChange(val ?? undefined)}
                  error={errors.unit_price?.message}
                  fullWidth
                  data-testid="add-item-unit-price"
                />
              )}
            />
          </div>

          <Controller
            control={control}
            name="discount"
            render={({ field }) => (
              <DiscountEditor
                value={field.value ?? 0}
                max={grossAmount}
                onChange={field.onChange}
                error={errors.discount?.message}
                data-testid="add-item-discount"
              />
            )}
          />

          <PriceSummary unitPrice={effectiveUnitPrice} quantity={quantity || 0} discount={discount || 0} />

          <div className="grid grid-cols-3 gap-4">
            <Input label="Album Size" {...register('album_size')} fullWidth data-testid="add-item-album-size" />
            <Input label="Sheet Type" {...register('sheet_type')} fullWidth data-testid="add-item-sheet-type" />
            <Input label="Cover Type" {...register('cover_type')} fullWidth data-testid="add-item-cover-type" />
          </div>

          <Textarea label="Remarks" {...register('remarks')} fullWidth data-testid="add-item-remarks" />

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={isSubmitting} data-testid="add-item-cancel">
              Cancel
            </Button>
            <Button type="submit" isLoading={isSubmitting} data-testid="add-item-submit">
              Add Item
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
