import { Badge } from "@/components/ui/badge";

interface FinalOutputBoxProps {
  icon: React.ElementType;
  title: string;
  fields: string[];
  gateNote?: string;
}

export function FinalOutputBox({ icon: Icon, title, fields, gateNote }: FinalOutputBoxProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border-2 border-emerald-500/60 bg-emerald-500/10 p-4 w-[200px] shrink-0">
      <Icon className="h-5 w-5 text-emerald-400 mb-1.5" />
      <p className="text-xs font-semibold text-emerald-300 text-center">{title}</p>
      <div className="mt-2 flex flex-wrap justify-center gap-1">
        {fields.map((f) => (
          <Badge
            key={f}
            className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[10px]"
          >
            {f}
          </Badge>
        ))}
      </div>
      {gateNote && (
        <div className="mt-2 rounded border border-emerald-500/30 bg-emerald-900/30 px-2 py-1 text-center">
          <p className="text-[10px] text-emerald-400">{gateNote}</p>
        </div>
      )}
    </div>
  );
}
