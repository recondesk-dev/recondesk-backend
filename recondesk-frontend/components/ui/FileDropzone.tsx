"use client";

import { useCallback, useRef, useState } from "react";
import { UploadCloud, FileText, CheckCircle2, X, AlertCircle } from "lucide-react";

export interface FileDropzoneProps {
  accept?: string;
  allowedExtensions?: string[];
  maxSizeBytes?: number; // default 25MB
  multiple?: boolean;
  selectedFile?: File | null;
  onFileSelect?: (file: File | null) => void;
  onFilesSelect?: (files: File[]) => void;
  progress?: number | null; // 0 to 100
  title?: string;
  subtitle?: string;
  disabled?: boolean;
  className?: string;
  compact?: boolean;
  hintTags?: string[];
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileDropzone({
  accept,
  allowedExtensions = [".xlsx", ".xls", ".csv"],
  maxSizeBytes = 25 * 1024 * 1024,
  multiple = false,
  selectedFile,
  onFileSelect,
  onFilesSelect,
  progress,
  title = "Drop your file here, or click to browse",
  subtitle = "Supports Excel (.xlsx, .xls) and CSV up to 25 MB",
  disabled = false,
  className = "",
  compact = false,
  hintTags,
}: FileDropzoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const dragCounter = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const validate = useCallback(
    (file: File): string | null => {
      if (maxSizeBytes && file.size > maxSizeBytes) {
        return `File exceeds maximum size of ${formatBytes(maxSizeBytes)}`;
      }
      if (allowedExtensions.length > 0) {
        const lowerName = file.name.toLowerCase();
        const matches = allowedExtensions.some((ext) =>
          lowerName.endsWith(ext.toLowerCase())
        );
        if (!matches) {
          return `Only ${allowedExtensions.join(", ")} files are supported`;
        }
      }
      return null;
    },
    [maxSizeBytes, allowedExtensions]
  );

  const processIncomingFiles = useCallback(
    (incoming: File[]) => {
      setErrorMessage(null);
      if (incoming.length === 0) return;

      if (!multiple) {
        const first = incoming[0];
        const error = validate(first);
        if (error) {
          setErrorMessage(error);
          return;
        }
        onFileSelect?.(first);
      } else {
        const valid: File[] = [];
        const errors: string[] = [];
        for (const f of incoming) {
          const err = validate(f);
          if (err) {
            errors.push(`${f.name}: ${err}`);
          } else {
            valid.push(f);
          }
        }
        if (errors.length > 0) {
          setErrorMessage(errors[0]);
        }
        if (valid.length > 0) {
          onFilesSelect?.(valid);
        }
      }
    },
    [multiple, onFileSelect, onFilesSelect, validate]
  );

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0 && !disabled) {
      setIsDragOver(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setIsDragOver(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setIsDragOver(false);
    if (disabled) return;
    const dropped = Array.from(e.dataTransfer.files || []);
    processIncomingFiles(dropped);
  };

  const isUploading = typeof progress === "number" && progress >= 0 && progress < 100;
  const isUploadComplete = typeof progress === "number" && progress >= 100;

  return (
    <div className={`w-full space-y-2.5 ${className}`}>
      {selectedFile ? (
        // Selected File Preview Card
        <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-[var(--shadow-soft)] transition-all">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gray-100 text-[var(--ink)]">
                <FileText className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-[var(--ink)]">
                  {selectedFile.name}
                </p>
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <span>{formatBytes(selectedFile.size)}</span>
                  <span>•</span>
                  <span className="uppercase font-medium text-gray-400">
                    {selectedFile.name.split(".").pop() || "FILE"}
                  </span>
                  {isUploadComplete && (
                    <span className="inline-flex items-center gap-1 font-medium text-emerald-600">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Uploaded
                    </span>
                  )}
                </div>
              </div>
            </div>

            {!disabled && !isUploading && (
              <button
                type="button"
                onClick={() => {
                  onFileSelect?.(null);
                  setErrorMessage(null);
                  if (inputRef.current) inputRef.current.value = "";
                }}
                className="shrink-0 rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition-colors"
                title="Remove selected file"
                aria-label="Remove file"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          {/* Live Progress Bar */}
          {typeof progress === "number" && progress > 0 && progress < 100 && (
            <div className="mt-3 space-y-1.5 pt-2 border-t border-gray-100">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-gray-600">Uploading…</span>
                <span className="font-mono font-semibold text-[var(--ink)]">{progress}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
                <div
                  className="h-full bg-[var(--ink)] transition-all duration-300 ease-out"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}
        </div>
      ) : (
        // Dropzone Area
        <div
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onClick={() => !disabled && inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (!disabled && (e.key === "Enter" || e.key === " ")) {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          className={`group relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-all duration-200 select-none ${
            compact ? "p-6" : "p-8"
          } ${
            isDragOver
              ? "border-[var(--ink)] bg-[#F8F9FA] scale-[1.01] shadow-md ring-4 ring-black/5"
              : disabled
              ? "border-gray-200 bg-gray-50/60 cursor-not-allowed opacity-60"
              : "border-gray-300 bg-white hover:border-gray-400 hover:bg-[#FCFCFD] shadow-[var(--shadow-soft)]"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={accept}
            multiple={multiple}
            disabled={disabled}
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files || []);
              processIncomingFiles(files);
              e.target.value = "";
            }}
          />

          <div
            className={`flex items-center justify-center rounded-2xl transition-transform duration-200 ${
              compact ? "h-10 w-10 mb-2" : "h-12 w-12 mb-3"
            } ${
              isDragOver
                ? "bg-[var(--ink)] text-white scale-110 shadow-sm"
                : "bg-gray-100 text-gray-600 group-hover:bg-gray-200/80 group-hover:text-gray-900"
            }`}
          >
            <UploadCloud className={compact ? "h-5 w-5" : "h-6 w-6"} />
          </div>

          <p className="text-center font-semibold text-[var(--ink)] text-sm tracking-tight">
            {isDragOver ? "Drop your file right here" : title}
          </p>

          <p className="mt-1 text-center text-xs text-gray-500">
            {isDragOver ? "Release to start processing" : subtitle}
          </p>

          {hintTags && hintTags.length > 0 && !isDragOver && (
            <div className="mt-3 flex flex-wrap justify-center gap-1.5">
              {hintTags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full bg-gray-100 px-2.5 py-0.5 text-[10px] font-semibold text-gray-600 border border-gray-200/60"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {errorMessage && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50/90 p-3 text-xs text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}
    </div>
  );
}
