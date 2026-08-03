import { cn } from '../../utils/cn';
import { Button } from './Button';
import {
  File,
  FileText,
  FileImage,
  FileCode,
  FileAudio,
  FileVideo,
  Download,
  Trash2,
  Eye,
} from 'lucide-react';

export interface FilePreviewProps {
  name: string;
  size?: number; // Size in bytes
  type?: string; // Mime type or extension
  onDownload?: () => void;
  onDelete?: () => void;
  onView?: () => void;
  className?: string;
}

export const FilePreview = ({
  name,
  size,
  type,
  onDownload,
  onDelete,
  onView,
  className,
}: FilePreviewProps) => {
  const formatBytes = (bytes?: number) => {
    if (bytes === undefined) return '';
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const getFileIcon = () => {
    const ext = name.split('.').pop()?.toLowerCase() || '';
    const mime = type?.toLowerCase() || '';

    if (mime.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp'].includes(ext)) {
      return <FileImage className="h-6 w-6 text-blue-500" />;
    }
    if (mime === 'application/pdf' || ext === 'pdf') {
      return <FileText className="h-6 w-6 text-rose-500" />;
    }
    if (
      ['doc', 'docx', 'rtf', 'txt', 'odt'].includes(ext) ||
      mime.startsWith('text/plain')
    ) {
      return <FileText className="h-6 w-6 text-indigo-500" />;
    }
    if (['xls', 'xlsx', 'csv', 'ods'].includes(ext)) {
      return <FileText className="h-6 w-6 text-emerald-600" />; // Fallback spreadsheet to text
    }
    if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) {
      return <File className="h-6 w-6 text-amber-500" />; // Fallback archive to file
    }
    if (mime.startsWith('video/') || ['mp4', 'mkv', 'avi', 'mov'].includes(ext)) {
      return <FileVideo className="h-6 w-6 text-purple-500" />;
    }
    if (mime.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'aac'].includes(ext)) {
      return <FileAudio className="h-6 w-6 text-teal-500" />;
    }
    if (['html', 'css', 'js', 'ts', 'tsx', 'json', 'py', 'go'].includes(ext)) {
      return <FileCode className="h-6 w-6 text-violet-500" />;
    }

    return <File className="h-6 w-6 text-muted-foreground" />;
  };

  return (
    <div
      className={cn(
        'flex items-center justify-between gap-4 p-3 rounded-lg border border-border bg-card hover:bg-muted/10 transition-colors',
        className
      )}
      data-testid="file-preview"
    >
      <div className="flex items-center gap-3 min-w-0">
        <div className="p-2 rounded bg-muted dark:bg-zinc-900 shrink-0" data-testid="file-preview-icon">
          {getFileIcon()}
        </div>
        <div className="min-w-0 flex flex-col">
          <span
            className="text-sm font-medium text-foreground truncate select-all leading-snug"
            title={name}
            data-testid="file-preview-name"
          >
            {name}
          </span>
          {size !== undefined && (
            <span
              className="text-xs text-muted-foreground select-none"
              data-testid="file-preview-size"
            >
              {formatBytes(size)}
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1.5 shrink-0" data-testid="file-preview-actions">
        {onView && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={onView}
            aria-label={`View file ${name}`}
            data-testid="file-preview-view"
          >
            <Eye className="h-4 w-4" />
          </Button>
        )}
        {onDownload && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={onDownload}
            aria-label={`Download file ${name}`}
            data-testid="file-preview-download"
          >
            <Download className="h-4 w-4" />
          </Button>
        )}
        {onDelete && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0 hover:bg-destructive/10 hover:text-destructive text-muted-foreground"
            onClick={onDelete}
            aria-label={`Delete file ${name}`}
            data-testid="file-preview-delete"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  );
};
