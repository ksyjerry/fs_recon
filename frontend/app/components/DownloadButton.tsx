"use client";

interface DownloadButtonProps {
  href: string | null;
  disabled?: boolean;
}

export default function DownloadButton({ href, disabled }: DownloadButtonProps) {
  const ready = !!href && !disabled;

  return (
    <a
      href={ready ? href : undefined}
      download
      onClick={(e) => { if (!ready) e.preventDefault(); }}
      className={[
        "flex items-center justify-center gap-2 w-full rounded-lg py-3 px-5 text-sm font-semibold transition-all duration-150",
        ready
          ? "bg-pwc-orange text-white hover:bg-pwc-orange-dk cursor-pointer shadow-sm hover:shadow-md"
          : "bg-pwc-grey-5 text-pwc-grey-20 cursor-not-allowed border border-pwc-grey-20",
      ].join(" ")}
      aria-disabled={!ready}
    >
      <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
      {ready ? "Excel 다운로드" : "대사 완료 후 다운로드 가능"}
    </a>
  );
}
