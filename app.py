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

import sys

# Supabase setup
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
if not SUPABASE_URL:
    print("❌ CRITICAL ERROR: SUPABASE_URL is missing.")
    # We exit here because the app cannot function without DB
    # But now we know exactly why it failed in the logs
    sys.exit(1)

if not SUPABASE_KEY:
    print("❌ CRITICAL ERROR: SUPABASE_KEY is missing.")
    sys.exit(1)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"❌ CRITICAL ERROR: Could not connect to Supabase. Check your URL/KEY format. Error: {e}")
    sys.exit(1)

# Add this check to debug WHY it fails
if not SUPABASE_URL:
    print("CRITICAL ERROR: SUPABASE_URL is missing from environment variables.")
if not SUPABASE_KEY:
    print("CRITICAL ERROR: SUPABASE_KEY is missing from environment variables.")

# Only try to connect if keys exist
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    # This prevents the app from crashing immediately, but API calls will fail
    # It allows the server to start so you can read the logs
    print("Warning: Supabase client not initialized due to missing keys.")
    supabase = None
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

from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

def generate_pdf(invoice, settings, job_summary_text):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)

    styles = getSampleStyleSheet()
    
    # --- HEADER STYLES ---
    header_title = ParagraphStyle('HeaderTitle', parent=styles['Heading1'], fontSize=24, spaceAfter=8, textColor=colors.black)
    header_text = ParagraphStyle('HeaderText', parent=styles['Normal'], fontSize=10, leading=14)
    total_label_style = ParagraphStyle('TotalLabel', parent=styles['Normal'], alignment=TA_RIGHT)
    
    # --- JOB SUMMARY STYLES (NEW) ---
    # Style for "JOB SUMMARY:" and "# Title"
    summary_main = ParagraphStyle('SummaryMain', parent=styles['Normal'], fontSize=11, leading=15, fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4)
    
    # Style for "## Subtitle" (Just bold, same size as text)
    summary_sub = ParagraphStyle('SummarySub', parent=styles['Normal'], fontSize=10, leading=14, fontName='Helvetica-Bold', spaceBefore=3)
    
    # Style for "* Bullet"
    summary_bullet = ParagraphStyle('SummaryBullet', parent=styles['Normal'], fontSize=10, leading=14, leftIndent=12)

    elements = []

    # ================= HEADER SECTION =================
    quote_num = invoice.get('quote_number', 'N/A')
    try:
        date_obj = datetime.fromisoformat(invoice['created_at'].replace('Z', '+00:00'))
        date_str = date_obj.strftime('%d %B %Y')
    except:
        date_str = datetime.now().strftime('%d %B %Y')

    left_column = [
        Paragraph("<b>QUOTE</b>", header_title),
        Paragraph(f"<b>Quote No:</b> {quote_num}", header_text),
        Paragraph(f"<b>Quote Date:</b> {date_str}", header_text),
        Paragraph(f"<b>ABN:</b> {settings.get('abn', '')}", header_text),
        Spacer(1, 5*mm),
        Paragraph("<b>QUOTE TO:</b>", header_text),
        Paragraph(f"<b>Client Name:</b> {invoice.get('client_name', '')}", header_text),
        Paragraph(f"<b>Client Number:</b> {invoice.get('client_number', '')}", header_text),
    ]

    right_column = []
    logo_path = os.path.join(app.root_path, 'static', 'logo.jpg')
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=70*mm, height=40*mm)
        logo.hAlign = 'RIGHT'
        right_column.append(logo)
    else:
        right_column.append(Paragraph("<b>LOGO</b>", header_title))

    header_data = [[left_column, right_column]]
    header_table = Table(header_data, colWidths=[100*mm, 80*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (0,0), 'LEFT'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 5*mm))

    # ================= JOB SUMMARY (Logic Updated) =================
    if job_summary_text:
        # Main Title
        elements.append(Paragraph("JOB SUMMARY:", summary_main))

        for line in job_summary_text.split('\n'):
            line = line.strip()
            if not line:
                continue 

            # CHECK 1: Starts with ## (Just Bold)
            if line.startswith('##'):
                clean_text = line[2:].strip() # Remove first 2 chars
                elements.append(Paragraph(clean_text, summary_sub))
            
            # CHECK 2: Starts with # (Main Header Style)
            elif line.startswith('#'):
                clean_text = line[1:].strip() # Remove first 1 char
                elements.append(Paragraph(clean_text, summary_main))
                
            # CHECK 3: Bullets
            elif line.startswith('*') or line.startswith('-'):
                clean_text = line.lstrip('*-').strip()
                elements.append(Paragraph(f"• {clean_text}", summary_bullet))
                
            # CHECK 4: Normal Text
            else:
                elements.append(Paragraph(line, header_text))
        
        elements.append(Spacer(1, 5*mm))

    # ================= ITEMS TABLE =================
    table_data = [['NO.', 'DESCRIPTION', 'QTY']]
    
    items = invoice.get('items', [])
    if isinstance(items, str):
        items = json.loads(items)

    for idx, item in enumerate(items, start=1):
        name = item.get('service', item.get('name', 'Unknown Item'))
        if item.get('subService'):
            name += f" - {item['subService']}"
        
        qty = float(item.get('quantity', 0))
        
        table_data.append([
            str(idx),
            Paragraph(name, header_text),
            f"{qty} {item.get('unit','')}"
        ])
        
        if item.get('notes'):
            note_style = ParagraphStyle('note', parent=styles['Normal'], fontSize=9, textColor=colors.grey, fontName='Helvetica-Oblique')
            table_data.append(['', Paragraph(f"<i>Note: {item['notes']}</i>", note_style), '' ])

    # ================= TOTALS =================
    subtotal = float(invoice.get('total', 0))
    gst = subtotal * 0.1
    grand_total = subtotal + gst

    table_data.append(['', Paragraph('<b>Subtotal:</b>', total_label_style), f"${subtotal:.2f}"])
    table_data.append(['', Paragraph('<b>GST (10%):</b>', total_label_style), f"${gst:.2f}"])
    table_data.append(['', Paragraph('<b>Total:</b>', total_label_style), f"${grand_total:.2f}"])

    table = Table(table_data, colWidths=[15*mm, 135*mm, 30*mm])
    table.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-4),0.5,colors.grey),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('BACKGROUND',(0,0),(-1,0),colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(0,0),(0,-1),'CENTER'),
        ('ALIGN',(2,0),(-1,-1),'CENTER'),
        ('ALIGN',(2,-3),(-1,-1),'RIGHT'),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LINEBELOW', (0,-4), (-1,-4), 1, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 10*mm))

    # ================= PAYMENT & FOOTER =================
    elements.append(Paragraph("<b>PAYMENT OPTIONS</b>", styles['Heading2']))
    elements.append(Spacer(1, 2*mm))
    
    payment_html = f"""
    <b>Account Name:</b> {settings.get('bank_account_name', '')}<br/>
    <b>BSB:</b> {settings.get('bank_bsb', '')}<br/>
    <b>Account Number:</b> {settings.get('bank_account', '')}<br/>
    <b>Reference:</b> {quote_num}
    """
    elements.append(Paragraph(payment_html, header_text))

    elements.append(Spacer(1, 20*mm))
    contact_info = f"""
    <b>CONTACT:</b><br/>
    {settings.get('company_name', '')}<br/>
    {settings.get('phone', '')}<br/>
    {settings.get('email', '')}<br/>
    {settings.get('address', '')}<br/>
    <b>{settings.get('area_manager', '')}</b>
    """
    elements.append(Paragraph(contact_info, header_text))

    doc.build(elements)
    return buffer

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)