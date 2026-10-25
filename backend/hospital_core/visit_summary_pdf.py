"""HospitalOne — illustrated, hospital-scoped patient visit summary.

Drop in as backend/hospital_core/visit_summary_pdf.py.
Public API remains render_visit_summary_pdf(data) -> PDF bytes.
Only caller-supplied records and hospital/visit-scoped released test results are used.
"""
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
    Flowable, PageBreak,
)

NAVY = colors.HexColor("#10364B")
TEAL = colors.HexColor("#087F8C")
CYAN = colors.HexColor("#DDF5F7")
INK = colors.HexColor("#253A47")
MUTED = colors.HexColor("#657D8B")
LINE = colors.HexColor("#DDE8EC")
PALE = colors.HexColor("#F3F8FA")
WHITE = colors.white
AMBER = colors.HexColor("#F4AE35")
RED = colors.HexColor("#D95757")
GREEN = colors.HexColor("#2C9A75")


def _value(v, fallback="Not recorded"):
    if v is None or v == "":
        return fallback
    if isinstance(v, (list, tuple)):
        return ", ".join(map(str, v)) if v else fallback
    if isinstance(v, dict):
        return ", ".join(f"{k}: {val}" for k, val in v.items()) or fallback
    return str(v)


def _safe(v, fallback="Not recorded"):
    return escape(_value(v, fallback))


class MedicalIcon(Flowable):
    """Vector-drawn clinical pictograms; no external fonts or image files."""
    def __init__(self, kind, size=26, color=TEAL):
        super().__init__()
        self.kind, self.width, self.height, self.color = kind, size, size, color

    def draw(self):
        c = self.canv
        c.saveState()
        c.setStrokeColor(self.color)
        c.setFillColor(self.color)
        c.setLineWidth(1.9)
        c.setLineCap(1)
        c.setLineJoin(1)
        s = self.width / 30.0
        c.scale(s, s)
        k = self.kind
        if k == "doctor":  # stethoscope
            c.arc(5, 11, 19, 27, 180, 180)
            c.line(5, 19, 5, 12); c.line(19, 19, 19, 12)
            c.circle(5, 21, 2, fill=1, stroke=0)
            c.circle(19, 21, 2, fill=1, stroke=0)
            c.bezier(12, 11, 12, 1, 25, 3, 25, 11)
            c.circle(25, 14, 3, fill=0, stroke=1)
        elif k == "heart":
            p = c.beginPath(); p.moveTo(15, 4)
            p.curveTo(0, 14, 2, 25, 10, 25)
            p.curveTo(13, 25, 15, 23, 15, 21)
            p.curveTo(18, 27, 27, 27, 28, 19)
            p.curveTo(29, 13, 22, 8, 15, 4)
            c.drawPath(p, stroke=1, fill=0)
            c.line(5, 16, 10, 16); c.line(10, 16, 12, 20)
            c.line(12, 20, 16, 12); c.line(16, 12, 18, 16); c.line(18, 16, 25, 16)
        elif k == "lab":
            c.line(11, 26, 19, 26); c.line(13, 26, 13, 17)
            c.line(17, 26, 17, 17)
            p=c.beginPath(); p.moveTo(13,17);p.lineTo(5,6)
            p.curveTo(3,3,7,2,10,2);p.lineTo(20,2)
            p.curveTo(24,2,27,4,25,7);p.lineTo(17,17)
            c.drawPath(p)
            c.line(9, 10, 21, 10); c.circle(14, 6, 1.3, fill=1, stroke=0)
        elif k == "pill":
            c.translate(15, 15); c.rotate(40)
            c.roundRect(-12, -6, 24, 12, 6, stroke=1, fill=0)
            c.line(0, -6, 0, 6)
        elif k == "user":
            c.circle(15, 21, 6, fill=0, stroke=1)
            c.arc(4, 1, 26, 19, 0, 180)
        elif k == "calendar":
            c.roundRect(4, 4, 22, 21, 3, stroke=1, fill=0)
            c.line(4, 18, 26, 18); c.line(10, 27, 10, 22); c.line(20, 27, 20, 22)
            for x in (10, 16, 22):
                c.circle(x, 12, 1, fill=1, stroke=0)
        elif k == "clock":
            c.circle(15, 15, 11, fill=0, stroke=1)
            c.line(15, 15, 15, 22); c.line(15, 15, 20, 12)
        elif k == "receipt":
            p=c.beginPath();p.moveTo(7,3);p.lineTo(7,27);p.lineTo(23,27)
            p.lineTo(23,3);p.lineTo(19,6);p.lineTo(15,3);p.lineTo(11,6);p.close()
            c.drawPath(p)
            for y in (20,15,10):c.line(11,y,19,y)
        else:  # medical cross
            c.roundRect(11, 3, 8, 24, 1, stroke=0, fill=1)
            c.roundRect(3, 11, 24, 8, 1, stroke=0, fill=1)
        c.restoreState()


