import { Badge } from "@/components/ui/badge";
import { ArrowRight, ArrowDown } from "lucide-react";

interface TransferArrowProps {
  fields: string[];
  direction?: "right" | "down";
}

export function TransferArrow({ fields, direction = "right" }: TransferArrowProps) {
  if (direction === "down") {
    return (
      <div className="flex flex-col items-center gap-1 py-2">
        <div className="flex flex-col items-center gap-1">
          {fields.map((f, i) => (
            <Badge
              key={i}
              className="bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px]"
            >
              {f}
            </Badge>
          ))}
        </div>
        <ArrowDown className="h-5 w-5 text-amber-400" />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center gap-1 px-2 self-center">
      <div className="flex flex-wrap items-center justify-center gap-1">
        {fields.map((f, i) => (
          <Badge
            key={i}
            className="bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px]"
          >
            {f}
          </Badge>
        ))}
      </div>
      <ArrowRight className="h-5 w-5 text-amber-400" />
    </div>
  );
}
