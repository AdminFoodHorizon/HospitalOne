"""Private, server-side PDF generation for finalized structured reports."""
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether


def safe(value):
    return escape(str(value if value is not None else ""))


def generate_final_pdf(report):
    """Return private relative key. Called during authorized report completion."""
    if report.status != 'FINAL' or not report.verified_by_id or not report.verified_at:
        raise ValueError('Only completed FINAL reports may be archived.')
    item = report.item
    visit = item.order.visit
    hospital = visit.hospital
    root = Path(getattr(settings, 'HOSPITAL_PRIVATE_REPORT_ROOT',
                        Path(settings.BASE_DIR) / 'private_reports')).resolve()
    rel = Path('investigation_pdfs') / str(hospital.pk) / f'{item.pk}-{uuid4().hex}.pdf'
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='HospTitle', parent=styles['Heading1'],
                              fontSize=17, alignment=TA_CENTER, spaceAfter=8))
    styles.add(ParagraphStyle(name='HospSmall', parent=styles['Normal'],
                              fontSize=9, leading=13))
    styles.add(ParagraphStyle(name='HospSection', parent=styles['Heading3'],
                              spaceBefore=12, spaceAfter=5))
    story = [
        Paragraph(safe(hospital.name), styles['HospTitle']),
        Paragraph('FINAL INVESTIGATION REPORT', styles['Title']),
        Spacer(1, 10),
        Paragraph(f'<b>Patient:</b> {safe(visit.patient.full_name)} '
                  f'&nbsp;&nbsp; <b>Patient ID:</b> {safe(visit.patient.patient_number)}',
                  styles['HospSmall']),
        Paragraph(f'<b>Visit:</b> {safe(visit.visit_number)} '
                  f'&nbsp;&nbsp; <b>Token:</b> {safe(visit.queue_token)}',
                  styles['HospSmall']),
        Paragraph(f'<b>Investigation:</b> {safe(item.test.name)} '
                  f'({safe(item.test.code)})', styles['HospSmall']),
        Paragraph(f'<b>Completed:</b> {safe(report.verified_at.strftime("%Y-%m-%d %H:%M %Z"))} '
                  f'&nbsp;&nbsp; <b>Completed by staff ID:</b> {safe(report.verified_by.user_id)}',
                  styles['HospSmall']),
        Spacer(1, 10),
    ]
    values = list(report.values.select_related('field').order_by('field__position', 'pk'))
    if values:
        rows = [[Paragraph('<b>Parameter</b>', styles['HospSmall']),
                 Paragraph('<b>Result</b>', styles['HospSmall']),
                 Paragraph('<b>Unit</b>', styles['HospSmall']),
                 Paragraph('<b>Reference / Flag</b>', styles['HospSmall'])]]
        for v in values:
            rows.append([
                Paragraph(safe(v.field.label), styles['HospSmall']),
                Paragraph(safe(v.value), styles['HospSmall']),
                Paragraph(safe(v.field.unit), styles['HospSmall']),
                Paragraph(safe(v.field.reference_text) + (' / ' + safe(v.flag) if v.flag else ''),
                          styles['HospSmall']),
            ])
        table = Table(rows, colWidths=[51*mm, 38*mm, 25*mm, 65*mm], repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(-1,0), colors.HexColor('#e9f2f6')),
            ('GRID', (0,0),(-1,-1), .3, colors.HexColor('#d5e1e7')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),6),
            ('RIGHTPADDING',(0,0),(-1,-1),6),
            ('TOPPADDING',(0,0),(-1,-1),7),
            ('BOTTOMPADDING',(0,0),(-1,-1),7),
        ]))
        story.append(table)
    for title, value in [('Findings', report.findings),
                         ('Impression', report.impression),
                         ('Recommendations', report.recommendations)]:
        if value.strip():
            story.append(Paragraph(title, styles['HospSection']))
            for line in value.splitlines():
                story.append(Paragraph(safe(line) or '&nbsp;', styles['HospSmall']))
    story.append(Spacer(1, 16))
    story.append(Paragraph('Electronically completed at this hospital. '
                           'This document contains confidential patient information.',
                           styles['HospSmall']))
    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, rightMargin=16*mm,
                      leftMargin=16*mm, topMargin=18*mm,
                      bottomMargin=18*mm).build(story)
    try:
        with dest.open('xb') as f:
            f.write(buffer.getvalue())
        dest.chmod(0o600)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return rel.as_posix()