def render_visit_summary_pdf(data):
    """Create a graphical, confidential visit PDF. Return bytes; no data mutation."""
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="HO_Title2", fontName="Helvetica-Bold",
        fontSize=22, leading=26, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="HO_Sub2", fontName="Helvetica",
        fontSize=9, leading=13, textColor=MUTED))
    styles.add(ParagraphStyle(name="HO_Section2", fontName="Helvetica-Bold",
        fontSize=12, leading=16, textColor=NAVY))
    styles.add(ParagraphStyle(name="HO_Body2", fontName="Helvetica",
        fontSize=9, leading=13, textColor=INK, spaceAfter=4, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="HO_Small2", parent=styles["HO_Body2"],
        fontSize=7.6, leading=11))
    styles.add(ParagraphStyle(name="HO_Label2", fontName="Helvetica-Bold",
        fontSize=7.4, leading=10, textColor=MUTED))
    styles.add(ParagraphStyle(name="HO_Value2", fontName="Helvetica-Bold",
        fontSize=10, leading=14, textColor=NAVY))
    styles.add(ParagraphStyle(name="HO_White2", fontName="Helvetica-Bold",
        fontSize=8.5, leading=12, textColor=WHITE))
    styles.add(ParagraphStyle(name="HO_Center2", parent=styles["HO_Small2"], alignment=TA_CENTER))

    def P(v, style="HO_Body2"):
        return Paragraph(_safe(v), styles[style])

    def rich(txt, style="HO_Body2"):
        return Paragraph(txt, styles[style])

    def block(label, value):
        return [P(label.upper(), "HO_Label2"), P(value, "HO_Value2")]

    def panel(contents, bg=PALE, pad=10):
        t = Table([[contents]], colWidths=[172*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), bg),
            ("BOX", (0,0), (-1,-1), 0.5, LINE),
            ("LEFTPADDING",(0,0),(-1,-1),pad),
            ("RIGHTPADDING",(0,0),(-1,-1),pad),
            ("TOPPADDING",(0,0),(-1,-1),pad),
            ("BOTTOMPADDING",(0,0),(-1,-1),pad),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
        ]))
        return t

    def heading(title, icon):
        t=Table([[MedicalIcon(icon,24), P(title,"HO_Section2")]],
                colWidths=[30, 142*mm-30])
        t.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LINEBELOW",(0,0),(-1,-1),1,LINE),
            ("LEFTPADDING",(0,0),(-1,-1),0),
            ("BOTTOMPADDING",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),7),
        ]))
        story.extend([Spacer(1,9),t,Spacer(1,8)])

    def kv_table(obj, pairs):
        rows=[]
        for label,key in pairs:
            rows.append([P(label,"HO_Label2"),P((obj or {}).get(key),"HO_Body2")])
        t=Table(rows,colWidths=[43*mm,129*mm],hAlign="LEFT")
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS",(0,0),(-1,-1),[WHITE,PALE]),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),9),
            ("RIGHTPADDING",(0,0),(-1,-1),9),
            ("TOPPADDING",(0,0),(-1,-1),7),
            ("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("LINEBELOW",(0,0),(-1,-1),0.3,LINE),
        ]))
        story.append(t)

    def cards(items, pairs, icon, empty):
        if not items:
            story.append(P(empty))
            return
        for index,item in enumerate(items,1):
            header=Table([[MedicalIcon(icon,21),P(f"Record {index}","HO_Value2")]],
                         colWidths=[27, 145*mm-27])
            header.setStyle(TableStyle([
                ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                ("LEFTPADDING",(0,0),(-1,-1),0),
                ("BOTTOMPADDING",(0,0),(-1,-1),5),
            ]))
            details=[header]
            for label,key in pairs:
                value=item.get(key)
                if value is not None and value != "":
                    details.append(rich(f"<font color='#657D8B'><b>{escape(label)}:</b></font> {_safe(value)}","HO_Body2"))
            story.extend([panel(details),Spacer(1,7)])

    hospital=data.get("hospital") or {}
    patient=data.get("patient") or {}
    visit=data.get("visit") or {}
    story=[]
    # Hospital header: neutral, unbranded visual identity; no fake logo.
    brand=Table([[MedicalIcon("cross",30),[
        P(hospital.get("name") or "Hospital","HO_Title2"),
        P("CONFIDENTIAL • PATIENT VISIT REPORT","HO_Sub2")]]],
        colWidths=[39, 172*mm-39])
    brand.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),9),
        ("LINEBELOW",(0,0),(-1,-1),2,TEAL),
    ]))
    story.extend([brand,Spacer(1,8)])
    contact="  •  ".join(str(hospital[k]) for k in ("address","phone","email") if hospital.get(k))
    if contact:
        story.append(P(contact,"HO_Small2"))
    story.append(Spacer(1,7))
    story.append(rich("COMPLETE VISIT <font color='#087F8C'>SUMMARY</font>","HO_Title2"))
    story.append(P("Clinical information available and authorized at the time of generation.","HO_Sub2"))
    story.append(Spacer(1,12))

    # Patient overview cards.
    patient_grid=Table([
        [block("Patient",patient.get("name")),block("Patient ID",patient.get("number"))],
        [block("Visit",visit.get("visit_number")),block("Registered",visit.get("registered_at"))],
        [block("Doctor",visit.get("doctor")),block("Visit status",visit.get("state"))],
    ],colWidths=[86*mm,86*mm])
    patient_grid.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),PALE),
        ("BOX",(0,0),(-1,-1),0.5,LINE),
        ("INNERGRID",(0,0),(-1,-1),0.5,LINE),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),11),
        ("RIGHTPADDING",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),9),
        ("BOTTOMPADDING",(0,0),(-1,-1),9),
    ]))
    story.append(patient_grid)
    heading("PATIENT PROFILE","user")
    kv_table(patient,[("Date of birth","date_of_birth"),("Sex","sex"),
        ("Phone","phone"),("Email","email"),("Address","address"),
        ("Allergies","allergies"),("Medical history","medical_history"),
        ("Current medications","current_medications")])
    story.append(Spacer(1,4))
    story.append(rich(f"<b>Queue token:</b> {_safe(visit.get('queue_token'))} &nbsp;&nbsp; "
                      f"<b>Completed:</b> {_safe(data.get('completed_at'),'Not finalized')}"))

    # Vitals: big number tiles rather than raw text.
    heading("NURSING ASSESSMENT & VITAL SIGNS","heart")
    nursing=data.get("nursing") or []
    if not nursing:
        story.append(P("No nursing assessments recorded."))
    for idx,n in enumerate(nursing,1):
        story.append(rich(f"<b>Assessment {idx}</b> &nbsp; {_safe(n.get('completed_at'))}","HO_Small2"))
        vitals=[
            ("BLOOD PRESSURE","blood_pressure","mmHg"),
            ("PULSE","pulse_bpm","bpm"),
            ("TEMPERATURE","temperature_c","°C"),
            ("OXYGEN SATURATION","spo2_percent","%"),
            ("RESPIRATORY RATE","respiratory_rate","/min"),
            ("PAIN SCORE","pain_score",""),
            ("HEIGHT","height_cm","cm"),
            ("WEIGHT","weight_kg","kg"),
        ]
        cells=[]
        for label,key,unit in vitals:
            value=n.get(key)
            shown=_safe(value,"—")
            if value is not None and value != "" and unit:
                shown+=f" <font size='7' color='#657D8B'>{escape(unit)}</font>"
            cells.append([rich(escape(label),"HO_Label2"),
                          rich(f"<font size='14' color='#10364B'><b>{shown}</b></font>","HO_Body2")])
        rows=[[cells[i],cells[i+1]] for i in range(0,len(cells),2)]
        t=Table(rows,colWidths=[86*mm,86*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),CYAN),
            ("INNERGRID",(0,0),(-1,-1),2,WHITE),
            ("BOX",(0,0),(-1,-1),0.5,LINE),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),10),
            ("TOPPADDING",(0,0),(-1,-1),9),
            ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ]))
        story.extend([t,Spacer(1,5)])
        if n.get("notes"):
            story.append(rich(f"<b>Nursing notes:</b> {_safe(n['notes'])}"))
        story.append(Spacer(1,8))

    heading("DOCTOR REVIEW & CLINICAL ASSESSMENT","doctor")
    cards(data.get("consultations") or [],
        [("Doctor","doctor"),("Department","department"),("Started","started_at"),
         ("Completed","ended_at"),("Diagnosis","diagnosis"),("Clinical review","notes"),
         ("Status","status")],"doctor","No doctor consultations recorded.")

    heading("LABORATORY & INVESTIGATION RESULTS","lab")
    investigations=data.get("investigations") or []
    released=[x for x in investigations if x.get("released")]
    cards(released,[("Test","test_name"),("Status","status"),
         ("Performed","performed_at"),("Findings","findings"),
         ("Impression","impression"),("Recommendations","recommendations")],
         "lab","No verified, released investigation results recorded.")

    # Structured results are queried ONLY when both hospital and visit scope IDs are present.
    hospital_id=data.get("_hospital_id")
    visit_id=data.get("_visit_id")
    if hospital_id and visit_id and released:
        from .models import InvestigationReport, TestOrderItem
        ids={r.get("item_id") for r in released if r.get("item_id") is not None}
        reports=(InvestigationReport.objects.filter(
            item_id__in=ids,
            item__order__visit_id=visit_id,
            item__order__visit__hospital_id=hospital_id,
            item__status=TestOrderItem.Status.REPORT_READY,
            status__in=[InvestigationReport.Status.FINAL,InvestigationReport.Status.AMENDED],
            verified_at__isnull=False,verified_by__isnull=False,
        ).select_related("item__test").prefetch_related("values__field"))
        for report in reports:
            values=list(report.values.all())
            if not values:
                continue
            story.append(rich(f"<b>{_safe(report.item.test.name)} — Verified parameters</b>","HO_Value2"))
            table_rows=[[P("PARAMETER","HO_Label2"),P("RESULT","HO_Label2"),
                         P("REFERENCE / FLAG","HO_Label2")]]
            for val in values:
                result=f"{_safe(val.value)} {_safe(val.field.unit,'')}"
                reference=_safe(val.field.reference_text,"Not supplied")
                if val.flag:
                    reference+=f"<font color='#B35D17'> &nbsp; | &nbsp; {_safe(val.flag)}</font>"
                table_rows.append([P(val.field.label,"HO_Body2"),
                                   rich(result,"HO_Body2"),rich(reference,"HO_Small2")])
            t=Table(table_rows,colWidths=[54*mm,40*mm,78*mm],repeatRows=1,hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,0),CYAN),
                ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,PALE]),
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("LINEBELOW",(0,0),(-1,-1),0.4,LINE),
                ("LEFTPADDING",(0,0),(-1,-1),7),
                ("TOPPADDING",(0,0),(-1,-1),7),
                ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ]))
            story.extend([Spacer(1,5),t,Spacer(1,9)])
    omitted=len(investigations)-len(released)
    if omitted:
        story.append(rich(f"<b>{omitted} unreleased investigation(s) excluded.</b>","HO_Small2"))

    heading("PRESCRIBED MEDICATIONS","pill")
    cards(data.get("prescriptions") or [],
        [("Medicine","medicine"),("Code","code"),("Dose","dose"),
         ("Route","route"),("Frequency","frequency"),("Duration","duration"),
         ("Quantity","quantity"),("Instructions","instructions")],
         "pill","No prescriptions recorded.")

    heading("PHARMACY DISPENSING & BILL","receipt")
    bill=data.get("bill")
    if bill:
        summary=Table([[block("Bill number",bill.get("bill_number")),
                        block("Total",f"{_value(bill.get('currency'),'')} {_value(bill.get('total'))}")]],
                      colWidths=[86*mm,86*mm])
        summary.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),CYAN),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),12),
            ("TOPPADDING",(0,0),(-1,-1),12),
            ("BOTTOMPADDING",(0,0),(-1,-1),10),
        ]))
        story.extend([summary,Spacer(1,6),
                      rich(f"<b>Finalized:</b> {_safe(bill.get('finalized_at'))}")])
        cards(bill.get("lines") or [],
            [("Medicine","medicine"),("Prescribed quantity","prescribed_quantity"),
             ("Dispensed quantity","quantity"),("Unit price","unit_price"),
             ("Line total","total"),("Dose","dose"),("Route","route"),
             ("Frequency","frequency"),("Duration","duration"),
             ("Instructions","instructions")],"pill","No dispensing lines recorded.")
    else:
        story.append(panel([P("Pharmacy dispensing has not been finalized.")],CYAN))

    heading("PATIENT JOURNEY TIMELINE","clock")
    timeline=data.get("timeline") or []
    if not timeline:
        story.append(P("No movement events recorded."))
    else:
        for event in timeline:
            time=_safe(event.get("at"))
            desc=f"{_safe(event.get('from'),'—')} → {_safe(event.get('to'),'—')}"
            reason=_safe(event.get("reason"),"")
            actor=_safe(event.get("actor"),"")
            story.append(panel([
                rich(f"<font color='#087F8C'><b>{time}</b></font>","HO_Small2"),
                rich(f"<b>{desc}</b>","HO_Body2"),
                rich(f"{reason} &nbsp; {actor}","HO_Small2"),
            ],WHITE,8))
            story.append(Spacer(1,5))

    story.extend([Spacer(1,13),panel([
        rich("<b>CONFIDENTIAL CLINICAL RECORD</b>","HO_Label2"),
        P("This document contains information recorded during this visit. "
          "It is not a substitute for professional medical assessment or for "
          "the separately issued, verified investigation report PDFs.","HO_Small2")
    ],PALE)])

    output=BytesIO()
    def decorate(canvas,doc):
        canvas.saveState()
        w,h=A4
        canvas.setStrokeColor(LINE)
        canvas.line(18*mm,17*mm,w-18*mm,17*mm)
        canvas.setFont("Helvetica-Bold",7)
        canvas.setFillColor(TEAL)
        canvas.drawString(18*mm,12*mm,"HOSPITALONE  •  PRIVATE & CONFIDENTIAL")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica",7)
        canvas.drawRightString(w-18*mm,12*mm,f"Page {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(
        output,pagesize=A4,leftMargin=19*mm,rightMargin=19*mm,
        topMargin=18*mm,bottomMargin=23*mm,
        title="Confidential Patient Visit Summary",
        author=_value(hospital.get("name"),"HospitalOne"),
    ).build(story,onFirstPage=decorate,onLaterPages=decorate)
    return output.getvalue()
