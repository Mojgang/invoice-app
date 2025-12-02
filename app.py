from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import os
from datetime import datetime
import uuid
import io
import pytz
from supabase import create_client, Client

# ReportLab imports
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT

import requests
from reportlab.lib.utils import ImageReader

app = Flask(__name__, static_folder='static')
CORS(app)

# Supabase setup
SUPABASE_URL = 'https://iqqczpmvqiuqrtnzusqx.supabase.co'
SUPABASE_KEY = "sb_publishable_7EhrzbtM43LQrNFCY019UQ_KKKjCino"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Helper to get setting or return default
def get_db_setting(key, default_value):
    try:
        response = supabase.table('settings').select('value').eq('key', key).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['value']
        return default_value
    except Exception as e:
        print(f"Error fetching {key}: {e}")
        return default_value

# --- API ROUTES ---

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/services', methods=['GET'])
def get_services():
    # Default empty structure if DB is empty
    defaults = {"electrician": {"name": "Electrician", "price": 85, "unit": "hour"}}
    services = get_db_setting('services', defaults)
    return jsonify(services)

@app.route('/api/services', methods=['PUT'])
def update_services():
    services = request.json
    supabase.table('settings').upsert({
        'key': 'services',
        'value': services,
        'updated_at': datetime.now().isoformat()
    }).execute()
    return jsonify({"message": "Services updated successfully"})

@app.route('/api/invoices', methods=['GET'])
def get_invoices():
    response = supabase.table('invoices').select('*').order('created_at', desc=True).execute()
    return jsonify(response.data)

@app.route('/api/invoices', methods=['POST'])
def create_invoice():
    invoice = request.json
    
    # 1. Get Company Settings for Quote Numbering
    defaults = {'quote_prefix': 'JN', 'next_quote_number': 5401}
    settings = get_db_setting('company_settings', defaults)
    
    # 2. Generate Quote Number
    quote_number = f"{settings.get('quote_prefix', 'JN')}{settings.get('next_quote_number', 5401)}"
    invoice_id = str(uuid.uuid4())
    
    # 3. Prepare Data
    aus_tz = pytz.timezone('Australia/Sydney')
    now_iso = datetime.now(aus_tz).isoformat()

    data = {
        'id': invoice_id,
        'quote_number': quote_number,
        'client_name': invoice['clientName'],
        'client_number': invoice.get('clientNumber', ''),
        'project_notes': invoice.get('projectNotes', ''),
        'items': invoice['items'],
        'total': invoice['total'],
        'created_at': now_iso
    }
    
    # 4. Insert Invoice
    supabase.table('invoices').insert(data).execute()
    
    # 5. Increment Quote Number
    settings['next_quote_number'] = settings.get('next_quote_number', 5401) + 1
    supabase.table('settings').upsert({
        'key': 'company_settings',
        'value': settings,
        'updated_at': now_iso
    }).execute()
    
    return jsonify(data), 201

@app.route('/api/invoices/<invoice_id>', methods=['DELETE'])
def delete_invoice(invoice_id):
    supabase.table('invoices').delete().eq('id', invoice_id).execute()
    return jsonify({"message": "Invoice deleted successfully"})

@app.route('/api/invoices/<invoice_id>', methods=['PUT'])
def update_invoice(invoice_id):
    invoice = request.json
    data = {
        'client_name': invoice['clientName'],
        'client_number': invoice.get('clientNumber', ''),
        'project_notes': invoice.get('projectNotes', ''),
        'items': invoice['items'],
        'total': invoice['total'],
        'updated_at': datetime.now().isoformat()
    }
    supabase.table('invoices').update(data).eq('id', invoice_id).execute()
    return jsonify({"message": "Invoice updated successfully"})

@app.route('/api/job-summary', methods=['GET'])
def get_job_summary():
    # Note: We extract the 'text' field from the JSON object
    data = get_db_setting('job_summary', {"text": "Default summary..."})
    return jsonify({"summary": data.get('text', '')})

