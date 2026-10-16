"""Retrieve the nine previously title-only official notices, once each."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
import requests
import pandas as pd
import fitz

ROOT=Path('D:/QuantResearchEvidence/alphaforge_000998_crosscheck_20261016_r1')
OUT=ROOT/'official_remaining9'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUT.exists():raise RuntimeError('Existing collection: preserve evidence and inspect before resuming')
    OUT.mkdir();(OUT/'pdf').mkdir();(OUT/'text').mkdir();(OUT/'pages').mkdir()
    index=ROOT/'official_actions/window_official_index_review.csv'
    fingerprint=sha(index)
    selected=pd.read_csv(index,dtype=str,keep_default_na=False)
    selected=selected.loc[selected.classification_basis.eq('title_only')]
    assert len(selected)==9
    records=[]
    for row in selected.itertuples(index=False):
        item=dict(announcement_id=row.announcement_id,title=row.title,url=row.url,
            current_index_day=row.announcement_day_as_current_index,
            requested_at=datetime.now(timezone.utc).isoformat())
        try:
            response=requests.get(row.url,timeout=35)
            path=OUT/'pdf'/f'{row.announcement_id}.pdf';path.write_bytes(response.content)
            item.update(status=response.status_code,bytes=len(response.content),sha256=sha(path),headers=dict(response.headers))
            assert response.ok and response.content.startswith(b'%PDF') and len(response.content)<16*1024*1024
            with fitz.open(path) as document:
                item['pages']=len(document);texts=[]
                for i,page in enumerate(document):
                    text=page.get_text();texts.append(f'--- PAGE {i+1} ---\n{text}')
                    page.get_pixmap(matrix=fitz.Matrix(1.15,1.15)).save(OUT/'pages'/f'{row.announcement_id}_p{i+1:02}.png')
                item['text_characters_by_page']=[len(p.get_text().strip()) for p in document]
                (OUT/'text'/f'{row.announcement_id}.txt').write_text('\n'.join(texts),encoding='utf-8')
            item['state']='downloaded_text_extracted_pages_rendered'
            print(row.announcement_id,item['pages'],row.title,flush=True)
        except Exception as error:
            item.update(state='failed',error=type(error).__name__+': '+str(error))
        records.append(item)
        (OUT/'collection.json').write_text(json.dumps(dict(records=records,index_sha256=fingerprint),ensure_ascii=False,indent=2),encoding='utf-8')
    assert sha(index)==fingerprint


if __name__=='__main__':main()
