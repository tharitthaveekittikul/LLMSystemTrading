import { Separator } from "@/components/ui/separator";

interface AppHeaderProps {
  title: string;
  children?: React.ReactNode;
}

export function AppHeader({ title, children }: AppHeaderProps) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
      <Separator orientation="vertical" className="mr-2 h-4" />
      <h1 className="font-semibold">{title}</h1>
      {children && <div className="ml-auto">{children}</div>}
    </header>
  );
}
