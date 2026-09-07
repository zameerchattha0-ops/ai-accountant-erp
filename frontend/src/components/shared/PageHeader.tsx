import Image from "next/image";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  logoUrl?: string | null;
}

export default function PageHeader({ title, subtitle, actions, logoUrl }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-3">
      {logoUrl && (
        <Image
          src={logoUrl}
          alt="Organization logo"
          width={140}
          height={40}
          className="h-8 w-auto object-contain"
        />
      )}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl lg:text-2xl font-semibold text-text-primary">{title}</h1>
          {subtitle && <p className="text-sm text-text-secondary mt-0.5">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