@app.route('/api/job-summary', methods=['PUT'])
def update_job_summary():
    summary_text = request.json.get('summary', '')
    supabase.table('settings').upsert({
        'key': 'job_summary',
        'value': {"text": summary_text}, # Store as JSON
        'updated_at': datetime.now().isoformat()
    }).execute()
    return jsonify({"message": "Job summary updated successfully"})

@app.route('/api/company-settings', methods=['GET'])
def get_company_settings():
    settings = get_db_setting('company_settings', {})
    return jsonify(settings)

@app.route('/api/company-settings', methods=['PUT'])
def update_company_settings():
    settings = request.json
    supabase.table('settings').upsert({
        'key': 'company_settings',
        'value': settings,
        'updated_at': datetime.now().isoformat()
    }).execute()
    return jsonify({"message": "Company settings updated successfully"})

# --- PDF GENERATION ---

@app.route('/api/invoices/<invoice_id>/pdf', methods=['GET'])
def generate_pdf_route(invoice_id):
    # 1. Fetch Invoice
    inv_res = supabase.table('invoices').select('*').eq('id', invoice_id).execute()
    if not inv_res.data:
        return jsonify({"error": "Invoice not found"}), 404
    invoice = inv_res.data[0]
    
    # 2. Fetch Company Settings (for footer/header)
    settings = get_db_setting('company_settings', {})
    
    # 3. Fetch Job Summary
    summary_data = get_db_setting('job_summary', {"text": ""})
    job_summary_text = summary_data.get('text', '')
    
    # 4. Generate PDF
    buffer = generate_pdf(invoice, settings, job_summary_text)
    buffer.seek(0)
    
    filename = f"quote_{invoice.get('quote_number', 'draft')}.pdf"
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

