"""Verbatim standalone parent APIs, including history wrap and keep errors."""

from dataclasses import dataclass
from pathlib import Path
import shutil

import oracle
from retention import write_json


@dataclass
class Case:
    operation: int
    source: bytes
    content: bytes
    error: int = 0
    keeps: list | None = None
    overflow: bool = False


TB = r"""
module tb;
  reg clk=0, rst_n;
  always #5 clk=~clk;
  reg roundtrip_enable=0;
  reg [7:0] c_s_data=0, d_s_data=0;
  reg c_s_keep=1, c_s_valid=0, c_s_last=0;
  wire c_s_ready;
  wire [7:0] c_m_data, d_m_data;
  wire c_m_valid,c_m_last,d_m_valid,d_m_last;
  reg c_m_ready=0,d_m_ready=0;
  wire c_status_valid,d_status_valid;
  wire [2:0] c_status_error,d_status_error;
  reg c_status_ready=0,d_status_ready=0;
  reg d_s_valid=0,d_s_last=0;
  wire d_s_ready;
  @INSTANCE@
  wire [29:0] outputs={c_s_ready,c_m_data,c_m_valid,c_m_last,c_status_valid,
                      c_status_error,d_s_ready,d_m_data,d_m_valid,d_m_last,
                      d_status_valid,d_status_error};
  integer inp,outp,result,count,number,operation,length,expected,overflow_mode;
  integer k,byte_value,keep_value,cycle=0,start_cycle;
  integer ccount=0,dcount=0,clast=0,dlast=0;
  integer cdone=0,ddone=0,cerror=0,derror=0;
  reg [7:0] input_bytes[0:131199],cbytes[0:131199],dbytes[0:131199];
  integer keeps[0:131199];
  string cases,results;
  reg pcstall=0,pdstall=0;
  reg [8:0] hc,hd;
  reg [2:0] hcs,hds;
  reg pcsstall=0,pdsstall=0;
  integer cstatus_window=-1,dstatus_window=-1;

  task automatic reset_check;
    if (outputs !== 30'd0) $fatal(1,"PARENT_RESET t=%0t outputs=%h",$time,outputs);
  endtask
  always @(posedge clk or negedge clk) if (!rst_n) reset_check();
  always @(posedge clk) begin
    cycle=cycle+1;
    if (rst_n) begin
      if ((^outputs)===1'bx) $fatal(1,"PARENT_XZ");
      if (pcstall && (!c_m_valid || {c_m_data,c_m_last}!==hc))
        $fatal(1,"PARENT_C_STABILITY");
      if (pdstall && (!d_m_valid || {d_m_data,d_m_last}!==hd))
        $fatal(1,"PARENT_D_STABILITY");
      if (pcsstall && (!c_status_valid || c_status_error!==hcs))
        $fatal(1,"PARENT_C_STATUS_STABILITY");
      if (pdsstall && (!d_status_valid || d_status_error!==hds))
        $fatal(1,"PARENT_D_STATUS_STABILITY");
      pcstall=c_m_valid && !c_m_ready; hc={c_m_data,c_m_last};
      pdstall=d_m_valid && !d_m_ready; hd={d_m_data,d_m_last};
      pcsstall=c_status_valid && !c_status_ready; hcs=c_status_error;
      pdsstall=d_status_valid && !d_status_ready; hds=d_status_error;
      if (c_m_valid && c_m_ready) begin
        if (clast || ccount>=131200) $fatal(1,"PARENT_C_AFTER_LAST");
        cbytes[ccount]=c_m_data; ccount=ccount+1;
        if (c_m_last) clast=clast+1;
      end
      if (d_m_valid && d_m_ready) begin
        if (dlast || dcount>=131200) $fatal(1,"PARENT_D_AFTER_LAST");
        dbytes[dcount]=d_m_data; dcount=dcount+1;
        if (d_m_last) dlast=dlast+1;
      end
      if (c_status_valid && c_status_ready) begin
        if (cdone) $fatal(1,"PARENT_C_DUPLICATE_STATUS");
        cdone=1; cerror=c_status_error;
      end
      if (d_status_valid && d_status_ready) begin
        if (ddone) $fatal(1,"PARENT_D_DUPLICATE_STATUS");
        ddone=1; derror=d_status_error;
      end
      if (cycle-start_cycle>@CYCLE_LIMIT@) $fatal(1,"PARENT_CYCLE_BOUND case=%0d",number);
      @SMOKE_BOUND@
    end
  end
  always @(negedge clk) if (rst_n) begin
    c_m_ready=(cycle%29>=17);
    d_m_ready=(cycle%31>=17);
    if (c_status_valid && cstatus_window<0) cstatus_window=cycle+17;
    if (d_status_valid && dstatus_window<0) dstatus_window=cycle+17;
    c_status_ready=cstatus_window>=0 && cycle>=cstatus_window;
    d_status_ready=dstatus_window>=0 && cycle>=dstatus_window;
  end
  initial begin
    rst_n=0;
`ifdef VERILATOR
    #1;
`else
    #0;
`endif
    reset_check();
    if (!$value$plusargs("case=%s",cases) ||
        !$value$plusargs("result=%s",results)) $fatal(1,"PARENT_ARGS");
    inp=$fopen(cases,"r"); outp=$fopen(results,"w");
    if (!inp || !outp) $fatal(1,"PARENT_FILES");
    result=$fscanf(inp,"%d",count); if(result!=1) $fatal(1,"PARENT_SCAN");
    repeat(3) @(negedge clk);
    #1; rst_n=1;
    for (number=0;number<count;number=number+1) begin
      result=$fscanf(inp,"%d %d %d %d",operation,length,expected,overflow_mode);
      if(result!=4) $fatal(1,"PARENT_SCAN");
      if (!overflow_mode)
        for (k=0;k<length;k=k+1) begin
          result=$fscanf(inp,"%h %d",byte_value,keep_value);
          if(result!=2) $fatal(1,"PARENT_SCAN");
          input_bytes[k]=byte_value; keeps[k]=keep_value;
        end
      start_cycle=cycle; ccount=0; dcount=0; clast=0; dlast=0;
      cdone=0; ddone=0; cerror=0; derror=0;
      cstatus_window=-1; dstatus_window=-1;
      roundtrip_enable=(operation==2);
      for (k=0;k<length;k=k+1) begin
        @(negedge clk);
        if (operation==1) begin
          d_s_valid=1; d_s_last=(k==length-1);
          d_s_data=overflow_mode ? (k==0 ? 8'hf0 :
                                    k==length-1 ? 8'h00 : 8'hff) : input_bytes[k];
          do @(posedge clk); while(!d_s_ready);
        end else begin
          c_s_valid=1; c_s_last=(k==length-1);
          c_s_keep=keeps[k]; c_s_data=input_bytes[k];
          do @(posedge clk); while(!c_s_ready);
        end
      end
      @(negedge clk); c_s_valid=0; c_s_last=0; d_s_valid=0; d_s_last=0;
      if (operation==0) wait(cdone);
      else if (operation==1) wait(ddone);
      else wait(cdone && ddone);
      @(negedge clk);
      if (operation!=1 && ccount>0 && clast!=1) $fatal(1,"PARENT_C_LAST");
      if (operation!=0 && dcount>0 && dlast!=1) $fatal(1,"PARENT_D_LAST");
      if (operation==2 && (ccount!=0 || c_m_valid || d_s_ready))
        $fatal(1,"PARENT_ROUNDTRIP_PORTS");
      $fwrite(outp,"PARENT %0d %0d %0d %0d ",number,cerror,derror,
              operation==0 ? ccount : dcount);
      for(k=0;k<(operation==0 ? ccount : dcount);k=k+1)
        $fwrite(outp,"%02h",operation==0 ? cbytes[k] : dbytes[k]);
      $fwrite(outp,"\n");
      repeat(3) @(negedge clk);
    end
    $fclose(inp); $fclose(outp);
    $display("PARENT_COMPLETE comparisons=%0d cycles=%0d",count,cycle);
    $finish;
  end
endmodule
"""

