import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import {
  Input,
  PasswordInput,
  Textarea,
  Checkbox,
  Switch,
  RadioGroup,
  Select,
  NumberInput,
  CurrencyInput,
  PhoneInput,
  SearchBox,
} from '../components/ui';

describe('Input Component', () => {
  it('renders labels, placeholders, prefixes, and suffixes correctly', () => {
    render(
      <Input
        label="Username"
        placeholder="Enter username"
        prefix={<span data-testid="pref">@</span>}
        suffix={<span data-testid="suff">.com</span>}
        helperText="Only alphanumeric characters allowed"
      />
    );

    expect(screen.getByTestId('input-label')).toHaveTextContent('Username');
    expect(screen.getByPlaceholderText('Enter username')).toBeInTheDocument();
    expect(screen.getByTestId('input-prefix')).toBeInTheDocument();
    expect(screen.getByTestId('input-suffix')).toBeInTheDocument();
    expect(screen.getByTestId('input-helper')).toHaveTextContent('Only alphanumeric characters allowed');
  });

  it('renders required indicator star when required prop is passed', () => {
    render(<Input label="Required Field" required />);
    expect(screen.getByTestId('input-required-star')).toBeInTheDocument();
  });

  it('applies validation error styling classes and sets aria-invalid="true"', () => {
    render(<Input error="Field is required" />);
    const input = screen.getByRole('textbox');
    expect(input).toHaveClass('border-destructive');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByTestId('input-error')).toHaveTextContent('Field is required');
  });

  it('disables input interactions when disabled is true', () => {
    render(<Input disabled label="Disabled Input" />);
    const input = screen.getByRole('textbox');
    expect(input).toBeDisabled();
    expect(screen.getByTestId('input-label')).toHaveClass('opacity-50');
  });
});

describe('PasswordInput Component', () => {
  it('toggles password visibility when the eye button is clicked', () => {
    render(<PasswordInput placeholder="Enter password" />);
    const input = screen.getByPlaceholderText('Enter password');
    expect(input).toHaveAttribute('type', 'password');

    const toggleBtn = screen.getByTestId('password-toggle');
    expect(toggleBtn).toHaveAttribute('aria-label', 'Show password');
    expect(screen.getByTestId('eye-icon')).toBeInTheDocument();

    // Toggle to visible
    fireEvent.click(toggleBtn);
    expect(input).toHaveAttribute('type', 'text');
    expect(toggleBtn).toHaveAttribute('aria-label', 'Hide password');
    expect(screen.getByTestId('eye-off-icon')).toBeInTheDocument();

    // Toggle back to password
    fireEvent.click(toggleBtn);
    expect(input).toHaveAttribute('type', 'password');
  });

  it('disables toggle click event when disabled is true', () => {
    render(<PasswordInput disabled placeholder="Enter password" />);
    const input = screen.getByPlaceholderText('Enter password');
    const toggleBtn = screen.getByTestId('password-toggle');

    expect(input).toBeDisabled();
    expect(toggleBtn).toBeDisabled();
  });
});

describe('Textarea Component', () => {
  it('renders labels, characters, and text counts correctly', () => {
    render(
      <Textarea
        label="Comments"
        maxLength={100}
        showMaxLength
        defaultValue="Hello World"
      />
    );
    expect(screen.getByTestId('textarea-label')).toHaveTextContent('Comments');
    expect(screen.getByTestId('textarea-counter')).toHaveTextContent('11 / 100');
  });

  it('renders validation error text and invalid state classes', () => {
    render(<Textarea error="Too short" />);
    const textarea = screen.getByRole('textbox');
    expect(textarea).toHaveClass('border-destructive');
    expect(screen.getByTestId('textarea-error')).toHaveTextContent('Too short');
  });

  it('updates counter length value when typing', () => {
    render(<Textarea maxLength={50} showMaxLength />);
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'Coding' } });
    expect(screen.getByTestId('textarea-counter')).toHaveTextContent('6 / 50');
  });
});

describe('Checkbox Component', () => {
  it('renders checkmark indicator correctly', () => {
    render(<Checkbox label="Accept Terms" description="Read terms first" />);
    expect(screen.getByTestId('checkbox-label')).toHaveTextContent('Accept Terms');
    expect(screen.getByTestId('checkbox-description')).toHaveTextContent('Read terms first');

    const input = screen.getByRole('checkbox');
    expect(input).not.toBeChecked();

    fireEvent.click(input);
    expect(input).toBeChecked();
  });

  it('displays validation error highlights', () => {
    render(<Checkbox error="Must accept" />);
    expect(screen.getByTestId('checkbox-indicator')).toHaveClass('border-destructive');
    expect(screen.getByTestId('checkbox-error')).toHaveTextContent('Must accept');
  });

  it('disables clicking and interactions when disabled is true', () => {
    render(<Checkbox disabled label="Cannot click" />);
    const input = screen.getByRole('checkbox');
    expect(input).toBeDisabled();
  });
});

