"use client";

interface ProgressTrackerProps {
  progress: number;   // 0~100
  step: string;
  state: "processing" | "completed" | "failed";
}

const STEPS = [
  { label: "DSD 파일 변환",     threshold: 10 },
  { label: "영문 문서 파싱",     threshold: 20 },
  { label: "주석 매핑 & 대사",   threshold: 90 },
  { label: "Excel 생성",        threshold: 100 },
];

export default function ProgressTracker({ progress, step, state }: ProgressTrackerProps) {
  return (
    <div className="bg-white rounded-xl border border-pwc-grey-20 p-6">
      <h3 className="text-sm font-semibold text-pwc-black mb-4">처리 진행 상황</h3>

      {/* 프로그레스 바 */}
      <div className="h-2 bg-pwc-grey-5 rounded-full overflow-hidden mb-5">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            state === "failed"
              ? "bg-pwc-red"
              : state === "completed"
              ? "bg-success"
              : "bg-pwc-orange"
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* 스텝 목록 */}
      <div className="space-y-3">
        {STEPS.map((s, i) => {
          const done      = progress > s.threshold;
          const active    = !done && (i === 0 ? progress > 0 : progress > STEPS[i - 1].threshold);
          const isFailed  = state === "failed" && active;

          return (
            <div key={i} className="flex items-center gap-3">
              {/* 아이콘 */}
              <div className={[
                "w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold",
                isFailed  ? "bg-pwc-red text-white" :
                done      ? "bg-pwc-orange text-white" :
                active    ? "bg-orange-100 border-2 border-pwc-orange" :
                            "bg-pwc-grey-5 border-2 border-pwc-grey-20 text-pwc-grey-20",
              ].join(" ")}>
                {isFailed ? (
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                ) : done ? (
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
                  </svg>
                ) : active ? (
                  <div className="w-2.5 h-2.5 rounded-full bg-pwc-orange animate-pulse" />
                ) : (
                  <span className="text-pwc-grey-20">{i + 1}</span>
                )}
              </div>

              {/* 레이블 */}
              <div className="flex-1 min-w-0">
                <p className={`text-sm font-medium ${
                  isFailed ? "text-pwc-red" :
                  done     ? "text-success" :
                  active   ? "text-pwc-black" :
                             "text-pwc-grey-20"
                }`}>
                  {s.label}
                </p>
                {active && step && (
                  <p className="text-xs text-pwc-grey-70 truncate mt-0.5">{step}</p>
                )}
              </div>

              {/* 상태 텍스트 */}
              <span className={`text-xs flex-shrink-0 ${
                isFailed ? "text-pwc-red" :
                done     ? "text-success font-medium" :
                active   ? "text-pwc-orange font-medium" :
                           "text-pwc-grey-20"
              }`}>
                {isFailed ? "오류" : done ? "완료" : active ? "진행중" : "대기"}
              </span>
            </div>
          );
        })}
      </div>

      {/* 퍼센트 */}
      <div className="mt-4 text-right">
        <span className={`text-sm font-semibold tabular-nums ${
          state === "failed" ? "text-pwc-red" : "text-pwc-orange"
        }`}>
          {progress}%
        </span>
      </div>
    </div>
  );
}
