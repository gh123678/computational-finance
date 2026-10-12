"""Render a fixed existing-PDF followup list; rendered pages do not approve fields."""
from pathlib import Path
import json
import fitz
import announcement_financial_audit as audit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/unanchored_conflict_pages_20261012_r1'
BASE=ROOT/'output/announcement_financial_audit_20261007'
CASES=[
 ('000687.SZ','20170411','20161231','000687.SZ_20170411_1203273828.pdf',[6,7]),
 ('000698.SZ','20190321','20181231','000698.SZ_20190321_1205922074.pdf',[6]),
 ('000698.SZ','20200410','20191231','000698.SZ_20200410_1207475125.pdf',[6]),
 ('000759.SZ','20170330','20161231','000759.SZ_20180328_1204523920.pdf',[6]),
 ('000759.SZ','20180328','20171231','000759.SZ_20180328_1204523920.pdf',[6]),
 ('000851.SZ','20200428','20191231','000851.SZ_20200428_1207642198.pdf',[9]),
 ('000903.SZ','20201015','20200930','000903.SZ_20201015_1208561669.pdf',[3]),
 ('002360.SZ','20160329','20151231','002360.SZ_20160329_1202089047.pdf',[9,10,103]),
 ('002822.SZ','20200428','20191231','002822.SZ_20200428_1207643426.pdf',[7]),
 ('600105.SH','20180403','20171231','600105.SH_20180403_1204575391.pdf',[94,95]),
 ('603696.SH','20190403','20181231','603696.SH_20190403_1205988667.pdf',[5,6]),
]


def main():
    if OUT.exists():raise RuntimeError('Snapshot exists; do not overwrite')
    (OUT/'images').mkdir(parents=True)
    queue=ROOT/'output/financial_content_scope_link_20261012_r1/unanchored_conflict_followup_queue.json'
    actual={(r['ts_code'],r['ann_date'],r['end_date']) for r in json.loads(queue.read_text())}
    assert actual=={tuple(c[:3]) for c in CASES}
    records=[]
    for code,ann,period,name,pages in CASES:
        candidates=list(BASE.rglob(name))
        hashes={audit.sha(p) for p in candidates}
        assert len(hashes)==1, name
        pdf_path=sorted(candidates)[0]
        images=[]
        with fitz.open(pdf_path) as pdf:
            for n in pages:
                image=OUT/'images'/f'{code}_{period}_p{n}.png'
                pdf[n-1].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(image)
                images.append(dict(page=n,path=str(image.relative_to(OUT)),sha256=audit.sha(image)))
        records.append(dict(ts_code=code,key_ann_date=ann,end_date=period,
            pdf=str(pdf_path.relative_to(ROOT)),pdf_sha256=hashes.pop(),images=images,
            historical_original_pdf_confirmed=False,visual_review_pending=True,
            limitation='000759 comparative/cancelled report retained; no inference of earlier publication or cancellation effect',
            selected_financial_value=None,verified_publication_day=None,usable_in_verified_history=False))
    audit.write_json(OUT/'candidates.json',records)
    audit.write_json(OUT/'protocol.json',dict(queue_sha256=audit.sha(queue),source_sha256=audit.sha(Path(__file__)),
        fixed_cases=11,render_zoom=2,historical_approvals=0,old_experiments=audit.verify_old()))
    print('Rendered 11 fixed cases; no field or historical approval')


if __name__=='__main__':main()
