"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { createClient } from "@/lib/supabase/client";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import dynamic from "next/dynamic";

/* 3D mascot — client-only so WebGL never touches the server */
const HeroRobotStage = dynamic(() => import("@/components/welcome/HeroRobot"), {
  ssr: false,
  loading: () => <div className="h-[185px] rounded-[2rem] bg-white/40 animate-pulse" />,
});

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const supabase = createClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    const { error } = await supabase.auth.signInWithPassword({ email, password });

    if (error) {
      setError(error.message);
      setLoading(false);
      return;
    }

    router.push("/");
    router.refresh();
  };

  return (
    <div className="bg-bg-surface/80 backdrop-blur-sm rounded-2xl shadow-lg border border-border-subtle p-8 space-y-6">
      <div className="text-center">
        <div className="flex justify-center mb-5 logo-enter">
          <Image
            src="/ai-accountant.png"
            alt="AI Accountant"
            width={260}
            height={74}
            className="w-full max-w-[240px] h-auto object-contain"
            priority
          />
        </div>
        <h1 className="text-2xl font-semibold text-brand-navy">Welcome back</h1>
        <p className="text-sm text-text-secondary mt-1">Sign in to your AI Accountant</p>
        <div className="mt-4 -mx-4">
          <HeroRobotStage variant="compact" />
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg bg-error-50 border border-error-100 text-sm text-error-600">
            {error}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-brand-navy mb-1.5">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full px-3 py-2.5 rounded-xl border border-border-default bg-bg-surface text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-brand-teal/30 focus:border-brand-teal transition"
            placeholder="you@company.com"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-brand-navy mb-1.5">Password</label>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-3 py-2.5 pr-10 rounded-xl border border-border-default bg-bg-surface text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-brand-teal/30 focus:border-brand-teal transition"
              placeholder="••••••••"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 btn-3d btn-shine rounded-xl bg-brand-teal text-white text-sm font-medium hover:bg-brand-navy focus:outline-none focus:ring-2 focus:ring-brand-teal/30 disabled:opacity-60 transition flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          {loading ? "Signing in..." : "Sign In"}
        </button>
      </form>

      <p className="text-center text-sm text-text-secondary">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="text-brand-teal font-medium hover:text-brand-navy">
          Create one
        </Link>
      </p>
    </div>
  );
}
