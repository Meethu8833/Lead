import { ConfirmationDialog } from '../../../components/ui/ConfirmationDialog';
import { Order } from '../types';

interface DeleteOrderDialogProps {
  order: Order | null;
  isOpen: boolean;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
  isLoading?: boolean;
}

export const DeleteOrderDialog = ({ order, isOpen, onConfirm, onCancel, isLoading = false }: DeleteOrderDialogProps) => {
  return (
    <ConfirmationDialog
      isOpen={isOpen}
      variant="danger"
      title="Delete Order"
      description={
        order
          ? `Are you sure you want to delete order "${order.order_number}" (${order.job_name})? This action cannot be undone.`
          : ''
      }
      confirmText="Delete Order"
      cancelText="Cancel"
      onConfirm={onConfirm}
      onCancel={onCancel}
      isLoading={isLoading}
    />
  );
};
