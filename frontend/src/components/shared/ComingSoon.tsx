import { Sparkles } from "lucide-react";

interface ComingSoonProps {
  title: string;
  description: string;
}

/**
 * Placeholder for sidebar routes that are designed but not yet implemented.
 * Keeps navigation free of 404s while clearly signalling build status.
 */
export default function ComingSoon({ title, description }: ComingSoonProps) {
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl lg:text-2xl font-semibold text-text-primary">{title}</h1>
        <p className="text-sm text-text-secondary mt-0.5">Coming soon</p>
      </div>
      <div className="clay bg-bg-surface p-10 flex flex-col items-center text-center">
        <div className="w-14 h-14 rounded-2xl bg-ai-100 flex items-center justify-center mb-4">
          <Sparkles className="w-6 h-6 text-ai-600" />
        </div>
        <h2 className="text-base font-semibold text-text-primary">{title} is on the roadmap</h2>
        <p className="text-sm text-text-secondary mt-2 max-w-md">{description}</p>
        <p className="text-xs text-text-muted mt-4">
          Meanwhile, try the AI Command Box on the dashboard - most of this
          functionality is already available conversationally.
        </p>
      </div>
    </div>
  );
}
