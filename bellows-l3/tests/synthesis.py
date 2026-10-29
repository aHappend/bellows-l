"""Memory-preserving generic synthesis and explicit elaboration diagnostics."""

import collections
import json
import re

from retention import write_json


def structural_rules(root):
    results = {}
    for path in sorted(root.glob("rtl/*.sv")):
        text = path.read_text()
        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        assert not re.search(r"[/%]", text), f"division/remainder operator: {path.name}"
        # Sequential blocks can contain nested begin/end and case statements.
        for match in re.finditer(r"always\s*@\s*\([^)]*posedge[^)]*\)\s*begin", text):
            depth, end = 1, match.end()
            for token in re.finditer(r"\bbegin\b|\bend\b", text[match.end():]):
                depth += 1 if token.group() == "begin" else -1
                if depth == 0:
                    end = match.end() + token.start()
                    break
            body = text[match.end():end]
            blocking = re.search(r"(?<![<>=!])=(?!=)", body)
            nonblocking = "<=" in body
            assert not (blocking and nonblocking), (
                f"mixed blocking/nonblocking sequential assignments: {path.name}")
        results[path.name] = {"division_or_remainder": 0, "mixed_sequential": 0}
    return results


def arithmetic_boundaries(modules):
    """Reject dependent arithmetic after a multiplier without a register."""
    measurements = {}
    arithmetic = {"$add", "$sub", "$mul", "$xor", "$shl", "$shr", "$sshl", "$sshr"}
    for module_name, module in modules.items():
        cells = module.get("cells", {})
        combinational = {
            name: cell for name, cell in cells.items()
            if cell["type"] not in modules and
            not any(token in cell["type"].lower() for token in ("dff", "mem", "latch"))
        }
        drivers = {}
        for name, cell in combinational.items():
            for port, direction in cell["port_directions"].items():
                if direction == "output":
                    for bit in cell["connections"][port]:
                        if isinstance(bit, int):
                            drivers[bit] = name
        predecessors = {}
        for name, cell in combinational.items():
            predecessors[name] = {
                drivers[bit]
                for port, direction in cell["port_directions"].items() if direction == "input"
                for bit in cell["connections"][port] if bit in drivers
            }
        pending, computed = set(combinational), {}
        while pending:
            ready = [name for name in pending if predecessors[name] <= computed.keys()]
            assert ready, ("combinational cycle in synthesized module", module_name)
            for name in ready:
                depth = 1 + max((computed[p][0] for p in predecessors[name]), default=0)
                upstream_multiplier = any(computed[p][1] for p in predecessors[name])
                kind = combinational[name]["type"]
                assert not (upstream_multiplier and kind in arithmetic), (
                    "unregistered dependent multiply/arithmetic", module_name, name, kind)
                computed[name] = depth, upstream_multiplier or kind == "$mul"
                pending.remove(name)
        measurements[module_name] = max((value[0] for value in computed.values()), default=0)
    return measurements


