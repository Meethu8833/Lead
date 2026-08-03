import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';

vi.mock('@radix-ui/react-avatar', () => {
  return {
    Root: React.forwardRef(({ children, className, ...props }: any, ref: any) => (
      <span ref={ref} className={className} {...props}>
        {children}
      </span>
    )),
    Image: ({ src, className, ...props }: any) => (
      src ? <img src={src} className={className} {...props} /> : null
    ),
    Fallback: ({ children, className, ...props }: any) => (
      <span className={className} {...props}>
        {children}
      </span>
    ),
  };
});

import {
  Button,
  Badge,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
  Spinner,
  Skeleton,
  EmptyState,
  ErrorState,
  Avatar,
  StatusBadge,
} from '../components/ui';

describe('Spinner Component', () => {
  it('renders correctly', () => {
    render(<Spinner />);
    const spinner = screen.getByTestId('spinner');
    expect(spinner).toBeInTheDocument();
    expect(spinner).toHaveClass('animate-spin');
  });

  it('applies size classes correctly', () => {
    const { rerender } = render(<Spinner size="sm" />);
    expect(screen.getByTestId('spinner')).toHaveClass('h-4', 'w-4');

    rerender(<Spinner size="md" />);
    expect(screen.getByTestId('spinner')).toHaveClass('h-6', 'w-6');

    rerender(<Spinner size="lg" />);
    expect(screen.getByTestId('spinner')).toHaveClass('h-8', 'w-8');
  });
});

