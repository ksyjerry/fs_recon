"use client";

import { useEffect, useRef } from "react";
import { LogEntry } from "../lib/api";

interface ProcessLogProps {
  logs: LogEntry[];
}

export default function ProcessLog({ logs }: ProcessLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // 새 로그가 추가되면 자동 스크롤
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  if (logs.length === 0) return null;

  return (
    <div className="rounded-lg border border-pwc-grey-20 overflow-hidden">
      <div className="bg-pwc-grey-90 px-3 py-1.5 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-pwc-orange animate-pulse flex-shrink-0" />
        <span className="text-xs font-semibold text-white">처리 로그</span>
        <span className="ml-auto text-xs text-pwc-grey-20">{logs.length}개 항목</span>
      </div>
      <div className="bg-pwc-grey-90 bg-opacity-95 max-h-48 overflow-y-auto p-3 space-y-0.5 font-mono">
        {logs.map((entry, i) => (
          <div key={i} className="flex gap-2 text-xs leading-relaxed">
            <span className="text-pwc-grey-20 flex-shrink-0 select-none">[{entry.time}]</span>
            <span className="text-green-400 break-all">{entry.msg}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
