"""Integrate the independently audited Part III; preserve supplied originals."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'report'/'report.tex'
text=p.read_text(encoding='utf-8')
start=text.find(r'\section{AI interaction: verified evidence and pending records}')
if start>=0:
    end=text.index(r'\section{Reproduction and submission status}',start)
    text=text[:start]+r'\input{part_iii_verified.tex}'+'\n\n'+text[end:]
old='The student reports having genuine AI interaction records, but those records have not yet been supplied in this chat. Part III therefore contains verified mathematical evidence and debugging results, while the required cross-model classifications, full interaction sequences, student pre-feedback attempts and personal reflections remain pending.'
new='Supplied Part III records were integrated and independently audited on October 11. Numeric scripts reproduce their outputs, but the exact I1(b) prompt differs from the handout, some I2 exchanges omit verbatim material, and the accompanying README calls I3 attempts examples. Part III identifies these remaining evidence requirements and corrects observed mathematical and code defects.'
text=text.replace(old,new).replace('Prepared on October 10, 2026','Updated on October 11, 2026')
text=text.replace('Until genuine logs and the student\'s contributions are integrated, it is a working package rather than a fully compliant submission.','The supplied records are now included with an independent audit. Remaining transcript and student-contribution requirements are listed in Part III; the package remains a reviewed working version until those items are fulfilled.')
text=text.replace('python -m pytest code/test_student_tasks.py code/test_extended.py -v','python -m pytest code/test_student_tasks.py code/test_extended.py\n  code/test_part_iii_regressions.py -v')
# Keep the command on one line for copyability.
text=text.replace('code/test_extended.py\n  code/test_part_iii_regressions.py','code/test_extended.py code/test_part_iii_regressions.py')
# A long shell line can exceed the PDF text width; README has the full explicit command.
text=text.replace('python -m pytest code/test_student_tasks.py code/test_extended.py code/test_part_iii_regressions.py -v','python -m pytest code/ -v')
text=text.replace('python code/build_report_tables.py','python code/verify_part_iii.py\npython code/build_report_tables.py')
p.write_text(text,encoding='utf-8')
print('Integrated independently audited Part III into report source.')
