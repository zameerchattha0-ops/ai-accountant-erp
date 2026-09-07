import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4">
      <h1 className="text-6xl font-bold text-text-primary">404</h1>
      <p className="text-lg text-text-secondary mt-4">Page not found</p>
      <Link
        href="/"
        className="mt-6 px-5 py-2.5 btn-3d btn-shine rounded-xl bg-ai-500 hover:bg-ai-600 text-white text-sm font-medium transition-colors"
      >
        Go to dashboard
      </Link>
    </div>
  );
}
