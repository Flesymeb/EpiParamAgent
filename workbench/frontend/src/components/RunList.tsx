import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { RunSummary } from "@/types";

export function RunList({
  runs,
  selectedId,
  onSelect,
  title,
}: {
  runs: RunSummary[];
  selectedId?: string;
  onSelect: (id: string) => void;
  title: string;
}) {
  const [query, setQuery] = useState("");
  const [topicFilter, setTopicFilter] = useState("all");
  const [configFilter, setConfigFilter] = useState("all");

  const topics = useMemo(
    () =>
      Array.from(new Set(runs.map((run) => run.topic).filter(Boolean) as string[])).sort(),
    [runs]
  );

  const configs = useMemo(
    () =>
      Array.from(new Set(runs.map((run) => run.config).filter(Boolean) as string[])).sort(),
    [runs]
  );

  const filteredRuns = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return runs.filter((run) => {
      if (topicFilter !== "all" && run.topic !== topicFilter) {
        return false;
      }
      if (configFilter !== "all" && run.config !== configFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      return [run.label, run.topic, run.config, run.timestamp_utc]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [configFilter, query, runs, topicFilter]);

  return (
    <div className="border-t border-sage-100">
      <div className="border-b border-sage-100 px-1 py-4">
        <div className="section-title">{title}</div>
        <div className="mt-1 text-xs text-slate-500">Select a local run to inspect details.</div>
      </div>
      <div className="space-y-3 border-b border-sage-100 px-1 py-4">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by topic, config, label..."
        />
        <div className="grid grid-cols-2 gap-2">
          <select
            value={topicFilter}
            onChange={(event) => setTopicFilter(event.target.value)}
            className="h-10 border border-sage-200/60 bg-white px-3 text-sm text-slate-700 outline-none transition focus:border-sage-400"
          >
            <option value="all">All topics</option>
            {topics.map((topic) => (
              <option key={topic} value={topic}>
                {topic}
              </option>
            ))}
          </select>
          <select
            value={configFilter}
            onChange={(event) => setConfigFilter(event.target.value)}
            className="h-10 border border-sage-200/60 bg-white px-3 text-sm text-slate-700 outline-none transition focus:border-sage-400"
          >
            <option value="all">All configs</option>
            {configs.map((config) => (
              <option key={config} value={config}>
                {config}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="max-h-[620px] overflow-y-auto py-2 pr-1">
        {filteredRuns.map((run) => (
          <button
            key={run.id}
            type="button"
            onClick={() => onSelect(run.id)}
            className={cn(
              "mb-1 w-full border-l-2 px-3 py-3 text-left transition duration-200",
              selectedId === run.id
                ? "border-l-sage-600 bg-sage-50/70"
                : "border-l-transparent bg-transparent hover:bg-sage-50/40"
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-900">
                  {run.config || run.topic || "run"}
                </div>
                <div className="mt-1 flex flex-wrap gap-2">
                  {run.topic ? <Badge tone="stone">{run.topic}</Badge> : null}
                  {run.config ? <Badge tone="blue">{run.config}</Badge> : null}
                </div>
              </div>
              <Badge tone={run.module === "coding_sheet" ? "amber" : "green"}>
                {run.module === "coding_sheet" ? "Extraction" : "Screening"}
              </Badge>
            </div>
            <div className="mt-2 line-clamp-2 text-xs text-slate-500">{run.label}</div>
            {run.timestamp_utc ? (
              <div className="mt-2 text-[11px] text-slate-400">{formatRunTimestamp(run.timestamp_utc)}</div>
            ) : null}
          </button>
        ))}
        {filteredRuns.length === 0 ? (
          <div className="px-3 py-6 text-sm text-slate-500">
            No runs found for the current filters.
          </div>
        ) : null}
      </div>
    </div>
  );
}

function formatRunTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
