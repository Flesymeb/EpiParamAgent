import ReactECharts from "echarts-for-react";

import type { CountItem } from "@/types";

const COLORS = ["#4f6d7a", "#7c9a6d", "#a7b6be"];

export function BarsPanel({
  decisionCounts,
  stageCounts,
  fulltextCounts,
}: {
  decisionCounts: CountItem[];
  stageCounts: CountItem[];
  fulltextCounts: CountItem[];
}) {
  const blocks = [
    { title: "Decision Mix", data: decisionCounts, color: COLORS[0] },
    { title: "Stages", data: stageCounts, color: COLORS[1] },
    { title: "Full-text", data: fulltextCounts, color: COLORS[2] },
  ];

  return (
    <div className="grid divide-y divide-sage-100 bg-sage-50/35 xl:grid-cols-3 xl:divide-x xl:divide-y-0">
      {blocks.map((block) => (
        <div key={block.title} className="p-4">
          <div className="mb-3 section-title">{block.title}</div>
          <ReactECharts
            style={{ height: 220 }}
            option={{
              animationDuration: 420,
              grid: { left: 0, right: 12, top: 8, bottom: 0, containLabel: true },
              tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
              xAxis: {
                type: "value",
                splitLine: { lineStyle: { color: "#e5ecee" } },
              },
              yAxis: {
                type: "category",
                data: block.data.map((item) => item.label),
                axisTick: { show: false },
                axisLine: { show: false },
              },
              series: [
                {
                  type: "bar",
                  data: block.data.map((item) => item.count),
                  itemStyle: { color: block.color, borderRadius: [0, 8, 8, 0] },
                  barWidth: 16,
                  label: { show: true, position: "right", color: "#334155" },
                },
              ],
            }}
          />
        </div>
      ))}
    </div>
  );
}