def generate_pdf(invoice, settings, job_summary_text):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=20*mm, bottomMargin=25*mm,
                            leftMargin=15*mm, rightMargin=15*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title', parent=styles['Heading1'], fontSize=24, alignment=TA_LEFT)

    elements = []

    # ===== LOGO LOGIC (Reads from static/logo.jpg) =====
    # We construct the absolute path to ensure Render finds it
    logo_path = os.path.join(app.root_path, 'static', 'logo.jpg')
    
    if os.path.exists(logo_path):
        # Create Image object from the local file
        logo = Image(logo_path, width=80*mm, height=40*mm) # Adjust width/height as needed
        logo.hAlign = 'RIGHT'
        elements.append(logo)
        elements.append(Spacer(1, 2*mm))
    else:
        # Fallback if file is missing (debugging purpose)
        print(f"Warning: Logo not found at {logo_path}")

    # ===== Title =====
    elements.append(Paragraph("<b>QUOTE</b>", title_style))
    elements.append(Spacer(1, 5*mm))

    # ===== Info Table =====
    # Handle missing keys gracefully
    quote_num = invoice.get('quote_number', 'N/A')
    
    # Parse date safely
    try:
        date_obj = datetime.fromisoformat(invoice['created_at'].replace('Z', '+00:00'))
        date_str = date_obj.strftime('%d %B %Y')
    except:
        date_str = "Unknown Date"

    info_data = [
        [Paragraph(f"<b>Quote No:</b> {quote_num}", styles['Normal']),
         Paragraph(f"<b>QUOTE TO:</b>", styles['Normal'])],
        [Paragraph(f"<b>Quote Date:</b> {date_str}", styles['Normal']),
         Paragraph(f"<b>Client Name:</b> {invoice.get('client_name','')}", styles['Normal'])],
        [Paragraph(f"<b>ABN:</b> {settings.get('abn','')}", styles['Normal']),
         Paragraph(f"<b>Client Number:</b> {invoice.get('client_number','N/A')}", styles['Normal'])]
    ]
    
    info_table = Table(info_data, colWidths=[90*mm, 90*mm])
    info_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    elements.append(info_table)
    elements.append(Spacer(1, 5*mm))

    # ===== Job Summary (From DB) =====
    if job_summary_text:
        for line in job_summary_text.split('\n'):
            if line.strip():
                if any(x in line for x in ['Materials & Finishes', 'Scope of Work', 'Notes']):
                    elements.append(Paragraph(f"<b>{line}</b>", styles['Heading3']))
                else:
                    elements.append(Paragraph(line, styles['Normal']))
                elements.append(Spacer(1, 2*mm))
        elements.append(Spacer(1, 5*mm))

    # ===== Items Table =====
    table_data = [['NO.', 'DESCRIPTION', 'QTY', 'PRICE', 'TOTAL']]
    
    items = invoice.get('items', [])
    if isinstance(items, str): # Handle case where JSONB comes back as string (rare but possible)
        items = json.loads(items)

    for idx, item in enumerate(items, start=1):
        name = item.get('service', item.get('name', 'Unknown Item'))
        if item.get('subService'):
            name += f" - {item['subService']}"
        
        qty = float(item.get('quantity', 0))
        price = float(item.get('price', 0))
        total = float(item.get('total', 0))
        
        table_data.append([
            str(idx),
            Paragraph(name, styles['Normal']),
            f"{qty} {item.get('unit','')}",
            f"${price:.2f}",
            f"${total:.2f}"
        ])
        
        if item.get('notes'):
            note_style = ParagraphStyle('note', parent=styles['Normal'], fontSize=9, textColor=colors.grey, fontName='Helvetica-Oblique')
            table_data.append(['', Paragraph(f"<i>Note: {item['notes']}</i>", note_style), '', '', ''])

    # Totals
    subtotal = float(invoice.get('total', 0))
    gst = subtotal * 0.1
    grand_total = subtotal + gst

    table_data.append(['', '', '', Paragraph('<b>Subtotal:</b>', styles['Normal']), f"${subtotal:.2f}"])
    table_data.append(['', '', '', Paragraph('<b>GST (10%):</b>', styles['Normal']), f"${gst:.2f}"])
    table_data.append(['', '', '', Paragraph('<b>Total:</b>', styles['Normal']), f"${grand_total:.2f}"])

    table = Table(table_data, colWidths=[15*mm, 90*mm, 25*mm, 30*mm, 25*mm])
    table.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-4),0.5,colors.grey),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('BACKGROUND',(0,0),(-1,0),colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(0,0),(0,-1),'CENTER'),
        ('ALIGN',(3,0),(-1,-1),'RIGHT'),
        ('VALIGN',(0,0),(-1,-1),'TOP')
    ]))
    elements.append(table)
    elements.append(Spacer(1, 5*mm))

    # ===== Payment Info (From DB Settings) =====
    elements.append(Paragraph("<b>PAYMENT OPTIONS</b>", styles['Heading2']))
    elements.append(Spacer(1, 2*mm))
    
    payment_html = f"""
    <b>Account Name:</b> {settings.get('bank_account_name', '')}<br/>
    <b>BSB:</b> {settings.get('bank_bsb', '')}<br/>
    <b>Account Number:</b> {settings.get('bank_account', '')}<br/>
    <b>Reference:</b> {quote_num}
    """
    elements.append(Paragraph(payment_html, styles['Normal']))

    # ===== Footer Contact (From DB Settings) =====
    elements.append(Spacer(1, 30*mm))
    contact_info = f"""
    <b>CONTACT:</b><br/>
    {settings.get('company_name', '')}<br/>
    {settings.get('phone', '')}<br/>
    {settings.get('email', '')}<br/>
    {settings.get('address', '')}<br/>
    <b>{settings.get('area_manager', '')}</b>
    """
    elements.append(Paragraph(contact_info, styles['Normal']))

    doc.build(elements)
    return buffer

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)