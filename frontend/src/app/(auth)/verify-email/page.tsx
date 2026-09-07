import Link from "next/link";
import { Mail, ArrowRight } from "lucide-react";

export default function VerifyEmailPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-primary px-4">
      <div className="text-center space-y-5 max-w-sm">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-info-100">
          <Mail className="w-8 h-8 text-info-600" />
        </div>
        <h1 className="text-2xl font-semibold text-text-primary">Verify your email</h1>
        <p className="text-sm text-text-secondary">
          We&apos;ve sent a verification link to your email address. Please click the link to activate your account.
        </p>
        <div className="space-y-3 pt-2">
          <p className="text-xs text-text-muted">
            Didn&apos;t receive the email? Check your spam folder or try signing up again.
          </p>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-ai-600 text-white text-sm font-medium hover:bg-ai-700 transition"
          >
            Go to Sign In <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}
