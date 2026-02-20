"use client";

import DownloadButton from "./components/DownloadButton";
import FileUploadZone from "./components/FileUploadZone";
import ProcessLog from "./components/ProcessLog";
import ProgressTracker from "./components/ProgressTracker";
import { useReconcile } from "./hooks/useReconcile";

export default function Home() {
  const {
    dsdFile, setDsdFile,
    enFile,  setEnFile,
    status,
    logs,
    start, reset,
    downloadHref,
    canStart,
  } = useReconcile();

  const isActive   = status.state === "uploading" || status.state === "processing";
  const isFinished = status.state === "completed" || status.state === "failed";

  const STEPS = ["파일 업로드", "처리 중", "완료"] as const;
  const currentStep =
    status.state === "idle"       ? 0 :
    status.state === "uploading"  ? 1 :
    status.state === "processing" ? 1 : 2;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">

      {/* 스텝 인디케이터 */}
      <div className="flex items-center justify-center gap-0 mb-8">
        {STEPS.map((label, idx) => (
          <div key={idx} className="flex items-center">
            <div className="flex flex-col items-center">
              <div className={[
                "w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all",
                idx < currentStep  ? "bg-pwc-orange border-pwc-orange text-white" :
                idx === currentStep ? "border-pwc-orange bg-white text-pwc-orange" :
                                      "border-pwc-grey-20 bg-white text-pwc-grey-20",
              ].join(" ")}>
                {idx < currentStep ? (
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
                  </svg>
                ) : idx + 1}
              </div>
              <span className={`mt-1 text-xs ${idx === currentStep ? "text-pwc-orange font-semibold" : "text-pwc-grey-20"}`}>
                {label}
              </span>
            </div>
            {idx < STEPS.length - 1 && (
              <div className={`w-16 h-0.5 mb-4 mx-1 transition-all ${idx < currentStep ? "bg-pwc-orange" : "bg-pwc-grey-20"}`} />
            )}
          </div>
        ))}
      </div>

      {/* 메인 카드 */}
      <div className="bg-white rounded-xl border border-pwc-grey-20 shadow-sm p-6 space-y-5">

        {/* 파일 업로드 */}
        <div className="flex gap-4">
          <FileUploadZone
            label="국문 DSD 파일"
            subLabel="국문 DSD 파일을 업로드하세요"
            accept=".dsd"
            acceptDesc=".dsd 파일"
            file={dsdFile}
            onFile={setDsdFile}
            disabled={isActive}
          />
          <FileUploadZone
            label="영문 재무제표"
            subLabel="영문 Word 또는 PDF 파일을 업로드하세요"
            accept=".docx,.pdf"
            acceptDesc=".docx 또는 .pdf"
            file={enFile}
            onFile={setEnFile}
            disabled={isActive}
          />
        </div>

        {/* 오류 메시지 */}
        {status.state === "failed" && status.error && (
          <div className="rounded-lg border border-pwc-red bg-red-50 px-4 py-3 text-sm text-pwc-red">
            <p className="font-semibold mb-0.5">처리 중 오류가 발생했습니다</p>
            <p className="text-xs opacity-80 break-all">{status.error}</p>
          </div>
        )}

        {/* 진행 상황 */}
        {(isActive || isFinished) && (
          <ProgressTracker
            progress={status.progress}
            step={status.step}
            state={status.state === "completed" ? "completed" : status.state === "failed" ? "failed" : "processing"}
          />
        )}

        {/* 처리 로그 */}
        {(isActive || isFinished) && logs.length > 0 && (
          <ProcessLog logs={logs} />
        )}

        {/* 액션 버튼 */}
        <div className="flex gap-3 pt-1">
          {!isFinished ? (
            <>
              <button
                onClick={start}
                disabled={!canStart || isActive}
                className={[
                  "flex-1 rounded-lg py-3 text-sm font-semibold transition-all duration-150",
                  canStart && !isActive
                    ? "bg-pwc-orange text-white hover:bg-pwc-orange-dk shadow-sm hover:shadow-md"
                    : "bg-pwc-grey-5 text-pwc-grey-20 cursor-not-allowed border border-pwc-grey-20",
                ].join(" ")}
              >
                {isActive ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                    </svg>
                    처리 중...
                  </span>
                ) : "대사 시작"}
              </button>
              {isActive && (
                <button
                  onClick={reset}
                  className="px-4 py-3 rounded-lg text-sm font-medium text-pwc-grey-70 border border-pwc-grey-20 hover:border-pwc-red hover:text-pwc-red transition-all"
                  title="강제 초기화"
                >
                  취소
                </button>
              )}
            </>
          ) : (
            <>
              <div className="flex-1">
                <DownloadButton href={downloadHref} />
              </div>
              <button
                onClick={reset}
                className="px-4 py-3 rounded-lg text-sm font-medium text-pwc-grey-70 border border-pwc-grey-20 hover:border-pwc-grey-70 transition-all"
              >
                새로 시작
              </button>
            </>
          )}
        </div>
      </div>

      {/* 사용 안내 */}
      {status.state === "idle" && (
        <div className="mt-6 rounded-lg border border-pwc-grey-20 bg-white p-4">
          <p className="text-xs font-semibold text-pwc-grey-70 mb-2">사용 방법</p>
          <ol className="text-xs text-pwc-grey-70 space-y-1 list-decimal list-inside">
            <li>국문 DSD 파일 (.dsd)과 영문 재무제표 (.docx 또는 .pdf)를 업로드합니다.</li>
            <li><strong className="text-pwc-black">대사 시작</strong> 버튼을 클릭하면 자동으로 처리됩니다.</li>
            <li>완료 후 Excel 파일을 다운로드하여 결과를 확인합니다.</li>
          </ol>
        </div>
      )}
    </div>
  );
}
