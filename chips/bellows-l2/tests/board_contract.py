"""Verify the independently bound NETSYS17 package without board access."""

import json
from pathlib import Path

from matched_workload import corpus, publish, sha256
from oracle import frozen, role

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "platform-inputs/netsys17/host-board-reference.json"
CONFIG = "tests/platform_config.json"
GOLDEN = "tests/black_box_oracle.json"
BOARD = "fpga/board_hil.json"
PS = "tests/business-test.ps1"
CS = "tests/Workload.cs"
MAGIC = "0x42454c4c4f574c32"
DMA_OWNERSHIP = ("SoftReg-only PCIe BAR0 MMIO workload at offset 0x800000 via IOCTL 0xB0B28004; "
                 "no host DMA buffers allocated or used.")
PROTOCOL = "softreg-readback/v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def binding(path):
    return {"path": path, "sha256": sha256((ROOT / path).read_bytes())}


def intended_vectors():
    cases = frozen(ROOT / GOLDEN)
    for name in ("compress_overlap", "decode_external", "roundtrip_distinct"):
        yield name, GOLDEN, cases[name]
    name, raw, expected = next(block for block in corpus() if block[0] == "structured_4096")
    yield name, "tests/oracle.py", (0, raw, len(expected), expected, 0)


def envelope(mode, data, capacity, expected, code):
    return {"inputs": {"mode": mode, "input_hex": data.hex(), "output_capacity": capacity,
                       "expected_output_length": len(expected), "expected_completion": code,
                       "expected_output_sha256": sha256(expected)}}


def contract():
    from vulcan_agent.board_campaign import workload_payload, workload_vectors

    reference = json.loads((ROOT / REFERENCE).read_bytes())
    cfg = json.loads((ROOT / CONFIG).read_bytes())
    require(cfg == reference["platform_config_template"], "Product config differs from the NETSYS17 template")
    for path in ("prior_campaign", "prior_campaign_result"):
        require(binding(cfg[path])["sha256"] == cfg[f"{path}_sha256"], f"{path} binding differs")
    require(binding(cfg["prior_image"])["sha256"] == reference["prior_image_sha256"], "Prior image hash differs")
    entry = reference["collector_entrypoint"]
    require((ROOT / entry["path"]).read_text() == entry["exact_python_source"], "Collector must be the Runtime adapter")

    hil = json.loads((ROOT / BOARD).read_bytes())
    require(hil.keys() == {"expected_magic_hex", "runs", "native_collector", "experiment_plan"},
            "Board config contains an unsupported field")
    require(hil["expected_magic_hex"] == MAGIC and hil["runs"] == 3, "Wrong Bellows identity or repeat count")
    require(hil["native_collector"] == {
        "argv": ["python3", "tests/collector.py", "--config", CONFIG],
        "managed_board_owner": True, "timeout_s": 4800, "configuration": binding(CONFIG),
        "dma_ownership": DMA_OWNERSHIP, "api_sources": [binding(REFERENCE)],
        "workload_sources": {"business_script": binding(PS), "companion": binding(CS)},
    }, "Wrong Runtime collector or stale workload/API binding")

    plan = hil["experiment_plan"]
    require(plan["protocol"] == "reviewed-native-v1" and plan["workload_protocol"] == PROTOCOL,
            "Wrong native workload protocol")
    required = list(intended_vectors())
    published = json.loads((ROOT / GOLDEN).read_bytes())["cases"]
    require(len(plan["vectors"]) == len(required), "Required board vectors missing")
    rows, expected_staged = [], []
    for vector, (name, source, values) in zip(plan["vectors"], required, strict=True):
        prefix = f"tests/board_vectors/{name}"
        inp, gold = f"{prefix}.json", f"{prefix}.bin"
        require(vector == {"id": name, "input": binding(inp), "expected": binding(gold),
                           "oracle_source": binding(source), "comparison": {"format": "bytes"}},
                f"{name}: stale or incorrect vector binding")
        mode, raw, cap, expected, code = values
        expected_input = {"inputs": published[name]["inputs"]} if source == GOLDEN else envelope(*values)
        actual_input = json.loads((ROOT / inp).read_bytes())
        require(json.dumps(actual_input, sort_keys=True) == json.dumps(expected_input, sort_keys=True),
                f"{name}: staged input differs from {source}")
        require(expected and code == 0 and (ROOT / gold).read_bytes() == expected
                and role(mode, raw, cap) == (expected, code), f"{name}: exact oracle output differs")
        expected_staged.append({"id": name, **expected_input})
        rows.append({"id": name, "mode": mode, "input_bytes": len(raw), "input_sha256": sha256(raw),
                     "expected_bytes": len(expected), "expected_sha256": sha256(expected),
                     "oracle_source": vector["oracle_source"]})
    staged = workload_payload(hil, PROTOCOL, workload_vectors(ROOT, hil, PROTOCOL))
    require(staged == {"schema": 1, "workload_protocol": PROTOCOL,
                       "runs": [{"vectors": expected_staged}] * hil["runs"]},
            "Runtime staging does not preserve the admitted inputs, order and repeats")
    return {"schema": "bellows-l2-board-contract/v1", "offline_only": True, "hardware_access": False,
            "board_config": binding(BOARD), "collector": hil["native_collector"], "runs": hil["runs"],
            "vectors": rows, "planned_comparisons": len(rows) * hil["runs"]}


if __name__ == "__main__":
    publish(ROOT / "evidence/board_contract.json", contract())
