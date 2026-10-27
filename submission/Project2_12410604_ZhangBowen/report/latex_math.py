"""Real pdfLaTeX equations, embedded as vector PDF content in the report.

Cached PDFs ship with the project: unchanged report rebuilding is offline and
does not require TeX. Editing a formula requires a local pdflatex executable.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import ContentStream, DictionaryObject
from reportlab.platypus import Flowable

FORMULAS={
    "variance":("Realized variance",r"\bar f_t=\frac{1}{n_t}\sum_{d\in\mathcal D_t}f_d,\qquad RV_t=\sum_{d\in\mathcal D_t}\left(f_d-\bar f_t\right)^2"),
    "weights":("Portfolio formation",r"w_{t+1}=\frac{c}{RV_t},\qquad f^{\mathrm{VM}}_{t+1}=w_{t+1}f_{t+1}"),
    "scale":("Equal-volatility normalization",r"c=\frac{s_{\mathcal T}(f_t)}{s_{\mathcal T}\!\left(f_t/RV_{t-1}\right)},\qquad s_{\mathcal T}(x)=\sqrt{\frac{1}{T-1}\sum_{t\in\mathcal T}(x_t-\bar x)^2}"),
    "regression":("Univariate regression",r"f_t^{\mathrm{VM}}=\alpha_m+\beta f_t+\varepsilon_t"),
    "annualization":("Annual alpha and its standard error",r"\alpha_{\mathrm{ann},\%}=1200\alpha_m,\qquad \operatorname{SE}(\alpha_{\mathrm{ann},\%})=1200\operatorname{SE}(\alpha_m)"),
    "metrics":("Sharpe ratio and original-table RMSE units",r"\mathrm{SR}_{\mathrm{ann}}=\sqrt{12}\,\frac{\bar f^{\mathrm{VM}}}{s_{\mathcal T}(f^{\mathrm{VM}})},\qquad \mathrm{RMSE}_{\mathrm{paper}}=1200\sqrt{\frac{\sum_{t\in\mathcal T}\hat\varepsilon_t^2}{T-2}}"),
    "wealth":("Total-return wealth and risk",r"\begin{aligned}R_t^{\mathrm{gross}}&=r_t^f+w_tf_t,&V_t&=V_{t-1}(1+R_t),\quad V_0=1,\\ \mathrm{CAGR}&=\left(\frac{V_T}{V_0}\right)^{12/T}-1,&\mathrm{MDD}&=\max_{0\leq t\leq T}\left(1-\frac{V_t}{\max_{0\leq s\leq t}V_s}\right).\end{aligned}"),
    "cap":("Leverage cap",r"w_t^{\mathrm{cap}}=\min\!\left\{\frac{c}{RV_{t-1}},\,2\right\}"),
    "fees":("Exact proportional trading cost",r"\phi_t=k\left|w_t(1-\phi_t)-d_t\right|=\begin{cases}\displaystyle\frac{k(w_t-d_t)}{1+kw_t},&w_t\geq d_t,\\[5pt]\displaystyle\frac{k(d_t-w_t)}{1-kw_t},&w_t<d_t.\end{cases}"),
    "net_return":("Financing and net total return",r"R_t^{\mathrm{net}}=(1-\phi_t)\left[1+r_t^f+w_tf_t-\frac{\lambda}{12}\max(w_t-1,0)\right]-1,\qquad f_t^{\mathrm{net}}=R_t^{\mathrm{net}}-r_t^f"),
}


def tex_document(formula):
    return (r"\documentclass[11pt,border=2pt]{standalone}"+"\n"+
        r"\usepackage{amsmath,amssymb,xcolor}"+"\n"+
        r"\definecolor{mathblue}{HTML}{1B5878}"+"\n"+
        r"\begin{document}{\color{mathblue}$\displaystyle "+formula+r"$}\end{document}"+"\n")


def prepare_formulas(report_dir):
    report_dir=Path(report_dir);cache=report_dir/"latex_formulas";cache.mkdir(exist_ok=True)
    records={};log=[]
    for key,(title,formula) in FORMULAS.items():
        source=tex_document(formula);digest=hashlib.sha256(source.encode()).hexdigest()
        tex=cache/(key+".tex");pdf=cache/(key+".pdf")
        stamp=cache/(key+".sha256")
        if not (pdf.exists() and tex.exists() and stamp.exists() and tex.read_text(encoding="utf-8")==source and stamp.read_text().strip()==digest):
            executable=shutil.which("pdflatex")
            if not executable:raise RuntimeError("Formula changed: install pdfLaTeX or restore the matching shipped formula cache")
            tex.write_text(source,encoding="utf-8")
            command=[executable,"--disable-installer","-interaction=nonstopmode","-halt-on-error","-no-shell-escape",tex.name]
            result=subprocess.run(command,cwd=cache,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)
            log.append("FORMULA: "+key+"\n"+result.stdout+result.stderr)
            if result.returncode:raise RuntimeError("LaTeX formula failed: "+key+"\n"+result.stdout[-2500:])
            stamp.write_text(digest+"\n",encoding="ascii")
        page=PdfReader(pdf).pages[0]
        if len(PdfReader(pdf).pages)!=1:raise AssertionError("Expected one formula per PDF")
        records[key]={"title":title,"latex":formula,"tex_sha256":digest,
                      "pdf_sha256":hashlib.sha256(pdf.read_bytes()).hexdigest(),"pdf":pdf,
                      "width":float(page.mediabox.width),"height":float(page.mediabox.height)}
    manifest={key:{k:v for k,v in record.items() if k!="pdf"} for key,record in records.items()}
    (cache/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    # Human-editable, standalone LaTeX source for all equations.
    lines=[r"\documentclass[11pt]{article}",r"\usepackage{amsmath,amssymb}",
           r"\usepackage[margin=28mm]{geometry}",r"\title{Project 2: Mathematical Formulas}",
           r"\author{Zhang Bowen, 12410604}",r"\date{October 20, 2026}",r"\begin{document}",r"\maketitle"]
    for key,(title,formula) in FORMULAS.items():
        lines.extend([r"\subsection*{"+title+"}",r"\begin{equation}",formula,r"\end{equation}"])
    lines.append(r"\end{document}")
    (report_dir/"formulas.tex").write_text("\n".join(lines)+"\n",encoding="utf-8")
    (report_dir.parent/"results/latex_build_log.txt").write_text("\n\n".join(log) if log else "All 10 formula PDFs reused from verified LaTeX cache.\n",encoding="utf-8")
    return records


class LatexEquation(Flowable):
    def __init__(self,key,record,placements,number=None,width=507):
        super().__init__()
        self.key,self.record,self.placements,self.number=key,record,placements,number
        self.width=width
        self.scale=min(1.,(width-44)/record["width"])
        self.height=record["height"]*self.scale+5
        self.spaceBefore=1;self.spaceAfter=6

    def draw(self):
        x,y=self.canv.absolutePosition((self.width-self.record["width"]*self.scale)/2,2)
        self.placements.append({"page":self.canv.getPageNumber()-1,"key":self.key,"x":x,"y":y,"scale":self.scale})
        if self.number is not None:
            self.canv.setFont("Times-Roman",10)
            self.canv.drawRightString(self.width,self.height/2-3,"("+str(self.number)+")")


def merge_vector_formulas(base_pdf,destination,records,placements):
    reader=PdfReader(base_pdf);writer=PdfWriter();writer.clone_document_from_reader(reader)
    # Keep every source reader alive: pypdf 5 tracks cloned resources by reader
    # identity, so recycling reader identities can corrupt later font maps.
    source_readers={key:PdfReader(record["pdf"]) for key,record in records.items()}
    for item in placements:
        page=source_readers[item["key"]].pages[0]
        transform=Transformation().scale(item["scale"]).translate(item["x"],item["y"])
        writer.pages[item["page"]].merge_transformed_page(page,transform,expand=False)
    with Path(destination).open("wb") as stream:writer.write(stream)
    verified=PdfReader(destination);font_count=0;operator_count=0
    for page in verified.pages:
        resources=page["/Resources"].get_object()
        fonts=resources["/Font"].get_object() if "/Font" in resources else {}
        for name,font in fonts.items():
            if not isinstance(font.get_object(),DictionaryObject):raise AssertionError("Invalid font resource: "+str(name))
            font_count+=1
        for operands,operator in ContentStream(page.get_contents(),verified).operations:
            if operator==b"Tf":
                if operands[0] not in fonts:raise AssertionError("Missing formula font: "+str(operands[0]))
                operator_count+=1
    return {"status":"PASS","method":"pdfLaTeX-compiled vector PDF equations merged with pypdf",
            "report_pages":len(verified.pages),"font_resources_checked":font_count,"font_operators_checked":operator_count,
            "formula_count":len(placements),"formulas":[{"key":p["key"],"page":p["page"]+1} for p in placements]}
