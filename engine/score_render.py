"""Official CPU renderer with a separate, versioned Chinese display copy."""
import hashlib,re,sys
from pathlib import Path
from .common import ROOT,write_json

def display_abc(abc):
    labels={'Vocal Melody':'人声旋律','Ins Melody':'器乐旋律','Vocal':'人声','Inst.':'器乐'}
    lines=[]
    for line in abc.splitlines(keepends=True):
        if line.startswith('V:'):
            line=re.sub(r'(\b(?:name|snm)=)"([^"]*)"',lambda m:m[1]+'"'+labels.get(m[2],m[2])+'"',line)
        lines.append(line)
    return ''.join(lines)

def main(directory):
    sys.path.insert(0,str(ROOT/'models/SheetSage2'))
    from rendering_sheetsage2 import render_outputs
    directory=Path(directory);original=(directory/'score.abc').read_text(encoding='utf-8')
    view=directory/'render-input.abc';view.write_text(display_abc(original),encoding='utf-8')
    result=render_outputs(abc=view,output_dir=directory/'rendered',score=('svg','pdf','png'))
    write_json(directory/'render-info.json',{'displayVersion':1,'sourceSha256':hashlib.sha256(original.encode()).hexdigest(),'warnings':result.get('warnings',[])})
if __name__=='__main__':main(sys.argv[1])
