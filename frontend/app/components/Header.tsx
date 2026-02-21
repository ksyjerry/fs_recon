"use client";

import Image from "next/image";

export default function Header() {
  return (
    <header className="bg-white border-b border-pwc-grey-20">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
        {/* PwC 로고 */}
        <div className="flex items-center gap-3">
          <Image
            src="/pwc-logo.png"
            alt="PwC"
            width={72}
            height={28}
            style={{ objectFit: "contain" }}
            priority
          />
          <span className="w-px h-5 bg-pwc-grey-20" />
          <span className="text-pwc-grey-70 text-sm font-medium">
            SARA
          </span>
          <span className="w-px h-5 bg-pwc-grey-20" />
          <span className="text-pwc-grey-70 text-sm font-semibold">
            국영문 보고서 대사
          </span>
        </div>

        {/* 개발팀 표시 */}
        <div className="text-pwc-grey-70 text-sm italic">
          Developed by Assurance DA
        </div>
      </div>
    </header>
  );
}
