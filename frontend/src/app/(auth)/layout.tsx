import AmbientAura from "@/components/shared/AmbientAura";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative isolate min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-aqua-soft via-white to-brand-aqua px-4 overflow-hidden">
      {/* Ambient aura - perpetually moving multi-colour light shade behind
          the login / signup cards (replaces the two static blobs). */}
      <AmbientAura />
      <div className="w-full max-w-md relative z-10">{children}</div>
    </div>
  );
}
