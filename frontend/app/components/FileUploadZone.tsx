"use client";

import { useCallback, useRef, useState } from "react";

interface FileUploadZoneProps {
  label: string;
  subLabel: string;
  accept: string;
  acceptDesc: string;
  file: File | null;
  onFile: (f: File | null) => void;
  disabled?: boolean;
}

export default function FileUploadZone({
  label,
  subLabel,
  accept,
  acceptDesc,
  file,
  onFile,
  disabled = false,
}: FileUploadZoneProps) {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validate = useCallback(
    (f: File): boolean => {
      const exts = accept.split(",").map((e) => e.trim().toLowerCase());
      const name = f.name.toLowerCase();
      if (!exts.some((e) => name.endsWith(e))) {
        setError(`허용 형식: ${acceptDesc}`);
        return false;
      }
      setError(null);
      return true;
    },
    [accept, acceptDesc]
  );

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const f = files[0];
      if (validate(f)) onFile(f);
    },
    [validate, onFile]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (!disabled) handleFiles(e.dataTransfer.files);
    },
    [disabled, handleFiles]
  );

  const formatBytes = (b: number) =>
    b < 1024 * 1024
      ? `${(b / 1024).toFixed(1)} KB`
      : `${(b / 1024 / 1024).toFixed(1)} MB`;

  const formatExt = (name: string) => name.split(".").pop()?.toUpperCase() ?? "";

  return (
    <div className="flex-1 min-w-0">
      <p className="text-sm font-semibold text-pwc-black mb-1">{label}</p>
      <p className="text-xs text-pwc-grey-70 mb-2">{subLabel}</p>

      <div
        onClick={() => !disabled && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={[
          "relative rounded-lg border-2 border-dashed p-5 text-center cursor-pointer transition-all duration-150 select-none",
          disabled
            ? "opacity-50 cursor-not-allowed border-pwc-grey-20 bg-pwc-grey-5"
            : error
            ? "border-pwc-red bg-red-50"
            : dragging
            ? "border-pwc-orange bg-orange-50"
            : file
            ? "border-green-400 bg-green-50"
            : "border-pwc-grey-20 bg-white hover:border-pwc-orange hover:bg-orange-50/30",
        ].join(" ")}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
          disabled={disabled}
        />

        {file ? (
          /* 업로드 완료 */
          <div className="flex items-center justify-center gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-green-500 flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div className="text-left min-w-0">
              <p className="text-sm font-medium text-pwc-black truncate">{file.name}</p>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs font-bold text-white bg-pwc-orange px-1.5 py-0.5 rounded">
                  {formatExt(file.name)}
                </span>
                <span className="text-xs text-pwc-grey-70">{formatBytes(file.size)}</span>
              </div>
            </div>
            {!disabled && (
              <button
                onClick={(e) => { e.stopPropagation(); onFile(null); setError(null); }}
                className="ml-auto flex-shrink-0 text-pwc-grey-70 hover:text-pwc-red transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        ) : (
          /* 업로드 전 */
          <div className="py-2">
            <svg
              className={`mx-auto w-8 h-8 mb-2 ${dragging ? "text-pwc-orange" : "text-pwc-grey-20"}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-sm text-pwc-grey-70">
              {dragging ? "여기에 놓으세요" : "클릭 또는 드래그"}
            </p>
            <p className="text-xs text-pwc-grey-20 mt-1">{acceptDesc}</p>
          </div>
        )}
      </div>

      {error && (
        <p className="mt-1.5 text-xs text-pwc-red flex items-center gap-1">
          <svg className="w-3.5 h-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
          {error}
        </p>
      )}
    </div>
  );
}
