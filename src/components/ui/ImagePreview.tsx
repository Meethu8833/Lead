import * as React from 'react';
import { cn } from '../../utils/cn';
import { Button } from './Button';
import { Dialog, DialogContent } from './Dialog';
import { ZoomIn, ZoomOut, RotateCcw, Trash2, Eye, ImageOff } from 'lucide-react';

export interface ImagePreviewProps {
  src: string;
  alt?: string;
  onRemove?: () => void;
  className?: string;
  fallbackSrc?: string;
}

export const ImagePreview = ({
  src,
  alt = 'Preview',
  onRemove,
  className,
  fallbackSrc,
}: ImagePreviewProps) => {
  const [hasError, setHasError] = React.useState(false);
  const [lightboxOpen, setLightboxOpen] = React.useState(false);
  const [zoom, setZoom] = React.useState(1);

  React.useEffect(() => {
    setHasError(false);
  }, [src]);

  const displaySrc = hasError ? fallbackSrc : src;
  const showPlaceholder = !displaySrc || hasError;

  const handleZoomIn = (e: React.MouseEvent) => {
    e.stopPropagation();
    setZoom((z) => Math.min(z + 0.25, 3));
  };

  const handleZoomOut = (e: React.MouseEvent) => {
    e.stopPropagation();
    setZoom((z) => Math.max(z - 0.25, 0.5));
  };

  const handleZoomReset = (e: React.MouseEvent) => {
    e.stopPropagation();
    setZoom(1);
  };

  const handleThumbnailClick = () => {
    if (!showPlaceholder) {
      setLightboxOpen(true);
      setZoom(1); // Reset zoom on open
    }
  };

  return (
    <>
      <div
        className={cn(
          'group relative aspect-square w-24 h-24 rounded-lg border border-border bg-muted dark:bg-zinc-900 overflow-hidden flex items-center justify-center cursor-pointer select-none',
          showPlaceholder && 'cursor-default',
          className
        )}
        onClick={handleThumbnailClick}
        data-testid="image-preview"
      >
        {showPlaceholder ? (
          <div className="flex flex-col items-center justify-center gap-1.5 p-2 text-muted-foreground" data-testid="image-preview-fallback">
            <ImageOff className="h-6 w-6 stroke-[1.5]" />
            <span className="text-[10px] text-center font-medium leading-none">No Image</span>
          </div>
        ) : (
          <>
            <img
              src={displaySrc}
              alt={alt}
              className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
              onError={() => setHasError(true)}
              data-testid="image-preview-thumbnail"
            />
            {/* Hover overlay */}
            <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
              <span className="p-1.5 rounded-full bg-white/20 text-white hover:bg-white/30 transition-colors">
                <Eye className="h-4 w-4" />
              </span>
            </div>
          </>
        )}

        {/* Remove button */}
        {onRemove && (
          <Button
            variant="danger"
            size="sm"
            className="absolute top-1 right-1 h-6 w-6 p-0 rounded-full shadow opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity z-10"
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            aria-label="Remove image"
            data-testid="image-preview-remove"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        )}
      </div>

      {/* Lightbox dialog */}
      {!showPlaceholder && (
        <Dialog open={lightboxOpen} onOpenChange={setLightboxOpen}>
          <DialogContent
            size="lg"
            className="p-0 border-0 bg-transparent shadow-none max-h-none overflow-visible flex flex-col items-center"
            data-testid="image-preview-lightbox"
          >
            <div className="relative w-full max-w-[85vw] max-h-[75vh] flex items-center justify-center bg-black/90 dark:bg-zinc-950/90 rounded-lg overflow-hidden border border-zinc-800 shadow-2xl p-4">
              <div
                className="overflow-auto flex items-center justify-center w-full h-full max-h-[70vh]"
                data-testid="image-preview-lightbox-viewport"
              >
                <img
                  src={displaySrc}
                  alt={alt}
                  className="max-w-full max-h-full object-contain origin-center select-none"
                  style={{
                    transform: `scale(${zoom})`,
                    transition: 'transform 0.15s cubic-bezier(0.16, 1, 0.3, 1)',
                  }}
                  data-testid="image-preview-lightbox-img"
                />
              </div>

              {/* Zoom Controls Overlay */}
              <div
                className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-black/70 border border-zinc-800 text-white backdrop-blur z-20"
                onClick={(e) => e.stopPropagation()} // Prevent clicking through to parent
                data-testid="image-preview-zoom-controls"
              >
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 text-white hover:bg-white/10 hover:text-white"
                  onClick={handleZoomOut}
                  disabled={zoom <= 0.5}
                  aria-label="Zoom out"
                  data-testid="image-preview-zoom-out"
                >
                  <ZoomOut className="h-4 w-4" />
                </Button>
                <span className="text-xs font-semibold select-none min-w-[36px] text-center" data-testid="image-preview-zoom-scale">
                  {Math.round(zoom * 100)}%
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 text-white hover:bg-white/10 hover:text-white"
                  onClick={handleZoomIn}
                  disabled={zoom >= 3}
                  aria-label="Zoom in"
                  data-testid="image-preview-zoom-in"
                >
                  <ZoomIn className="h-4 w-4" />
                </Button>
                <div className="w-[1px] h-4 bg-zinc-800 mx-1" />
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 text-white hover:bg-white/10 hover:text-white"
                  onClick={handleZoomReset}
                  disabled={zoom === 1}
                  aria-label="Reset zoom"
                  data-testid="image-preview-zoom-reset"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
};
