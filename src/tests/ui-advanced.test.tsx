import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act, within } from '@testing-library/react';

// Setup browser API mocks for JSDOM
if (typeof window !== 'undefined') {
  if (!window.PointerEvent) {
    class MockPointerEvent extends Event {
      button: number;
      ctrlKey: boolean;
      pointerType: string;
      constructor(type: string, props: any = {}) {
        super(type, props);
        this.button = props.button || 0;
        this.ctrlKey = props.ctrlKey || false;
        this.pointerType = props.pointerType || 'mouse';
      }
    }
    window.PointerEvent = MockPointerEvent as any;
  }

  window.ResizeObserver = window.ResizeObserver || class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

import {
  DataTable,
  Pagination,
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
  Drawer,
  DrawerTrigger,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerFooter,
  DrawerClose,
  ConfirmationDialog,
  AlertDialog,
  LoadingOverlay,
  ProgressBar,
  Timeline,
  Breadcrumb,
  StatCard,
  KpiCard,
  FilePreview,
  ImagePreview,
} from '../components/ui';

describe('Pagination Component', () => {
  it('renders total records, pages list, size options', () => {
    const handlePageChange = vi.fn();
    const handlePageSizeChange = vi.fn();

    render(
      <Pagination
        page={2}
        pageSize={10}
        totalItems={45}
        onPageChange={handlePageChange}
        onPageSizeChange={handlePageSizeChange}
      />
    );

    // Verify info text
    expect(screen.getByTestId('pagination-info')).toHaveTextContent(
      'Showing 11 to 20 of 45 entries'
    );

    // Verify limit selector exists
    expect(screen.getByTestId('pagination-limit-selector')).toBeInTheDocument();

    // Verify pagination page buttons
    const prevBtn = screen.getByTestId('pagination-prev');
    const nextBtn = screen.getByTestId('pagination-next');
    const firstBtn = screen.getByTestId('pagination-first');
    const lastBtn = screen.getByTestId('pagination-last');

    expect(prevBtn).not.toBeDisabled();
    expect(nextBtn).not.toBeDisabled();
    expect(firstBtn).not.toBeDisabled();
    expect(lastBtn).not.toBeDisabled();

    // Trigger actions
    fireEvent.click(prevBtn);
    expect(handlePageChange).toHaveBeenCalledWith(1);

    fireEvent.click(nextBtn);
    expect(handlePageChange).toHaveBeenCalledWith(3);

    fireEvent.click(firstBtn);
    expect(handlePageChange).toHaveBeenCalledWith(1);

    fireEvent.click(lastBtn);
    expect(handlePageChange).toHaveBeenCalledWith(5);
  });
});

describe('DataTable Component', () => {
  interface RowData {
    id: number;
    name: string;
    role: string;
    status: string;
  }

  const columns = [
    { header: 'ID', accessorKey: 'id', sortable: true },
    { header: 'Name', accessorKey: 'name', sortable: true },
    { header: 'Role', accessorKey: 'role' },
    { header: 'Status', accessorKey: 'status' },
  ];

  const data: RowData[] = [
    { id: 1, name: 'Alice Smith', role: 'Admin', status: 'Active' },
    { id: 2, name: 'Bob Jones', role: 'User', status: 'Inactive' },
    { id: 3, name: 'Charlie Brown', role: 'User', status: 'Active' },
  ];

  it('renders standard table rows and column headings', () => {
    render(<DataTable columns={columns} data={data} />);

    // Verify header columns
    expect(screen.getByTestId('table-th-id')).toHaveTextContent('ID');
    expect(screen.getByTestId('table-th-name')).toHaveTextContent('Name');

    // Verify rows count
    const rows = screen.getAllByRole('row');
    // 1 header row + 3 data rows = 4 rows total
    expect(rows).toHaveLength(4);

    expect(screen.getByText('Alice Smith')).toBeInTheDocument();
    expect(screen.getByText('Bob Jones')).toBeInTheDocument();
  });

  it('renders loading skeleton rows', () => {
    render(<DataTable columns={columns} data={[]} loading={true} />);
    const skeletons = screen.getAllByTestId('skeleton');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('renders empty component fallback when data is empty', () => {
    render(
      <DataTable
        columns={columns}
        data={[]}
        emptyComponent={<div data-testid="custom-empty">Nothing here!</div>}
      />
    );
    expect(screen.getByTestId('custom-empty')).toBeInTheDocument();
  });

  it('handles client-side sorting', () => {
    render(<DataTable columns={columns} data={data} />);

    // Initially order is Alice (1), Bob (2), Charlie (3)
    const getRowTexts = () =>
      screen
        .getAllByRole('row')
        .slice(1) // exclude header row
        .map((row) => within(row).getAllByRole('cell')[0].textContent);

    expect(getRowTexts()).toEqual(['1', '2', '3']);

    // Sort by ID (descending)
    const idHeader = screen.getByTestId('table-th-id');
    fireEvent.click(idHeader); // Asc -> Desc or Asc depending on state. It defaults to ascending. Let's see: click once.
    // If it defaults to sorting ascending, click again for descending.
    fireEvent.click(idHeader);
    expect(getRowTexts()).toEqual(['3', '2', '1']);
  });

  it('triggers selection change on master and individual checkbox click', () => {
    const handleSelectionChange = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={data}
        selectedRows={[1]}
        onSelectionChange={handleSelectionChange}
      />
    );

    // Alice checkbox should be checked
    const selectAllCheckbox = screen.getByTestId('table-select-all');
    const row1Checkbox = screen.getByTestId('table-row-select-1');
    const row2Checkbox = screen.getByTestId('table-row-select-2');

    expect(row1Checkbox).toBeChecked();
    expect(row2Checkbox).not.toBeChecked();

    // Check row 2
    fireEvent.click(row2Checkbox!);
    expect(handleSelectionChange).toHaveBeenCalledWith([1, 2]);

    // Check all
    fireEvent.click(selectAllCheckbox!);
    expect(handleSelectionChange).toHaveBeenCalledWith([1, 2, 3]);
  });
});

describe('Dialog Component', () => {
  it('opens and closes modal content correctly', () => {
    render(
      <Dialog>
        <DialogTrigger data-testid="dialog-trigger">Open Dialog</DialogTrigger>
        <DialogContent data-testid="dialog-content">
          <DialogHeader>
            <DialogTitle>Dialog Title</DialogTitle>
            <DialogDescription>Dialog Desc</DialogDescription>
          </DialogHeader>
          <div>Main Dialog Body</div>
          <DialogFooter>
            <DialogClose data-testid="dialog-close">Close</DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );

    // Initial state: Content is not in the DOM
    expect(screen.queryByTestId('dialog-content')).not.toBeInTheDocument();

    // Open
    fireEvent.click(screen.getByTestId('dialog-trigger'));
    expect(screen.getByTestId('dialog-content')).toBeInTheDocument();
    expect(screen.getByText('Dialog Title')).toBeInTheDocument();

    // Close
    fireEvent.click(screen.getByTestId('dialog-close'));
    expect(screen.queryByTestId('dialog-content')).not.toBeInTheDocument();
  });
});

describe('Drawer Component', () => {
  it('opens, slides in drawer and displays contents', () => {
    render(
      <Drawer>
        <DrawerTrigger data-testid="drawer-trigger">Open Drawer</DrawerTrigger>
        <DrawerContent position="right" data-testid="drawer-content">
          <DrawerHeader>
            <DrawerTitle>Drawer Title</DrawerTitle>
            <DrawerDescription>Drawer Description</DrawerDescription>
          </DrawerHeader>
          <div>Drawer Content Body</div>
          <DrawerFooter>
            <DrawerClose data-testid="drawer-close">Dismiss</DrawerClose>
          </DrawerFooter>
        </DrawerContent>
      </Drawer>
    );

    expect(screen.queryByTestId('drawer-content')).not.toBeInTheDocument();

    // Open
    fireEvent.click(screen.getByTestId('drawer-trigger'));
    expect(screen.getByTestId('drawer-content')).toBeInTheDocument();
    expect(screen.getByText('Drawer Title')).toBeInTheDocument();

    // Close
    fireEvent.click(screen.getByTestId('drawer-close'));
    expect(screen.queryByTestId('drawer-content')).not.toBeInTheDocument();
  });
});

describe('ConfirmationDialog Component', () => {
  it('renders confirmation text, handles cancel and async confirmation triggers', async () => {
    const handleConfirm = vi.fn().mockImplementation(() => Promise.resolve());
    const handleCancel = vi.fn();

    const { rerender } = render(
      <ConfirmationDialog
        isOpen={true}
        title="Confirm Operation"
        description="Are you sure you want to perform this task?"
        onConfirm={handleConfirm}
        onCancel={handleCancel}
        variant="danger"
        confirmText="Yes, delete"
        cancelText="No, wait"
      />
    );

    expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
    expect(screen.getByText('Confirm Operation')).toBeInTheDocument();
    expect(screen.getByText('Are you sure you want to perform this task?')).toBeInTheDocument();

    const confirmBtn = screen.getByTestId('confirmation-confirm');
    const cancelBtn = screen.getByTestId('confirmation-cancel');

    expect(confirmBtn).toHaveTextContent('Yes, delete');
    expect(cancelBtn).toHaveTextContent('No, wait');

    // Confirm click triggers callback
    await act(async () => {
      fireEvent.click(confirmBtn);
    });
    expect(handleConfirm).toHaveBeenCalledTimes(1);

    // Cancel click triggers callback
    fireEvent.click(cancelBtn);
    expect(handleCancel).toHaveBeenCalledTimes(1);

    // Test external loading state
    rerender(
      <ConfirmationDialog
        isOpen={true}
        title="Confirm Operation"
        description="Are you sure you want to perform this task?"
        onConfirm={handleConfirm}
        onCancel={handleCancel}
        isLoading={true}
      />
    );
    expect(screen.getByTestId('confirmation-confirm')).toBeDisabled();
    expect(screen.getByTestId('confirmation-cancel')).toBeDisabled();
  });
});

describe('AlertDialog Component', () => {
  it('renders warning single ack alerts', () => {
    const handleAck = vi.fn();

    render(
      <AlertDialog
        isOpen={true}
        title="Access Denied"
        description="You do not have permission to view this panel."
        onAcknowledge={handleAck}
        variant="error"
        acknowledgeText="Understood"
      />
    );

    expect(screen.getByTestId('alert-dialog')).toBeInTheDocument();
    expect(screen.getByText('Access Denied')).toBeInTheDocument();

    const ackBtn = screen.getByTestId('alert-acknowledge');
    expect(ackBtn).toHaveTextContent('Understood');

    fireEvent.click(ackBtn);
    expect(handleAck).toHaveBeenCalledTimes(1);
  });
});

describe('LoadingOverlay Component', () => {
  it('renders overlay message, spinner, and blur styling', () => {
    const { rerender } = render(
      <LoadingOverlay visible={true} message="Saving changes..." blur={true} />
    );

    const overlay = screen.getByTestId('loading-overlay');
    expect(overlay).toBeInTheDocument();
    expect(overlay).toHaveClass('backdrop-blur-sm');
    expect(screen.getByTestId('loading-overlay-spinner')).toBeInTheDocument();
    expect(screen.getByTestId('loading-overlay-message')).toHaveTextContent('Saving changes...');

    rerender(<LoadingOverlay visible={false} />);
    expect(screen.queryByTestId('loading-overlay')).not.toBeInTheDocument();
  });
});

describe('ProgressBar Component', () => {
  it('renders determinate and indeterminate progress bars', () => {
    const { rerender } = render(
      <ProgressBar value={45} max={100} showPercentage={true} label="Uploading file" />
    );

    expect(screen.getByTestId('progress-bar-label')).toHaveTextContent('Uploading file');
    expect(screen.getByTestId('progress-bar-percentage')).toHaveTextContent('45%');
    
    const indicator = screen.getByTestId('progress-bar-indicator-determinate');
    expect(indicator).toHaveStyle('width: 45%');

    // Rerender as indeterminate
    rerender(<ProgressBar variant="indeterminate" />);
    expect(screen.getByTestId('progress-bar-indicator-indeterminate')).toBeInTheDocument();
  });
});

describe('Timeline Component', () => {
  it('renders milestones list with completed, current, and upcoming indicators', () => {
    const items = [
      { id: '1', title: 'Step 1: Order Created', timestamp: '10:00 AM', status: 'completed' as const },
      { id: '2', title: 'Step 2: Processing Payment', timestamp: '10:05 AM', status: 'current' as const },
      { id: '3', title: 'Step 3: Ready for Delivery', status: 'upcoming' as const },
    ];

    render(<Timeline items={items} />);

    expect(screen.getByTestId('timeline')).toBeInTheDocument();
    expect(screen.getByText('Step 1: Order Created')).toBeInTheDocument();
    expect(screen.getByText('Step 2: Processing Payment')).toBeInTheDocument();
    expect(screen.getByText('Step 3: Ready for Delivery')).toBeInTheDocument();

    // Check statuses
    expect(screen.getAllByTestId('timeline-item-completed')).toHaveLength(1);
    expect(screen.getAllByTestId('timeline-item-current')).toHaveLength(1);
    expect(screen.getAllByTestId('timeline-item-upcoming')).toHaveLength(1);
  });
});

describe('Breadcrumb Component', () => {
  it('renders breadcrumb segments, custom separator and ellipses', () => {
    const items = [
      { label: 'ERP Panel', href: '/erp' },
      { label: 'Inventory', href: '/erp/inventory' },
      { label: 'Chemicals', href: '/erp/inventory/chemicals' },
      { label: 'Item details', isCurrent: true },
    ];

    const { rerender } = render(<Breadcrumb items={items} showHome={true} />);

    // Contains home link
    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.getByText('ERP Panel')).toBeInTheDocument();
    expect(screen.getByText('Item details')).toBeInTheDocument();

    // Contains separators
    const separators = screen.getAllByTestId('breadcrumb-separator');
    expect(separators.length).toBeGreaterThan(0);

    // Rerender with max items to check ellipsis
    rerender(<Breadcrumb items={items} maxItems={3} showHome={true} />);
    expect(screen.getByTestId('breadcrumb-ellipsis')).toBeInTheDocument();
  });
});

describe('StatCard Component', () => {
  it('renders title, value, icon, loading skeletons, trend, and footer content', () => {
    const { rerender } = render(
      <StatCard
        title="Total Sales"
        value="$24,500"
        trend={{ value: '+14.5%', direction: 'up', label: 'vs last week' }}
        footer="Updated just now"
        icon={<span data-testid="sales-icon">$$</span>}
      />
    );

    expect(screen.getByTestId('stat-card-title')).toHaveTextContent('Total Sales');
    expect(screen.getByTestId('stat-card-value')).toHaveTextContent('$24,500');
    expect(screen.getByTestId('stat-card-icon')).toBeInTheDocument();
    expect(screen.getByTestId('stat-trend-up')).toHaveTextContent('+14.5%');
    expect(screen.getByTestId('stat-trend-label')).toHaveTextContent('vs last week');
    expect(screen.getByTestId('stat-card-footer')).toHaveTextContent('Updated just now');

    // Rerender as loading skeleton
    rerender(<StatCard title="Total Sales" value="$24,500" loading={true} />);
    expect(screen.getByTestId('stat-card-skeleton')).toBeInTheDocument();
  });
});

describe('KpiCard Component', () => {
  it('extends StatCard, supports percentage comparisons and mini sparkline placeholder', () => {
    render(
      <KpiCard
        title="Active Users"
        value="1,240"
        percentageChange={12.5}
        comparisonLabel="vs target"
        miniChartPlaceholder={<div data-testid="sparkline">sparkline-chart</div>}
      />
    );

    expect(screen.getByTestId('stat-card-title')).toHaveTextContent('Active Users');
    expect(screen.getByTestId('stat-card-value')).toHaveTextContent('1,240');
    expect(screen.getByTestId('stat-trend-up')).toHaveTextContent('+12.5%');
    expect(screen.getByTestId('stat-trend-label')).toHaveTextContent('vs target');
    expect(screen.getByTestId('sparkline')).toBeInTheDocument();
  });
});

describe('FilePreview Component', () => {
  it('renders name, size, type-appropriate icons and executes action clicks', () => {
    const handleDownload = vi.fn();
    const handleDelete = vi.fn();
    const handleView = vi.fn();

    render(
      <FilePreview
        name="specification.pdf"
        size={1204500}
        type="application/pdf"
        onDownload={handleDownload}
        onDelete={handleDelete}
        onView={handleView}
      />
    );

    expect(screen.getByTestId('file-preview-name')).toHaveTextContent('specification.pdf');
    // 1204500 bytes ~ 1.1 MB
    expect(screen.getByTestId('file-preview-size')).toHaveTextContent('1.1 MB');

    // Action buttons
    const viewBtn = screen.getByTestId('file-preview-view');
    const downloadBtn = screen.getByTestId('file-preview-download');
    const deleteBtn = screen.getByTestId('file-preview-delete');

    fireEvent.click(viewBtn);
    expect(handleView).toHaveBeenCalledTimes(1);

    fireEvent.click(downloadBtn);
    expect(handleDownload).toHaveBeenCalledTimes(1);

    fireEvent.click(deleteBtn);
    expect(handleDelete).toHaveBeenCalledTimes(1);
  });
});

describe('ImagePreview Component', () => {
  it('renders thumbnail, handles remove event, fallback state, and opens zoomable lightbox', () => {
    const handleRemove = vi.fn();

    const { rerender } = render(
      <ImagePreview
        src="https://example.com/image.png"
        alt="User Image"
        onRemove={handleRemove}
      />
    );

    const thumbnailImg = screen.getByTestId('image-preview-thumbnail');
    expect(thumbnailImg).toBeInTheDocument();
    expect(thumbnailImg).toHaveAttribute('src', 'https://example.com/image.png');

    // Trigger image loading failure
    fireEvent.error(thumbnailImg);
    expect(screen.getByTestId('image-preview-fallback')).toBeInTheDocument();

    // Rerender working thumbnail and click it to open lightbox
    rerender(
      <ImagePreview
        src="https://example.com/image-ok.png"
        alt="User Image OK"
        onRemove={handleRemove}
      />
    );

    const activeThumbnail = screen.getByTestId('image-preview-thumbnail');
    fireEvent.click(activeThumbnail);

    // Lightbox should now be visible in DOM
    const lightboxImg = screen.getByTestId('image-preview-lightbox-img');
    expect(lightboxImg).toBeInTheDocument();
    expect(lightboxImg).toHaveAttribute('src', 'https://example.com/image-ok.png');

    // Zoom interaction
    const zoomInBtn = screen.getByTestId('image-preview-zoom-in');
    const zoomOutBtn = screen.getByTestId('image-preview-zoom-out');
    const zoomResetBtn = screen.getByTestId('image-preview-zoom-reset');
    const zoomScale = screen.getByTestId('image-preview-zoom-scale');

    expect(zoomScale).toHaveTextContent('100%');

    fireEvent.click(zoomInBtn);
    expect(zoomScale).toHaveTextContent('125%');

    fireEvent.click(zoomOutBtn);
    expect(zoomScale).toHaveTextContent('100%');

    fireEvent.click(zoomInBtn);
    fireEvent.click(zoomInBtn);
    expect(zoomScale).toHaveTextContent('150%');

    fireEvent.click(zoomResetBtn);
    expect(zoomScale).toHaveTextContent('100%');

    // Remove trigger
    const removeBtn = screen.getByTestId('image-preview-remove');
    fireEvent.click(removeBtn);
    expect(handleRemove).toHaveBeenCalledTimes(1);
  });
});
