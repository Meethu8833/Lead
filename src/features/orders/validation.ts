import * as z from 'zod';

// Order workflow status (production stage) is intentionally not editable here —
// production workflow transitions are out of scope for this phase and are
// owned by a dedicated status-transition flow in a later phase.
export const orderFormSchema = z
  .object({
    photographer_id: z.string().min(1, 'Photographer / Customer is required'),
    job_name: z.string().trim().min(1, 'Job name is required'),
    event_type: z.string().trim().optional(),
    booking_date: z.string().min(1, 'Booking date is required'),
    event_date: z.string().optional(),
    expected_delivery_date: z.string().optional(),
    advance_paid: z
      .number({ invalid_type_error: 'Advance paid must be a number' })
      .min(0, 'Advance paid cannot be negative')
      .default(0),
    customer_notes: z.string().trim().optional(),
    internal_notes: z.string().trim().optional(),
  })
  .refine(
    (data) =>
      !data.expected_delivery_date ||
      !data.booking_date ||
      new Date(data.expected_delivery_date) >= new Date(data.booking_date),
    {
      message: 'Expected delivery date cannot be earlier than the booking date',
      path: ['expected_delivery_date'],
    }
  );

export type OrderFormValues = z.infer<typeof orderFormSchema>;

export const addItemSchema = z.object({
  product_id: z.string().min(1, 'Product is required'),
  unit_price: z
    .number({ invalid_type_error: 'Unit price must be a number' })
    .min(0, 'Unit price cannot be negative')
    .optional(),
  quantity: z
    .number({ invalid_type_error: 'Quantity must be a number' })
    .int('Quantity must be a whole number')
    .min(1, 'Quantity must be at least 1'),
  discount: z
    .number({ invalid_type_error: 'Discount must be a number' })
    .min(0, 'Discount cannot be negative')
    .default(0),
  album_size: z.string().trim().optional(),
  sheet_type: z.string().trim().optional(),
  cover_type: z.string().trim().optional(),
  remarks: z.string().trim().optional(),
});

export type AddItemFormValues = z.infer<typeof addItemSchema>;

// Used by OrderItemEditor, which edits an *existing* item — unlike addItemSchema, unit_price
// is always a known number here (never "use catalog price"), so the max-discount rule
// (mirrors app/services/order_item.py: "Discount cannot exceed the gross item amount.") can be
// enforced directly in the schema via superRefine.
export const orderItemEditSchema = z
  .object({
    product_id: z.string().min(1, 'Product is required'),
    unit_price: z
      .number({ invalid_type_error: 'Unit price must be a number' })
      .min(0, 'Unit price cannot be negative'),
    quantity: z
      .number({ invalid_type_error: 'Quantity must be a number' })
      .int('Quantity must be a whole number')
      .min(1, 'Quantity must be at least 1'),
    discount: z
      .number({ invalid_type_error: 'Discount must be a number' })
      .min(0, 'Discount cannot be negative')
      .default(0),
    album_size: z.string().trim().optional(),
    sheet_type: z.string().trim().optional(),
    cover_type: z.string().trim().optional(),
    remarks: z.string().trim().optional(),
  })
  .superRefine((data, ctx) => {
    const gross = data.unit_price * data.quantity;
    if (data.discount > gross) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Discount cannot exceed the gross item amount.',
        path: ['discount'],
      });
    }
  });

export type OrderItemEditFormValues = z.infer<typeof orderItemEditSchema>;
