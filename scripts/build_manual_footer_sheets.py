"""Read-only footer contact sheets; OCR candidates are never accepted as evidence."""
from pathlib import Path
import json
import re
import fitz
from PIL import Image, ImageDraw
import announcement_financial_audit as audit

OLD=Path('output/publication_scan_evidence_20261011_r1')
PREV=Path('output/publication_scan_locations_20261012_r2')
OUT=Path('output/publication_manual_footers_20261012_r1')


def main():
    (OUT/'sheets').mkdir(exist_ok=True)
    items=[];unknown=[]
    for p in sorted((PREV/'results').glob('*.json')):
        r=json.loads(p.read_text(encoding='utf-8'))
        if r['offset_evidence']['offset'] is not None:continue
        candidates=[]
        with fitz.open(r['pdf']) as pdf:
            assert audit.sha(Path(r['pdf']))==r['pdf_sha256']
            for f in sorted((OLD/'pages').glob(p.stem+'_p*.json')):
                v=json.loads(f.read_text(encoding='utf-8'))
                if v['page']<=2:continue
                h=pdf[v['page']-1].rect.height*2.5
                nums=[]
                for row in v.get('rows',[]):
                    if row['center_y']<h*.85:continue
                    for c in row['cells']:
                        m=re.fullmatch(r'(?:第\s*)?(\d{1,3})(?:\s*页\s*(?:[，,]?\s*共\s*\d{1,3}\s*页)?)?',c['text'].strip())
                        if m:nums.append(dict(pdf_page=v['page'],raw_printed=int(m[1]),confidence=c['confidence'],relative_y=row['center_y']/h))
                if len(nums)==1:candidates.extend(nums)
            candidates.sort(key=lambda c:c['pdf_page'])
            if len(candidates)<2:
                unknown.append(dict(stem=p.stem,reason='less_than_two_footer_candidates',candidates=candidates));continue
            items.append(dict(stem=p.stem,pdf=r['pdf'],pdf_sha256=r['pdf_sha256'],printed_targets=r['printed_targets'],chosen=[candidates[0],candidates[-1]],all_candidates=candidates))
    for start in range(0,len(items),6):
        batch=items[start:start+6]
        canvas=Image.new('RGB',(1240,len(batch)*270),'white');draw=ImageDraw.Draw(canvas)
        for j,item in enumerate(batch):
            draw.text((12,j*270+8),item['stem'],fill='black')
            with fitz.open(item['pdf']) as pdf:
                for k,c in enumerate(item['chosen']):
                    page=pdf[c['pdf_page']-1];rect=page.rect
                    pix=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=fitz.Rect(rect.x0,rect.y0+rect.height*.83,rect.x1,rect.y1),alpha=False)
                    im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                    im.thumbnail((600,215));canvas.paste(im,(12+k*620,j*270+46))
                    draw.text((12+k*620,j*270+28),'PDF page '+str(c['pdf_page']),fill='black')
            item['sheet']='sheets/footer_'+str(start//6+1)+'.png'
        canvas.save(OUT/'sheets'/('footer_'+str(start//6+1)+'.png'))
    audit.write_json(OUT/'footer_candidates.json',items)
    audit.write_json(OUT/'insufficient_footer_candidates.json',unknown)
    audit.write_json(OUT/'frozen_inputs.json',dict(old_manifest_sha256=audit.sha(OLD/'artifact_sha256.json'),previous_manifest_sha256=audit.sha(PREV/'artifact_sha256.json')))
    print(len(items),'two-page contact cases;',len(unknown),'insufficient cases')


if __name__=='__main__':main()