L2_INSTANCE = "bellows_l2_top #(.MAX_BLOCK_BYTES(64)) dut (.*);"
L1_INSTANCE = """
  assign c_s_ready=0;
  assign c_m_data=0;
  assign c_m_valid=0;
  assign c_m_last=0;
  assign c_status_valid=0;
  assign c_status_error=0;
  bellows_l1_top dut (.clk(clk),.rst_n(rst_n),.s_data(d_s_data),
    .s_valid(d_s_valid),.s_last(d_s_last),.s_ready(d_s_ready),
    .m_data(d_m_data),.m_valid(d_m_valid),.m_last(d_m_last),.m_ready(d_m_ready),
    .status_valid(d_status_valid),.status_error(d_status_error),
    .status_ready(d_status_ready));
"""


def cases(full=False, l1=False):
    collection = []
    if not l1:
        for op in (0, 2):
            for content in (b"", b"x", b"abc", b"A" * 64, bytes(range(64))):
                collection.append(Case(op, content or b"\x00", content,
                                       keeps=[1] * len(content) if content else [0]))
        for data, keeps, error in ((b"ab", [0, 1], 6), (b"ab", [1, 0], 6),
                                   (b"a" * 65, [1] * 65, 5),
                                   (b"a" * 66, [1] * 66, 5)):
            collection.append(Case(0, data, b"", error, keeps))
        collection.append(Case(0, b"recovered", b"recovered"))
    for content in (b"", b"x", b"abc", bytes(range(64))):
        collection.append(Case(1, oracle.literals(content), content))
    overlap = oracle.periodic_block(b"abc" * 100, 3)
    collection.append(Case(1, overlap, b"abc" * 100))
    for data in (b"\x10", b"\xf0\xff", b"\x10A\x00", b"\x10A\x00\x00\x00",
                 b"\x00\x01\x00\x00", b"\x12ab"):
        try:
            oracle.decode(data)
        except oracle.LZ4Error as error:
            collection.append(Case(1, data, error.output, error.code))
        else:
            raise AssertionError("malformed fixture is not malformed")
    collection.append(Case(1, oracle.literals(b"recovered"), b"recovered"))
    if full:
        head = bytes((i * 43 + 19) & 255 for i in range(65535))
        block = oracle.sequence(head, 65535, 1024) + oracle.literals(b"tail!")
        collection.append(Case(1, block, oracle.decode(block)))
        block = oracle.periodic_block(b"Z" * 70000)
        collection.append(Case(1, block, b"Z" * 70000))
        # 15 + (2^24+2^16+2^8+1)*255 overflows an unsigned 32-bit length.
        collection.append(Case(1, b"", b"", 4, overflow=True))
    return collection