describe('Switch Component', () => {
  it('handles click events to toggle checked state', () => {
    render(<Switch label="Enable notifications" description="Toggle switch" />);
    expect(screen.getByTestId('switch-label')).toHaveTextContent('Enable notifications');
    expect(screen.getByTestId('switch-description')).toHaveTextContent('Toggle switch');

    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it('shows error highlight border', () => {
    render(<Switch error="Enable is required" />);
    expect(screen.getByTestId('switch-track')).toHaveClass('ring-2', 'ring-destructive');
    expect(screen.getByTestId('switch-error')).toHaveTextContent('Enable is required');
  });

  it('blocks switch operations when disabled is true', () => {
    render(<Switch disabled label="Disabled Toggle" />);
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).toBeDisabled();
  });
});

describe('RadioGroup Component', () => {
  const options = [
    { label: 'Red', value: 'red' },
    { label: 'Blue', value: 'blue' },
    { label: 'Green', value: 'green', disabled: true },
  ];

  it('renders option lists and respects orientations', () => {
    render(<RadioGroup name="color" label="Pick a color" options={options} />);
    expect(screen.getByTestId('radiogroup-label')).toHaveTextContent('Pick a color');
    expect(screen.getByTestId('radio-label-red')).toHaveTextContent('Red');
    expect(screen.getByTestId('radio-label-green')).toHaveTextContent('Green');

    const redRadio = screen.getByLabelText('Red');
    const greenRadio = screen.getByLabelText('Green');

    expect(redRadio).not.toBeChecked();
    expect(greenRadio).toBeDisabled();
  });

  it('triggers change callback and checks active option', () => {
    const handleChange = vi.fn();
    render(
      <RadioGroup
        name="color"
        options={options}
        defaultValue="blue"
        onChange={handleChange}
      />
    );
    const redRadio = screen.getByLabelText('Red');
    const blueRadio = screen.getByLabelText('Blue');

    expect(blueRadio).toBeChecked();
    expect(redRadio).not.toBeChecked();

    fireEvent.click(redRadio);
    expect(redRadio).toBeChecked();
    expect(blueRadio).not.toBeChecked();
    expect(handleChange).toHaveBeenCalledWith('red');
  });
});

describe('Select Component', () => {
  const options = [
    { label: 'Apple', value: 'apple' },
    { label: 'Banana', value: 'banana' },
  ];
  const groups = [
    {
      label: 'Vegetables',
      options: [{ label: 'Carrot', value: 'carrot' }],
    },
  ];

  it('renders placeholders, options, and optgroups', () => {
    render(
      <Select
        label="Food Select"
        placeholder="Choose food"
        options={options}
        groups={groups}
      />
    );
    expect(screen.getByTestId('select-label')).toHaveTextContent('Food Select');
    expect(screen.getByRole('combobox')).toHaveTextContent('Choose food');
    expect(screen.getByText('Apple')).toBeInTheDocument();
    expect(screen.getByText('Carrot')).toBeInTheDocument();
  });

  it('updates selection on user interaction', () => {
    const handleChange = vi.fn();
    render(<Select options={options} onChange={handleChange} defaultValue="" />);
    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: 'banana' } });
    expect(select).toHaveValue('banana');
    expect(handleChange).toHaveBeenCalled();
  });
});

describe('NumberInput Component', () => {
  it('increments/decrements values via side buttons', () => {
    const handleChange = vi.fn();
    render(<NumberInput min={0} max={10} step={2} onChange={handleChange} defaultValue={4} />);
    const input = screen.getByRole('spinbutton');
    expect(input).toHaveValue(4);

    const incBtn = screen.getByTestId('numberinput-inc');
    const decBtn = screen.getByTestId('numberinput-dec');

    fireEvent.click(incBtn);
    expect(input).toHaveValue(6);
    expect(handleChange).toHaveBeenCalledWith(6);

    fireEvent.click(decBtn);
    expect(input).toHaveValue(4);
    expect(handleChange).toHaveBeenCalledWith(4);
  });

  it('respects min and max constraints on increment/decrement', () => {
    render(<NumberInput min={1} max={3} defaultValue={2} />);
    const input = screen.getByRole('spinbutton');
    const incBtn = screen.getByTestId('numberinput-inc');
    const decBtn = screen.getByTestId('numberinput-dec');

    // Click increment
    fireEvent.click(incBtn);
    expect(input).toHaveValue(3);
    
    // Increment should block at max
    fireEvent.click(incBtn);
    expect(input).toHaveValue(3);

    // Click decrement
    fireEvent.click(decBtn);
    fireEvent.click(decBtn);
    expect(input).toHaveValue(1);

    // Decrement should block at min
    fireEvent.click(decBtn);
    expect(input).toHaveValue(1);
  });

  it('handles typing inputs correctly', () => {
    const handleChange = vi.fn();
    render(<NumberInput onChange={handleChange} />);
    const input = screen.getByRole('spinbutton');

    fireEvent.change(input, { target: { value: '15' } });
    expect(input).toHaveValue(15);
    expect(handleChange).toHaveBeenCalledWith(15);

    fireEvent.change(input, { target: { value: '' } });
    expect(input).toHaveValue(null);
    expect(handleChange).toHaveBeenCalledWith(null);
  });
});

