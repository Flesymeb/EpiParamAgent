import ReactECharts from "echarts-for-react";

import type { ConfusionMatrix, CountItem } from "@/types";

export function FunnelPanel({
  items,
  matrix,
}: {
  items: CountItem[];
  matrix?: ConfusionMatrix | null;
}) {
  const pool = items.find((item) => item.label === "Paper Pool")?.count ?? 0;
  const screened =
    matrix ?
      matrix.tp + matrix.fp
    : (items.find((item) => item.label === "Screened Relevant")?.count ?? 0);
  const gt =
    matrix ?
      matrix.tp + matrix.fn
    : (items.find((item) => item.label === "GT")?.count ?? 0);

  const data = [
    { name: "Paper Pool", value: pool },
    {
      name:
        matrix && matrix.fp > 0 ?
          `Screened Relevant\nFP ${matrix.fp}`
        : "Screened Relevant",
      value: screened,
    },
    {
      name:
        matrix ?
          `GT\nTP ${matrix.tp} | FN ${matrix.fn}`
        : "GT",
      value: gt,
    },
  ].filter((item) => item.value > 0);

  return (
    <div className="bg-sage-50/35 p-4">
      <div className="mb-3 section-title">Research Flow</div>
      <ReactECharts
        style={{ height: 240 }}
        option={{
          animationDuration: 420,
          tooltip: { trigger: "item", formatter: "{b}: {c}" },
          series: [
            {
              type: "funnel",
              sort: "descending",
              gap: 10,
              left: "18%",
              right: "18%",
              top: 6,
              bottom: 6,
              minSize: "22%",
              maxSize: "100%",
              width: "64%",
              label: {
                show: true,
                position: "inside",
                formatter: "{b}\n{c}",
                color: "#ffffff",
                fontWeight: 600,
                fontSize: 12,
              },
              itemStyle: {
                borderColor: "#f8fafb",
                borderWidth: 3,
              },
              color: ["#486672", "#69848f", "#8ba86f"],
              data,
            },
          ],
        }}
      />
    </div>
  );
}
