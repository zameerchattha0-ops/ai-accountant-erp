"use client";

import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { createClient } from "@/lib/supabase/client";
import { Eye, EyeOff, Loader2, CheckCircle } from "lucide-react";

export default function SignupPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const supabase = createClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      setLoading(false);
      return;
    }

    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { full_name: fullName },
        emailRedirectTo: `${window.location.origin}/login`,
      },
    });

    if (error) {
      setError(error.message);
      setLoading(false);
      return;
    }

    setSent(true);
    setLoading(false);
  };

  if (sent) {
    return (
      <div className="text-center space-y-4">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-success-100 mb-2">
          <CheckCircle className="w-7 h-7 text-success-600" />
        </div>
        <h1 className="text-2xl font-semibold text-brand-navy">Check your email</h1>
        <p className="text-sm text-text-secondary max-w-xs mx-auto">
          We sent a verification link to <strong>{email}</strong>. Click it to confirm your account, then sign in.
        </p>
        <Link
          href="/login"
          className="inline-block mt-4 px-6 py-2.5 btn-3d btn-shine rounded-xl bg-brand-teal text-white text-sm font-medium hover:bg-brand-navy transition"
        >
          Go to Sign In
        </Link>
      </div>
    );
  }

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
        <h1 className="text-2xl font-semibold text-brand-navy">Create your account</h1>
        <p className="text-sm text-text-secondary mt-1">Start managing your finances with AI</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg bg-error-50 border border-error-100 text-sm text-error-600">
            {error}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-brand-navy mb-1.5">Full Name</label>
          <input
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
            className="w-full px-3 py-2.5 rounded-xl border border-border-default bg-bg-surface text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-brand-teal/30 focus:border-brand-teal transition"
            placeholder="Zameer Ahmed"
          />
        </div>

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
              minLength={8}
              className="w-full px-3 py-2.5 pr-10 rounded-xl border border-border-default bg-bg-surface text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-brand-teal/30 focus:border-brand-teal transition"
              placeholder="At least 8 characters"
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
          {loading ? "Creating account..." : "Create Account"}
        </button>
      </form>

      <p className="text-center text-sm text-text-secondary">
        Already have an account?{" "}
        <Link href="/login" className="text-brand-teal font-medium hover:text-brand-navy">
          Sign in
        </Link>
      </p>
    </div>
  );
}
