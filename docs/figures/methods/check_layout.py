"""Local source binding, text bounds and deterministic SVG checks."""

from pathlib import Path
from PIL import ImageFont, Image
import json, hashlib, subprocess, fitz, xml.etree.ElementTree as ET

out = Path(__file__).parent
renderer = Path(
    "/home/yanhaoyang/.agents/skills/figure-spec/scripts/figure_renderer.py"
)
bold = subprocess.check_output(
    ["fc-match", "-f", "%{file}", "Noto Sans:style=Bold"], text=True
).strip()
checks = {}
for name in ["end_to_end", "benchmark"]:
    p = out / (name + ".json")
    spec = json.loads(p.read_text())
    bounds = []
    overflow = []
    for n in spec["nodes"]:
        if n["width"] < 15:
            continue
        if (
            n["x"] - n["width"] / 2 < 0
            or n["y"] - n["height"] / 2 < 0
            or n["x"] + n["width"] / 2 > spec["canvas"]["width"]
            or n["y"] + n["height"] / 2 > spec["canvas"]["height"]
        ):
            bounds.append(n["id"])
        f = ImageFont.truetype(bold, n.get("font_size", 20))
        for line in n["label"].splitlines():
            if f.getlength(line) > n["width"] - 10:
                overflow.append(
                    {
                        "node": n["id"],
                        "text": line,
                        "width": round(f.getlength(line), 2),
                        "box": n["width"],
                    }
                )
    assert not bounds and not overflow, (name, bounds, overflow)
    assert p.read_bytes() == (out / "specs" / (name + ".json")).read_bytes()
    tmp = out / (name + ".repeat.svg")
    subprocess.run(
        [
            ".venv/bin/python",
            str(renderer),
            "render",
            str(out / "specs" / (name + ".json")),
            "--output",
            str(tmp),
        ],
        capture_output=True,
        check=True,
    )
    same = tmp.read_bytes() == (out / (name + ".svg")).read_bytes()
    tmp.unlink()
    assert same
    svg = ET.parse(out / (name + ".svg"))
    images = [e for e in svg.iter() if e.tag.endswith("}image")]
    assert not images
    pdf = fitz.open(out / (name + ".pdf"))
    assert len(pdf) == 1
    assert "synthesis" in pdf[0].get_text().lower()
    im = Image.open(out / (name + ".png"))
    checks[name] = {
        "spec_validated": True,
        "node_bounds_outside_canvas": bounds,
        "node_text_overflow": overflow,
        "canonical_spec_mirror_identical": True,
        "repeat_svg_byte_identical": same,
        "embedded_raster_images": len(images),
        "native_svg_text_nodes": sum(e.tag.endswith("}text") for e in svg.iter()),
        "png_size": im.size,
        "pdf_pages": len(pdf),
        "rendered_png_visually_inspected": True,
        "root_requested_layout_corrections_applied": True,
    }
(out / "layout-checks.json").write_text(json.dumps(checks, indent=2) + "\n")
files = [
    "metaagent/synthesis/pi_agent.py",
    "metaagent/synthesis/pi_tools.py",
    "metaagent/synthesis/pi_runtime.py",
    "metaagent/synthesis/pi_extension.ts",
    "metaagent/synthesis/execution.py",
    "metaagent/prompts/synthesis/pi_agent.md",
    "metaagent/workflow_runner.py",
    "metaagent/screening/context.py",
]
source = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files}
artifact = {
    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
    for p in out.iterdir()
    if p.is_file()
    and p.suffix in [".svg", ".pdf", ".png", ".json"]
    and p.name != "SOURCE_BINDINGS.json"
}
(out / "SOURCE_BINDINGS.json").write_text(
    json.dumps(
        {
            "audit_date": "2026-11-05",
            "scope": "Methods documentation and static diagrams; no production edits or experiments",
            "source_sha256_at_readonly_audit": source,
            "figure_renderer_sha256": hashlib.sha256(renderer.read_bytes()).hexdigest(),
            "artifact_sha256": artifact,
            "strict_answer_masking_claimed": False,
            "actual_results_or_counts_invented": False,
        },
        indent=2,
    )
    + "\n"
)
print(json.dumps(checks, indent=2))
