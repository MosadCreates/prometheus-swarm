"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const result = await login(email, password);
    if (result.ok) {
      router.push("/dashboard");
    } else {
      setError(result.error || "Login failed");
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-3.5rem)] px-6">
      <div className="w-full max-w-sm animate-slide-up">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-[#C96442]" />
            <span className="text-sm font-semibold text-[#1C1B19]">Prometheus Swarm</span>
          </div>
          <h1 className="font-display text-2xl text-[#1C1B19] mb-1">Welcome back</h1>
          <p className="text-sm text-[#8B8982]">Sign in to your account</p>
        </div>

        {error && (
          <div className="mb-5 p-3.5 rounded-xl border border-[#E8E5DF] bg-[#F0EDE8] text-xs text-[#C96442]">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label htmlFor="email" className="block text-xs font-semibold text-[#1C1B19] mb-1.5">Email</label>
            <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="input-field text-sm" placeholder="you@example.com" />
          </div>
          <div>
            <label htmlFor="password" className="block text-xs font-semibold text-[#1C1B19] mb-1.5">Password</label>
            <input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className="input-field text-sm" placeholder="••••••••" />
          </div>
          <button type="submit" disabled={loading} className="btn-accent justify-center text-sm">
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="text-xs text-[#8B8982] text-center mt-6">
          Don&apos;t have an account?{" "}
          <Link href="/register" className="text-[#C96442] hover:text-[#B85535] font-semibold">Create one</Link>
        </p>
      </div>
    </div>
  );
}
