from pathlib import Path
import re

def qident(name): return '"' + str(name).replace('"','""') + '"'
def snake(name):
    s=re.sub(r'[^0-9A-Za-z]+','_',str(name)).strip('_').lower()
    return re.sub('_+','_',s)
def find_file(raw_dir, stems):
    files=list(Path(raw_dir).glob('*'))
    for stem in stems:
        for f in files:
            if f.stem.lower()==stem.lower(): return f
    return None
