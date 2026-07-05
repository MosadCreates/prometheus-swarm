"use client";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-3.5rem)] px-6">
      <div className="glass p-12 text-center max-w-sm animate-fade-in">
        <div className="w-12 h-12 rounded-full bg-rose-100 flex items-center justify-center mx-auto mb-4">
          <span className="text-xl">!</span>
        </div>
        <p className="text-sm font-semibold text-rose-600 mb-2">Something went wrong</p>
        <p className="text-xs text-slate-500 mb-8 break-words leading-relaxed">
          {error.message}
        </p>
        <button onClick={() => reset()} className="btn-primary text-sm">
          Try Again
        </button>
      </div>
    </div>
  );
}
