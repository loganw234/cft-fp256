#!/usr/bin/env python3
"""ZIP one selected result directory, excluding caches and the ZIP itself."""
import argparse
from pathlib import Path
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("directory");p.add_argument("--out")
    a=p.parse_args();root=Path(a.directory).resolve()
    if not root.is_dir():p.error("result directory does not exist")
    output=Path(a.out).resolve() if a.out else root.parent/(root.name+".zip")
    if output.exists():p.error("output already exists; choose another filename")
    files=[f for f in sorted(root.rglob("*")) if f.is_file() and not f.is_symlink()
           and f!=output and "__pycache__" not in f.parts and f.suffix!=".pyc"]
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in files:z.write(f,root.name+"/"+f.relative_to(root).as_posix())
    print(output,output.stat().st_size,"bytes",len(files),"files")


if __name__=="__main__":main()