def execute(run, simulator="icarus", full=False, l1=False, reference=False):
    label = f"parent-{'l1' if l1 else 'l2'}-{simulator}-{'reference' if reference else 'rtl'}"
    directory = run.path / label
    directory.mkdir()
    tb = directory / "tb.sv"
    tb.write_text(TB.replace("@INSTANCE@", L1_INSTANCE if l1 else L2_INSTANCE)
                  .replace("@CYCLE_LIMIT@", "100000000" if full else "450000")
                  .replace("@SMOKE_BOUND@", 'if(cycle>500000) $fatal(1,"PARENT_SMOKE_LIMIT");'
                           if simulator == "icarus" else ""))
    selected = cases(full, l1)
    case_path, result_path = directory / "cases.txt", directory / "results.txt"
    lines = [str(len(selected))]
    for case in selected:
        length = 16843011 if case.overflow else len(case.source)
        lines.append(f"{case.operation} {length} {case.error} {int(case.overflow)}")
        if not case.overflow:
            lines.extend(f"{b:02x} {keep}" for b, keep in
                         zip(case.source, case.keeps or [1] * len(case.source), strict=True))
    case_path.write_text("\n".join(lines) + "\n")
    write_json(directory / "expected.json", [
        {"operation": c.operation, "source_hex": c.source.hex(), "content_hex": c.content.hex(),
         "error": c.error, "overflow": c.overflow, "keeps": c.keeps} for c in selected])
    rtl_dir = "bellows_l2_reference/rtl" if reference else "rtl"
    rtl = [run.relative(p) for p in sorted((run.root / rtl_dir).glob("*.sv"))]
    assert rtl, f"missing source set {rtl_dir}"
    executable = directory / "simv"
    if simulator == "icarus":
        run.command(["iverilog", "-g2012", "-Wall", "-s", "tb", "-o",
                     run.relative(executable), run.relative(tb), *rtl], label + "-compile")
    else:
        run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                     "--top-module", "tb", "--Mdir", run.relative(directory / "compile-obj"),
                     "-o", "../simv", "-j", "2", run.relative(tb), *rtl], label + "-compile")
    argv = [run.relative(executable), "+case=" + run.relative(case_path),
            "+result=" + run.relative(result_path)]
    if simulator == "icarus":
        argv.insert(0, "vvp")
    try:
        stdout, _ = run.command(argv, label + "-run")
    finally:
        intermediate = directory / "compile-obj"
        if intermediate.exists():
            shutil.rmtree(intermediate)
    assert "PARENT_COMPLETE" in stdout, "missing parent completion"
    records = result_path.read_text().splitlines()
    assert len(records) == len(selected), "missing parent cases"
    for number, (line, case) in enumerate(zip(records, selected, strict=True)):
        fields = line.split()
        assert fields[0] == "PARENT" and int(fields[1]) == number
        assert int(fields[2 if case.operation == 0 else 3]) == case.error, (
            "parent error", number, fields, case.error)
        if case.operation == 2:
            assert int(fields[2]) == 0
        content = bytes.fromhex(fields[5]) if len(fields) == 6 else b""
        assert len(content) == int(fields[4])
        if case.operation == 0:
            assert (oracle.decode(content) == case.content if case.error == 0
                    else content == b""), ("parent compressor", number)
            if not case.content and not case.error:
                assert content == b"\x00"
            if case.content == b"A" * 64:
                assert len(content) < len(oracle.literals(case.content))
        else:
            assert content == case.content, ("parent decode", number,
                                             content[:64].hex(), case.content[:64].hex())
    write_json(directory / "compared.json", {"cases": len(records), "all_compared": True,
                                            "history_wrap": full, "offset_65535": full,
                                            "overflow_error": full})
    return records
