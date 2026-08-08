/**
 * src/features/leads/components/CsvDropZone.tsx
 *
 * Drag-and-drop CSV picker for the Lead Import screen.
 *
 * The design system has no `FileUpload` primitive (see `src/components/ui/index.ts`), so
 * this composes the ones it does ship — `FilePreview` for the selected file and
 * `ProgressBar` for transfer — rather than introducing a new global
 * component for a single call site. If a second screen ever needs file upload, this is the
 * piece to promote into `components/ui`.
 *
 * The drop target is a real `<button>`, not a styled `<div>`: that gives keyboard focus,
 * Enter/Space activation and a screen-reader-announced role for free, which a div with a
 * click handler would each have to reimplement.
 */

import { useCallback, useRef, useState } from 'react';
import { FileUp, X } from 'lucide-react';
import { FilePreview, ProgressBar } from '../../../components/ui';
import { cn } from '../../../utils/cn';
import { ACCEPTED_CSV_EXTENSIONS, formatBytes, MAX_CSV_BYTES } from '../importUtils';

export interface CsvDropZoneProps {
  file: File | null;
  onSelect: (file: File) => void;
  onClear: () => void;
  /** Validation message from the parent; rendered and announced assertively. */
  error?: string | null;
  disabled?: boolean;
  /** Upload progress 0-100 while a CSV is in flight. */
  uploadPercent?: number;
  isUploading?: boolean;
}

export const CsvDropZone = ({
  file,
  onSelect,
  onClear,
  error,
  disabled = false,
  uploadPercent = 0,
  isUploading = false,
}: CsvDropZoneProps) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const picked = files?.[0];
      if (picked) onSelect(picked);
    },
    [onSelect]
  );

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLButtonElement>) => {
      event.preventDefault();
      setIsDragging(false);
      if (disabled) return;
      handleFiles(event.dataTransfer.files);
    },
    [disabled, handleFiles]
  );

  const handleDragOver = useCallback(
    (event: React.DragEvent<HTMLButtonElement>) => {
      event.preventDefault();
      if (!disabled) setIsDragging(true);
    },
    [disabled]
  );

  return (
    <div className="space-y-3">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_CSV_EXTENSIONS.join(',')}
        className="sr-only"
        onChange={(event) => {
          handleFiles(event.target.files);
          // Reset so picking the same file twice still fires a change event.
          event.target.value = '';
        }}
        disabled={disabled}
        tabIndex={-1}
        aria-hidden="true"
        data-testid="csv-file-input"
      />

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={() => setIsDragging(false)}
        disabled={disabled}
        aria-label="Upload a CSV file. Drag a file here or press Enter to browse."
        aria-describedby="csv-dropzone-hint"
        data-testid="csv-dropzone"
        className={cn(
          'flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 text-center transition-colors sm:p-8',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          isDragging
            ? 'border-primary bg-primary/5'
            : 'border-muted-foreground/25 bg-card hover:border-primary/50 hover:bg-accent/40 dark:border-zinc-800 dark:bg-zinc-950/20',
          disabled && 'cursor-not-allowed opacity-60'
        )}
      >
        <FileUp className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <span className="text-sm font-medium">
          {isDragging ? 'Drop the file to select it' : 'Drag and drop a CSV file here'}
        </span>
        <span className="text-xs text-muted-foreground">or click to browse your computer</span>
      </button>

      <p id="csv-dropzone-hint" className="text-xs text-muted-foreground">
        Accepts {ACCEPTED_CSV_EXTENSIONS.join(' or ')} files up to {formatBytes(MAX_CSV_BYTES)}.
        Column headers such as “Business Name”, “Phone” and “Email” are matched automatically.
      </p>

      {file && (
        <div className="space-y-2">
          <FilePreview
            name={file.name}
            size={file.size}
            type={file.type || 'text/csv'}
            onDelete={disabled ? undefined : onClear}
          />
          {isUploading && (
            <ProgressBar
              value={uploadPercent}
              variant={uploadPercent >= 100 ? 'indeterminate' : 'determinate'}
              size="sm"
              color="primary"
              showPercentage={uploadPercent < 100}
              label={
                uploadPercent >= 100
                  ? 'Processing rows on the server…'
                  : `Uploading ${file.name}`
              }
            />
          )}
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="flex items-start gap-1.5 text-xs font-medium text-destructive"
          data-testid="csv-error"
        >
          <X className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
};
