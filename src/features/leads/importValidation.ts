/**
 * src/features/leads/importValidation.ts
 *
 * Zod schema for the Lead Import form, mirroring the orders feature's `validation.ts`
 * convention of keeping schemas beside the feature rather than inside the component.
 *
 * The interesting rule is the conditional one: `query` is required for query-driven
 * providers and meaningless for file-driven ones, and which a provider is comes from the
 * live registry rather than a hardcoded list. That is why the schema is a factory taking
 * `requiresQuery`/`requiresFile` — building it per selected provider keeps the rule in one
 * place instead of scattering `if (provider === 'csv')` through the component.
 *
 * The provider key itself is not a field here: the page holds it as the selector's state
 * and passes it at submit, so validating a copy of it would only create a second source of
 * truth to keep in step.
 */

import { z } from 'zod';
import { MAX_IMPORT_LIMIT, MIN_IMPORT_LIMIT, validateCsvFile } from './importUtils';

export interface ImportSchemaOptions {
  requiresQuery: boolean;
  requiresFile: boolean;
}

/** Builds the form schema for the currently selected provider. */
export const buildImportSchema = ({ requiresQuery, requiresFile }: ImportSchemaOptions) =>
  z
    .object({
      query: z.string().max(500, 'Keep the search keyword under 500 characters.'),
      limit: z
        .number({ invalid_type_error: 'Enter how many results to collect.' })
        .int('Maximum results must be a whole number.')
        .min(MIN_IMPORT_LIMIT, `Collect at least ${MIN_IMPORT_LIMIT} result.`)
        .max(MAX_IMPORT_LIMIT, `Collect at most ${MAX_IMPORT_LIMIT} results in one run.`),
      file: z.instanceof(File).nullable(),
    })
    .superRefine((values, ctx) => {
      if (requiresQuery && !values.query.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['query'],
          message: 'Enter a search keyword, for example “Wedding Photographer Kozhikode”.',
        });
      }

      if (requiresFile) {
        if (!values.file) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['file'],
            message: 'Choose a CSV file to import.',
          });
          return;
        }
        // Re-uses the same check the drop zone applies, so a file selected by any route
        // (drop, browse, or a programmatic set) is validated identically before submit.
        const result = validateCsvFile(values.file);
        if (!result.valid) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['file'],
            message: result.error ?? 'That file cannot be imported.',
          });
        }
      }
    });

export type ImportFormSchema = z.infer<ReturnType<typeof buildImportSchema>>;
