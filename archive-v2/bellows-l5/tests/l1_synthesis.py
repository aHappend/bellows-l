"""Memory-preserving real Yosys synthesis and structural acceptance."""

import gzip
import hashlib
import json
from pathlib import Path


def _digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def retain_netlist(path):
    size, digest = _digest(path)
    compressed = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as source, compressed.open("xb") as target:
        with gzip.GzipFile(fileobj=target, mode="wb", mtime=0) as zipper:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                zipper.write(chunk)
    verified = hashlib.sha256()
    restored_size = 0
    with gzip.open(compressed, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            restored_size += len(chunk)
            verified.update(chunk)
    if restored_size != size or verified.hexdigest() != digest:
        raise AssertionError("complete synthesized netlist failed lossless retention")
    path.unlink()
    packed_size, packed_digest = _digest(compressed)
    return {"path": compressed.name, "uncompressed_bytes": size,
            "uncompressed_sha256": digest, "compressed_bytes": packed_size,
            "compressed_sha256": packed_digest}


def inspect_netlist(netlist):
    modules = netlist["modules"]
    top = modules["bellows_l5_top"]
    required = []
    counts = {}
    memory_bits = 0
    instances = []

    def visit(name, module, ancestors):
        nonlocal memory_bits
        if module.get("attributes", {}).get("blackbox", "0").strip("0"):
            raise AssertionError(f"unexpected black box: {name}")
        for cell_name, cell in module.get("cells", {}).items():
            path = name + "." + cell_name
            kind = cell["type"]
            counts[kind] = counts.get(kind, 0) + 1
            if "latch" in kind.lower():
                raise AssertionError(f"inferred latch at {path}")
            if kind in ("$div", "$mod", "$divfloor", "$modfloor"):
                raise AssertionError(f"forbidden combinational division/modulo at {path}")
            if kind in modules:
                if kind in ancestors:
                    raise AssertionError(f"recursive hierarchy at {path}")
                instances.append(path)
                visit(path, modules[kind], ancestors | {kind})
            elif kind in ("$mem_v2", "$mem"):
                parameters = cell["parameters"]
                width = int(parameters["WIDTH"], 2)
                size = int(parameters["SIZE"], 2)
                memory_bits += width * size
                if width * size >= 16384:
                    clocks = cell["connections"].get("RD_CLK", [])
                    enabled = int(parameters.get("RD_CLK_ENABLE", "0"), 2)
                    if not clocks or enabled == 0:
                        raise AssertionError(f"large RAM has no synchronous read port: {path}")
            elif not kind.startswith("$"):
                raise AssertionError(f"unresolved module/cell: {path}: {kind}")
        for port_name in ("status_valid", "m_valid", "dict_loaded"):
            port = module.get("ports", {}).get(port_name)
            if port and port["direction"] == "output" and all(
                    isinstance(bit, str) for bit in port["bits"]):
                raise AssertionError(f"constant functional output: {name}.{port_name}")

    visit("bellows_l5_top", top, {"bellows_l5_top"})
    for lane in range(4):
        base = f"bellows_l5_top.lanes[{lane}].context"
        required.extend((base, base + ".legacy", base + ".zstd",
                         base + ".zstd.entropy", base + ".zstd.engine",
                         base + ".zstd.engine.matcher", base + ".zstd.engine.content_hash",
                         base + ".zstd.entropy.encoder"))
        for alphabet in ("ll", "ml", "of"):
            required.append(base + f".zstd.entropy.fse_{alphabet}_decoder")
    required.extend(("bellows_l5_top.dictionary", "bellows_l5_top.scheduler",
                     "bellows_l5_top.dma"))
    missing = sorted(set(required) - set(instances))
    if missing:
        raise AssertionError(f"missing production hierarchy: {missing}")
    if memory_bits == 0:
        raise AssertionError("no retained functional memories")
    return {"cells_by_type": counts, "retained_memory_bits_with_replication": memory_bits,
            "required_instances": required, "hierarchical_instances": len(instances),
            "latches": 0, "black_boxes": 0}


def synthesis(experiment, geometries):
    experiment.command("yosys-version", ["yosys", "-V"])
    summaries = []
    for name, geometry in geometries:
        block, sg, copy, dictionary = geometry
        script = experiment.directory / f"synthesis-{name}.ys"
        script.write_text(
            "read_verilog -sv source/rtl/*.sv\n"
            f"chparam -set MAX_BLOCK_BYTES {block} -set SG_DEPTH {sg} "
            f"-set COPY_BYTES {copy} -set DICT_BYTES {dictionary} bellows_l5_top\n"
            "hierarchy -check -top bellows_l5_top\n"
            "proc\nopt_expr\nopt_clean\ncheck -assert\n"
            "opt\nfsm\nopt\nmemory -nomap\nopt_clean\n"
            "techmap\nopt_clean\ncheck -assert\nstat\n"
            f"write_json netlist-{name}.json\n")
        experiment.command(f"yosys-{name}", ["yosys", "-T", "-s", script.name], timeout=2400)
        path = experiment.directory / f"netlist-{name}.json"
        try:
            with path.open() as stream:
                checks = inspect_netlist(json.load(stream))
        finally:
            retained = retain_netlist(path)
        summaries.append({"configuration": name, "geometry": geometry,
                          "structure": checks, "netlist": retained})
        (experiment.directory / "synthesis-summary.json").write_text(
            json.dumps(summaries, indent=2) + "\n")
    return summaries
