import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-3.5rem)] px-6">
      <div className="glass p-12 text-center max-w-sm animate-fade-in">
        <div className="text-6xl font-bold bg-gradient-to-r from-cyan-500 to-purple-500 bg-clip-text text-transparent mb-4">
          404
        </div>
        <p className="text-sm text-slate-500 mb-8">
          This page does not exist.
        </p>
        <Link href="/" className="btn-primary inline-block text-sm">
          Go Home
        </Link>
      </div>
    </div>
  );
}