describe('CurrencyInput Component', () => {
  it('displays locale-formatted values on blur and raw values on focus', () => {
    const handleChangeValue = vi.fn();
    render(
      <CurrencyInput
        locale="en-IN"
        currency="INR"
        defaultValue={1234.5}
        onChangeValue={handleChangeValue}
      />
    );

    const input = screen.getByRole('textbox');
    // Indian locale should format 1234.50 as 1,234.50, and symbol ₹ should render in prefix
    expect(screen.getByTestId('currency-symbol')).toHaveTextContent('₹');
    expect(input).toHaveValue('1,234.50');

    // Focus -> should show raw input float
    fireEvent.focus(input);
    expect(input).toHaveAttribute('type', 'number');
    expect(input).toHaveValue(1234.5);

    // Change value in focus mode
    fireEvent.change(input, { target: { value: '9876.5' } });
    expect(handleChangeValue).toHaveBeenCalledWith(9876.5);

    // Blur -> should format again
    fireEvent.blur(input);
    expect(input).toHaveAttribute('type', 'text');
    expect(input).toHaveValue('9,876.50');
  });
});

describe('PhoneInput Component', () => {
  it('automatically formats Indian phone numbers (XXXXX XXXXX)', () => {
    const handleChange = vi.fn();
    render(<PhoneInput showCountryCode countryCode="+91" onChange={handleChange} />);
    const input = screen.getByRole('textbox');
    expect(screen.getByTestId('phone-country-code')).toHaveTextContent('+91');

    // Type 10 digit number
    fireEvent.change(input, { target: { value: '9876543210' } });
    expect(input).toHaveValue('98765 43210');
    expect(handleChange).toHaveBeenCalled();

    // Type non-digit values -> should filter
    fireEvent.change(input, { target: { value: '9876abc543' } });
    expect(input).toHaveValue('98765 43');
  });
});

describe('SearchBox Component', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('debounces input callbacks and triggers searching after delay', () => {
    const handleSearch = vi.fn();
    render(<SearchBox onSearch={handleSearch} debounceDelay={300} />);
    const input = screen.getByRole('searchbox');

    fireEvent.change(input, { target: { value: 'query' } });
    // Callback should not be fired yet
    expect(handleSearch).not.toHaveBeenCalled();

    // Fast-forward halfway
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(handleSearch).not.toHaveBeenCalled();

    // Fast-forward fully
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(handleSearch).toHaveBeenCalledWith('query');
    expect(handleSearch).toHaveBeenCalledTimes(1);
  });

  it('triggers instant query when clear button is clicked', () => {
    const handleSearch = vi.fn();
    render(<SearchBox onSearch={handleSearch} defaultValue="hello" />);
    const input = screen.getByRole('searchbox');

    const clearBtn = screen.getByTestId('search-clear');
    expect(clearBtn).toBeInTheDocument();

    fireEvent.click(clearBtn);
    expect(input).toHaveValue('');
    expect(handleSearch).toHaveBeenCalledWith('');
    expect(handleSearch).toHaveBeenCalledTimes(1);
  });

  it('shows loading spinner when isLoading is true', () => {
    render(<SearchBox onSearch={vi.fn()} isLoading={true} />);
    expect(screen.getByTestId('search-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('search-clear')).toBeNull();
  });

  it('focuses search input when global / key is pressed', () => {
    render(<SearchBox onSearch={vi.fn()} showShortcut={true} />);
    const input = screen.getByRole('searchbox');
    expect(input).not.toHaveFocus();

    // Trigger keydown on window
    fireEvent.keyDown(window, { key: '/' });
    expect(input).toHaveFocus();
  });
});
