"""Actual hierarchical Yosys synthesis with memory-preserving structural checks."""

import gzip
import hashlib
import json
from pathlib import Path

from execution import ROOT


def synthesize(execution, block, depth, width, *, root=ROOT):
    name = f"synthesis-{block}-{depth}-{width}"
    directory = execution.directory
    script = directory / f"{name}.ys"
    netlist = directory / f"{name}.json"
    relative = lambda p: Path(p).relative_to(root).as_posix()
    rtl = sorted(relative(p) for p in (root / "rtl").glob("*.sv"))
    script.write_text(
        "read_verilog -sv " + " ".join(rtl) + "\n"
        f"chparam -set MAX_BLOCK_BYTES {block} -set SG_DEPTH {depth} "
        f"-set COPY_BYTES {width} bellows_l4_top\n"
        "hierarchy -check -top bellows_l4_top\n"
        "proc\nopt_expr\nopt_clean\ncheck -assert -noinit\n"
        "memory -nomap\nopt_clean\ncheck -assert -noinit\nstat\n"
        f"write_json {relative(netlist)}\n"
    )
    execution.run(["yosys", "-Q", "-s", relative(script)], name, cwd=root)
    raw = netlist.read_bytes()
    design = json.loads(raw)
    counts = {}
    memories = 0
    for module in design["modules"].values():
        if module.get("attributes", {}).get("blackbox"):
            raise AssertionError("functional blackbox in synthesized hierarchy")
        for cell in module.get("cells", {}).values():
            kind = cell["type"]
            counts[kind] = counts.get(kind, 0) + 1
            if "latch" in kind.lower() or kind in ("$div", "$mod", "$divfloor", "$modfloor"):
                raise AssertionError(f"forbidden synthesized cell {kind}")
            if kind.startswith("$mem"):
                memories += 1
    top_cells = design["modules"]["bellows_l4_top"]["cells"]
    for module_name, count in (("bellows_l4_context", 4),
                               ("bellows_l4_scheduler", 1), ("bellows_l4_sg_dma", 1)):
        actual = sum(module_name in c["type"] for c in top_cells.values())
        if actual != count:
            raise AssertionError(f"actual hierarchy {module_name}: {actual}, required {count}")
    context_types = {c["type"] for c in top_cells.values() if "bellows_l4_context" in c["type"]}
    for context_type in context_types:
        cells = design["modules"][context_type]["cells"]
        for name_part in ("bellows_l4_lz4_decoder", "bellows_l4_copy_engine",
                          "bellows_l4_entropy", "bellows_l3_checksum"):
            if not any(name_part in c["type"] for c in cells.values()):
                raise AssertionError(f"missing synthesized context unit {name_part}")
    if memories == 0:
        raise AssertionError("synthesis did not retain inferred memories")
    compressed = netlist.with_suffix(".json.gz")
    with compressed.open("xb") as out:
        out.write(gzip.compress(raw, mtime=0))
    if gzip.decompress(compressed.read_bytes()) != raw:
        raise AssertionError("netlist compression round-trip")
    record = {"parameters": [block, depth, width], "memories": memories,
              "zero_latches": True, "zero_div_mod": True,
              "netlist": execution.relative(compressed),
              "uncompressed_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
              "compressed_sha256": hashlib.sha256(compressed.read_bytes()).hexdigest(),
              "cell_types": counts}
    netlist.unlink()
    execution.receipt.setdefault("structural_results", []).append(record)
    execution.save()
    return record