def render_final_pdf_bytes(report):
    """Generate an illustrated report in memory from verified structured values."""
    from decimal import Decimal, InvalidOperation
    from reportlab.graphics.shapes import Drawing, Rect, String, Circle, Line
    from reportlab.platypus import PageBreak, CondPageBreak
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if report.status != 'FINAL' or not report.verified_by_id or not report.verified_at:
        raise ValueError('Only verified FINAL reports may be rendered')
    item = report.item
    visit = item.order.visit
    hospital = visit.hospital
    teal, dark, pale = HexColor('#079CBA'), HexColor('#123A49'), HexColor('#E9F7FA')
    gray, red, green, amber = HexColor('#617684'), HexColor('#DB4A46'), HexColor('#169B70'), HexColor('#E6A329')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='HOHeading', parent=styles['Heading1'], fontSize=21, leading=25,
                              textColor=dark, spaceAfter=7, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='HOSubheading', parent=styles['Heading2'], fontSize=12, leading=17,
                              textColor=dark, spaceBefore=15, spaceAfter=8))
    styles.add(ParagraphStyle(name='HOBody', parent=styles['Normal'], fontSize=9, leading=14, textColor=dark))
    styles.add(ParagraphStyle(name='HOHint', parent=styles['Normal'], fontSize=8, leading=12, textColor=gray))
    styles.add(ParagraphStyle(name='HOCell', parent=styles['Normal'], fontSize=8.3, leading=12, textColor=dark))

    def ptxt(value, style='HOBody'):
        return Paragraph(safe(value), styles[style])

    def titlebar(text):
        return [Spacer(1, 10), Paragraph(safe(text.upper()), styles['HOSubheading']),
                Table([['']], colWidths=[177*mm], rowHeights=[2*mm], style=TableStyle([
                    ('BACKGROUND',(0,0),(-1,-1),teal)])), Spacer(1, 9)]

    def card(label, value, bg=pale):
        t=Table([[ptxt(label, 'HOHint')], [Paragraph('<b>'+safe(value)+'</b>',styles['HOBody'])]],
                colWidths=[82*mm], rowHeights=[17, 25])
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),bg),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),12),
            ('LINEBELOW',(0,1),(-1,1),.4,HexColor('#D2E9ED'))]))
        return t

    values = list(report.values.select_related('field').order_by('field__position','pk'))
    def get_num(v):
        try:
            n=Decimal(str(v.value))
            return float(n) if n.is_finite() else None
        except (InvalidOperation,ValueError,TypeError):
            return None

    def result_band(v):
        """Visual numeric bar with a per-measurement scale, NOT a diagnostic classification."""
        n=get_num(v)
        if n is None or n < 0 or n > 1000000:
            return None
        width,height=490,73
        d=Drawing(width,height)
        d.add(Rect(0,0,width,height,rx=9,ry=9,fillColor=HexColor('#F4F9FA'),strokeColor=None))
        label=str(v.field.label)[:63]
        d.add(String(13,52,label,fontName='Helvetica-Bold',fontSize=10,fillColor=dark))
        d.add(String(476,52,f'{n:g} {v.field.unit}'[:29],fontName='Helvetica-Bold',fontSize=10,
                     textAnchor='end',fillColor=dark))
        d.add(Rect(13,28,462,12,rx=6,ry=6,fillColor=HexColor('#DBE9EC'),strokeColor=None))
        # A bar must not imply a medical normal/abnormal threshold. It is a value-only visual.
        scale=max(n*1.25,1)
        d.add(Rect(13,28,max(2,462*n/scale),12,rx=6,ry=6,fillColor=teal,strokeColor=None))
        hint=(v.field.reference_text or 'Reference interval not supplied')[:92]
        d.add(String(13,10,'Reference: '+hint,fontSize=8,fillColor=gray))
        if v.flag:
            d.add(String(476,10,'Verified flag: '+str(v.flag)[:22],textAnchor='end',fontSize=8,fillColor=red))
        return d

    def bmi_visual(value):
        # Visualize an explicitly recorded BMI only. Do not derive diagnoses.
        d=Drawing(490,112)
        d.add(String(8,97,'BODY MASS INDEX — VISUAL RANGE',fontName='Helvetica-Bold',fontSize=11,fillColor=dark))
        groups=[('Underweight',0,18.5,HexColor('#20A4D0')),
                ('Healthy',18.5,25,green),('Overweight',25,30,amber),('30+',30,40,red)]
        for i,(name,lo,hi,color) in enumerate(groups):
            x=8+i*121
            d.add(Rect(x,43,115,37,rx=8,ry=8,fillColor=color,strokeColor=None))
            d.add(String(x+57,63,name,fontName='Helvetica-Bold',fontSize=9,textAnchor='middle',fillColor=colors.white))
            d.add(String(x+57,49,f'{lo:g}–{hi:g}' if i<3 else '>=30',fontSize=8,textAnchor='middle',fillColor=colors.white))
            # Small original vector human silhouettes, progressively broader by BMI band.
            cx=x+57; spread=[4,6,8,10][i]
            d.add(Circle(cx,96,4,fillColor=color,strokeColor=None))
            d.add(Rect(cx-spread/2,84,spread,8,rx=2,ry=2,fillColor=color,strokeColor=None))
            d.add(Line(cx-spread/3,84,cx-spread/3-2,81,strokeColor=color,strokeWidth=2))
            d.add(Line(cx+spread/3,84,cx+spread/3+2,81,strokeColor=color,strokeWidth=2))
        d.add(String(8,17,f'Recorded BMI: {value:g} kg/m2',fontName='Helvetica-Bold',fontSize=11,fillColor=dark))
        return d

    story=[Paragraph(safe(hospital.name),styles['HOHeading']),
           Paragraph('MEDICAL INVESTIGATION REPORT',styles['HOSubheading']),
           Paragraph('PRIVATE & CONFIDENTIAL  •  FINAL VERIFIED REPORT',styles['HOHint']),
           Spacer(1,14)]
    story.extend(titlebar('Patient and investigation details'))
    detail_rows=[
        [card('PATIENT',visit.patient.full_name),card('PATIENT NUMBER',visit.patient.patient_number)],
        [card('VISIT',visit.visit_number),card('QUEUE TOKEN',visit.queue_token)],
        [card('DEPARTMENT',item.test.department.name),card('TEST',item.test.name)],
    ]
    info=Table(detail_rows,colWidths=[89*mm,89*mm],hAlign='LEFT')
    info.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story.append(info)
    story.append(Spacer(1,8))
    story.append(Paragraph('<b>Verified:</b> '+safe(report.verified_at.strftime('%d %b %Y, %H:%M %Z'))+
             ' &nbsp;&nbsp; <b>Report revision:</b> '+safe(report.revision),styles['HOBody']))
    story.extend(titlebar('Verified results'))
    if values:
        rows=[[Paragraph('<b>TEST / PARAMETER</b>',styles['HOCell']),Paragraph('<b>RESULT</b>',styles['HOCell']),
               Paragraph('<b>UNIT</b>',styles['HOCell']),Paragraph('<b>REFERENCE / VERIFIED FLAG</b>',styles['HOCell'])]]
        for v in values:
            flag=(' | '+str(v.flag)) if v.flag else ''
            rows.append([ptxt(v.field.label,'HOCell'),ptxt(v.value,'HOCell'),ptxt(v.field.unit,'HOCell'),
                         ptxt((v.field.reference_text or '—')+flag,'HOCell')])
        t=Table(rows,colWidths=[51*mm,37*mm,25*mm,65*mm],repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),dark),('TEXTCOLOR',(0,0),(-1,0),colors.white),
           ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,HexColor('#F0F8FA')]),
           ('LINEBELOW',(0,0),(-1,-1),.4,HexColor('#D6E5E9')),
           ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),
           ('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),9),
           ('BOTTOMPADDING',(0,0),(-1,-1),9)]))
        story.append(t)
        numeric=[v for v in values if get_num(v) is not None and 0 <= get_num(v) <= 1000000]
        if numeric:
            story.extend(titlebar('Results at a glance'))
            story.append(Paragraph('Each bar has its own visual scale. It does not indicate whether a result is normal or abnormal. Clinical interpretation requires the verified reference interval.',styles['HOHint']))
            story.append(Spacer(1,9))
            for v in numeric[:24]:
                story.append(KeepTogether([result_band(v),Spacer(1,7)]))
        bmi=next((v for v in values if v.field.key.lower() in ('bmi','body_mass_index') and get_num(v) is not None),None)
        if bmi:
            story.extend(titlebar('Body mass index'))
            story.append(bmi_visual(get_num(bmi)))
            story.append(Paragraph('BMI bands are illustrative adult categories only. The treating clinician must interpret the result for the individual patient.',styles['HOHint']))
    for heading,content in [('Clinical findings',report.findings),('Impression',report.impression),('Recommendations',report.recommendations)]:
        if content and content.strip():
            story.extend(titlebar(heading))
            for line in content.splitlines():
                story.append(Paragraph(safe(line) or '&nbsp;',styles['HOBody']))
    story.append(Spacer(1,18))
    story.append(Paragraph('This report was electronically verified by authorized hospital staff. Clinical interpretations are those recorded by authorized staff. The PDF is generated on demand and is not permanently stored by this operation.',styles['HOHint']))
    def decorate(canvas,doc):
        canvas.saveState()
        w,h=A4
        canvas.setFillColor(teal);canvas.rect(0,h-9*mm,w,9*mm,fill=1,stroke=0)
        canvas.setStrokeColor(HexColor('#D9E8EC'));canvas.line(16*mm,17*mm,w-16*mm,17*mm)
        canvas.setFont('Helvetica',8);canvas.setFillColor(gray)
        canvas.drawString(16*mm,12*mm,str(hospital.name)[:65] + '  •  CONFIDENTIAL MEDICAL RECORD')
        canvas.drawRightString(w-16*mm,12*mm,f'Page {doc.page}')
        canvas.restoreState()
    buffer=BytesIO()
    SimpleDocTemplate(buffer,pagesize=A4,leftMargin=16*mm,rightMargin=16*mm,
                      topMargin=18*mm,bottomMargin=22*mm).build(story,onFirstPage=decorate,onLaterPages=decorate)
    return buffer.getvalue()
