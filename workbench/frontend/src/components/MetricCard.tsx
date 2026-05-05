import { Card } from "@/components/ui/card";

export function MetricCard({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <Card className="p-5">
      <div className="editorial-kicker">{label}</div>
      <div className="mt-3 font-mono text-[2rem] font-semibold tracking-tight text-slate-950">
        {value}
      </div>
      <div className="mt-2 h-px w-10 bg-sage-200" />
    </Card>
  );
}
