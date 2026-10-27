"""Optional: rebuild frozen P1 extracts with exact function-source fingerprints."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
FUNCTIONS={"research.py":["read_market"],"datasets.py":["dataset_config"],"backtest.py":["summarize"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=ROOT.parents[1]/"quant_research")
    args=parser.parse_args()
    out=ROOT/"p1_platform"
    reference=out/"reference";reference.mkdir(exist_ok=True)
    chunks=['"""Exact P1 function bodies; only imports and dataset registry are local glue."""\nimport numpy as np\nimport pandas as pd\nDATASETS = {}\n']
    entries=[]
    for filename,names in FUNCTIONS.items():
        origin=args.source/filename
        raw=origin.read_bytes();text=raw.decode("utf-8-sig")
        shutil.copyfile(origin,reference/filename)
        nodes={node.name:node for node in ast.parse(text).body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
        for name in names:
            node=nodes[name];snippet=ast.get_source_segment(text,node)
            chunks.append(snippet+"\n")
            entries.append({"source_file":f"quant_research/{filename}","reference_file":f"p1_platform/reference/{filename}",
                "source_file_sha256":hashlib.sha256(raw).hexdigest(),"function":name,
                "start_line":node.lineno,"end_line":node.end_lineno,
                "function_utf8_sha256":hashlib.sha256(snippet.encode("utf-8")).hexdigest()})
    (out/"legacy.py").write_text("\n\n".join(chunks),encoding="utf-8")
    (out/"function_provenance.json").write_text(json.dumps({"extraction":"AST exact source segment, no edits inside functions",
        "functions":entries},indent=2),encoding="utf-8")
    print("Frozen exact P1 functions:",", ".join(x["function"] for x in entries))


if __name__=="__main__":main()