describe('Button Component', () => {
  it('renders children content', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('supports variants styling classes', () => {
    const { rerender } = render(<Button variant="primary">Btn</Button>);
    expect(screen.getByRole('button')).toHaveClass('bg-primary');

    rerender(<Button variant="secondary">Btn</Button>);
    expect(screen.getByRole('button')).toHaveClass('bg-secondary');

    rerender(<Button variant="danger">Btn</Button>);
    expect(screen.getByRole('button')).toHaveClass('bg-destructive');

    rerender(<Button variant="success">Btn</Button>);
    expect(screen.getByRole('button')).toHaveClass('bg-emerald-600');
  });

  it('triggers click handler when clicked', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click me</Button>);
    fireEvent.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('is disabled and prevents click events when disabled prop is true', () => {
    const handleClick = vi.fn();
    render(<Button disabled onClick={handleClick}>Click me</Button>);
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
    expect(button).toHaveClass('disabled:opacity-50');
    fireEvent.click(button);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('disables clicking and displays a spinner when isLoading is true', () => {
    const handleClick = vi.fn();
    render(<Button isLoading onClick={handleClick}>Submit</Button>);
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
    
    // Spinner should render
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
    
    // Label should be invisible to preserve width
    const labelSpan = screen.getByTestId('button-content');
    expect(labelSpan).toHaveClass('invisible');
    expect(labelSpan).toHaveClass('opacity-0');

    // Click should be blocked
    fireEvent.click(button);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('renders left and right icons correctly', () => {
    render(
      <Button
        leftIcon={<span data-testid="left">L</span>}
        rightIcon={<span data-testid="right">R</span>}
      >
        Action
      </Button>
    );
    expect(screen.getByTestId('left')).toBeInTheDocument();
    expect(screen.getByTestId('right')).toBeInTheDocument();
    expect(screen.getByText('Action')).toBeInTheDocument();
  });
});

describe('Badge Component', () => {
  it('renders text correctly', () => {
    render(<Badge>New</Badge>);
    expect(screen.getByText('New')).toBeInTheDocument();
  });

  it('renders variants and size classes correctly', () => {
    const { rerender } = render(<Badge variant="success">Active</Badge>);
    const badge = screen.getByText('Active');
    expect(badge).toHaveClass('bg-emerald-50', 'text-emerald-700');

    rerender(<Badge variant="danger" size="sm">Alert</Badge>);
    const smBadge = screen.getByText('Alert');
    expect(smBadge).toHaveClass('bg-rose-50', 'px-2', 'py-0.5');
  });
});

describe('Card Component', () => {
  it('renders all composite parts and their slots', () => {
    render(
      <Card data-testid="card">
        <CardHeader data-testid="header">
          <CardTitle data-testid="title">Card Title</CardTitle>
          <CardDescription data-testid="description">Card Description</CardDescription>
        </CardHeader>
        <CardContent data-testid="content">
          <p>Main content area</p>
        </CardContent>
        <CardFooter data-testid="footer">
          <button>Footer Button</button>
        </CardFooter>
      </Card>
    );

    expect(screen.getByTestId('card')).toBeInTheDocument();
    expect(screen.getByTestId('header')).toBeInTheDocument();
    expect(screen.getByTestId('title')).toHaveTextContent('Card Title');
    expect(screen.getByTestId('description')).toHaveTextContent('Card Description');
    expect(screen.getByTestId('content')).toHaveTextContent('Main content area');
    expect(screen.getByTestId('footer')).toBeInTheDocument();
  });
});

describe('Skeleton Component', () => {
  it('renders with correct animation and styles', () => {
    render(<Skeleton data-testid="skele" />);
    const skele = screen.getByTestId('skele');
    expect(skele).toBeInTheDocument();
    expect(skele).toHaveClass('animate-pulse');
  });

  it('supports width, height and variant custom properties', () => {
    const { rerender } = render(<Skeleton variant="circle" width={50} height="100px" />);
    const skele = screen.getByTestId('skeleton');
    expect(skele).toHaveClass('rounded-full');
    expect(skele.style.width).toBe('50px');
    expect(skele.style.height).toBe('100px');

    rerender(<Skeleton variant="rect" />);
    expect(screen.getByTestId('skeleton')).toHaveClass('rounded-none');
  });
});

describe('EmptyState Component', () => {
  it('renders icon, title, description, and action button', () => {
    const mockAction = <Button>Create Item</Button>;
    render(
      <EmptyState
        icon={<span data-testid="empty-icon">📂</span>}
        title="No Results Found"
        description="Try adjusting your filter settings."
        action={mockAction}
      />
    );

    expect(screen.getByTestId('empty-state-title')).toHaveTextContent('No Results Found');
    expect(screen.getByTestId('empty-state-description')).toHaveTextContent('Try adjusting your filter settings.');
    expect(screen.getByTestId('empty-icon')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create Item' })).toBeInTheDocument();
  });
});

describe('ErrorState Component', () => {
  it('renders custom icon, title, and description', () => {
    render(
      <ErrorState
        icon={<span data-testid="error-icon">⚠️</span>}
        title="Custom Error Title"
        description="Something went wrong while fetching data."
      />
    );

    expect(screen.getByTestId('error-state-title')).toHaveTextContent('Custom Error Title');
    expect(screen.getByTestId('error-state-description')).toHaveTextContent('Something went wrong while fetching data.');
    expect(screen.getByTestId('error-icon')).toBeInTheDocument();
  });

  it('triggers onRetry callback when default retry button is clicked', () => {
    const handleRetry = vi.fn();
    render(<ErrorState description="Error" onRetry={handleRetry} />);
    
    const retryBtn = screen.getByTestId('error-state-retry-button');
    expect(retryBtn).toBeInTheDocument();
    
    fireEvent.click(retryBtn);
    expect(handleRetry).toHaveBeenCalledTimes(1);
  });

  it('renders custom retryButton slot', () => {
    render(
      <ErrorState
        description="Error"
        retryButton={<button data-testid="custom-retry">Try Custom</button>}
      />
    );
    expect(screen.getByTestId('custom-retry')).toBeInTheDocument();
    expect(screen.queryByTestId('error-state-retry-button')).toBeNull();
  });
});

describe('Avatar Component', () => {
  it('renders fallback initials if image is not loaded', () => {
    render(<Avatar fallback="JD" />);
    expect(screen.getByTestId('avatar-fallback')).toHaveTextContent('JD');
  });

  it('renders initials question mark fallback if no initials are provided', () => {
    render(<Avatar />);
    expect(screen.getByTestId('avatar-fallback')).toHaveTextContent('?');
  });

  it('displays online status indicator when isOnline is true', () => {
    const { rerender } = render(<Avatar isOnline={false} />);
    expect(screen.queryByTestId('avatar-online-indicator')).toBeNull();

    rerender(<Avatar isOnline={true} />);
    expect(screen.getByTestId('avatar-online-indicator')).toBeInTheDocument();
  });

  it('renders Avatar.Image component correctly', async () => {
    render(<Avatar image="https://example.com/avatar.jpg" fallback="JD" />);
    const avatarImg = await screen.findByTestId('avatar-image');
    expect(avatarImg).toBeInTheDocument();
    expect(avatarImg).toHaveAttribute('src', 'https://example.com/avatar.jpg');
  });
});

describe('StatusBadge Component', () => {
  it('automatically maps standard statuses to correct badge variants', () => {
    const { rerender } = render(<StatusBadge status="completed" />);
    let badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-emerald-50'); // success variant
    expect(badge).toHaveTextContent('Completed');

    rerender(<StatusBadge status="pending" />);
    badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-amber-50'); // warning variant
    expect(badge).toHaveTextContent('Pending');

    rerender(<StatusBadge status="failed" />);
    badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-rose-50'); // danger variant
    expect(badge).toHaveTextContent('Failed');

    rerender(<StatusBadge status="draft" />);
    badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-secondary'); // secondary variant
    expect(badge).toHaveTextContent('Draft');
  });

  it('allows variant overriding and custom children', () => {
    render(
      <StatusBadge status="completed" variantOverride="danger">
        Override Done
      </StatusBadge>
    );
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-rose-50'); // overridden to danger variant
    expect(badge).toHaveTextContent('Override Done');
  });
});