def synthesize(run, top, block=None, sg=None, label=None):
    label = label or f"synth-{top}-{block}-{sg}"
    directory = run.path / label
    directory.mkdir()
    script, netlist = directory / "synthesis.ys", directory / "netlist.json"
    rtl = " ".join(run.relative(p) for p in sorted(run.root.glob("rtl/*.sv")))
    commands = [f"read_verilog -sv {rtl}"]
    if block is not None:
        commands.append(f"chparam -set MAX_BLOCK_BYTES {block} {top}")
    if sg is not None:
        commands.append(f"chparam -set SG_DEPTH {sg} {top}")
    commands.extend([
        f"hierarchy -check -top {top}",
        "proc", "opt_expr", "opt_clean", "check -assert",
        "memory -nomap", "opt", "opt_clean", "check -assert",
        "select -assert-none t:$dlatch t:$adlatch t:$_DLATCH_*",
        "select -assert-none t:$div t:$mod t:$divfloor t:$modfloor",
        "stat", f"write_json {run.relative(netlist)}",
    ])
    script.write_text("\n".join(commands) + "\n")
    run.command(["yosys", "-s", run.relative(script)], label)
    design = json.loads(netlist.read_text())["modules"]
    logic_depths = arithmetic_boundaries(design)
    types = collections.Counter()
    memories = 0
    instances = []

    def visit(name, prefix=""):
        nonlocal memories
        module = design[name]
        for cell_name, cell in module.get("cells", {}).items():
            cell_type = cell["type"]
            path = prefix + cell_name
            if cell_type in design:
                instances.append(path)
                visit(cell_type, path + ".")
            else:
                types[cell_type] += 1
                assert "latch" not in cell_type.lower(), ("latch", path, cell_type)
                assert cell_type not in ("$div", "$mod", "$divfloor", "$modfloor")
                if cell_type.startswith("$mem"):
                    params = cell["parameters"]
                    if "SIZE" in params and "WIDTH" in params:
                        memories += int(params["SIZE"], 2) * int(params["WIDTH"], 2)

    visit(top)
    sequential = sum(count for name, count in types.items()
                     if any(token in name.lower() for token in ("dff", "mem")))
    assert sequential > 10, ("missing substantive state", sequential)
    assert memories >= 65536 * 8, ("history memory missing or expanded", memories)
    if top == "bellows_l3_top":
        for lane in range(4):
            base = f"lanes[{lane}].context"
            for suffix in ("", ".codec", ".checksum", ".codec.compressor",
                           ".codec.compressor.literal_buffer",
                           ".codec.compressor.hash_match", ".codec.compressor.emitter",
                           ".codec.decompressor", ".codec.decompressor.history",
                           ".codec.decompressor.output_stage"):
                assert base + suffix in instances, ("hierarchy", base + suffix)
        assert "scheduler" in instances and "dma" in instances
        assert memories >= 4 * 65536 * 8
    summary = {"top": top, "MAX_BLOCK_BYTES": block, "SG_DEPTH": sg,
               "sequential_or_memory_cells": sequential, "memory_bits": memories,
               "latches": 0, "cell_types": dict(types), "instances": instances,
               "generic_combinational_cell_depths_not_physical_timing": logic_depths,
               "netlist": run.relative(netlist), "script": run.relative(script)}
    write_json(directory / "statistics.json", summary)
    return summary


def elaborations(run, cells):
    rtl = [run.relative(p) for p in sorted(run.root.glob("rtl/*.sv"))]
    for block in sorted(set(b for b, _ in cells)):
        for sg in (1, 3, 16):
            run.command(["iverilog", "-g2012", "-Wall", "-s", "bellows_l3_top",
                         "-P", f"bellows_l3_top.MAX_BLOCK_BYTES={block}",
                         "-P", f"bellows_l3_top.SG_DEPTH={sg}",
                         "-t", "null", *rtl], f"elaborate-{block}-{sg}")
    for block, sg in ((0, 1), (65537, 1), (1, 0), (1, 17)):
        output = run.path / f"illegal-{block}-{sg}.vvp"
        run.command(["iverilog", "-g2012", "-Wall", "-s", "bellows_l3_top",
                     "-P", f"bellows_l3_top.MAX_BLOCK_BYTES={block}",
                     "-P", f"bellows_l3_top.SG_DEPTH={sg}",
                     "-o", run.relative(output), *rtl], f"illegal-compile-{block}-{sg}")
        stdout, stderr = run.command(["vvp", run.relative(output)],
                                     f"illegal-run-{block}-{sg}", expected=(1,))
        assert "PARAMETER ERROR" in stdout + stderr, "missing explicit parameter diagnostic"


def check(run, cells):
    for tool in ("yosys", "iverilog", "vvp"):
        run.tool(tool)
    rules = structural_rules(run.root)
    elaborations(run, cells)
    summaries = [synthesize(run, "bellows_l3_top", b, sg)
                 for b, sg in ((65536, 16), (1, 1), (3, 3))]
    summaries.extend((synthesize(run, "bellows_l1_top"),
                      synthesize(run, "bellows_l2_top", 65536)))
    write_json(run.path / "synthesis-summary.json",
               {"structural_rules": rules, "netlists": summaries})
