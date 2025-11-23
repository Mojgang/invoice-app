from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import json
import os
from datetime import datetime
import uuid
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
import io
import pytz
from reportlab.platypus import SimpleDocTemplate, BaseDocTemplate, PageTemplate, Frame, Table, TableStyle, Paragraph, Spacer, Image, PageBreak


app = Flask(__name__, static_folder='static')
CORS(app)

# Data storage files
DATA_DIR = 'data'
SERVICES_FILE = os.path.join(DATA_DIR, 'services.json')
INVOICES_FILE = os.path.join(DATA_DIR, 'invoices.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'company_settings.json')


# Initialize default services if file doesn't exist
def init_services():
    default_services = {
        "electrician": {
            "name": "Electrician",
            "unit": "hour",
            "price": 85.00
        },
        "plumber": {
            "name": "Plumber",
            "unit": "hour",
            "price": 90.00
        },
        "demolition": {
            "name": "Demolition",
            "unit": "hour",
            "price": 75.00
        },
        "joinery": {
            "name": "Joinery",
            "items": {
                "splashback": {
                    "name": "Splashback",
                    "unit": "meter",
                    "price": 120.00
                },
                "cabinet": {
                    "name": "Cabinet",
                    "unit": "meter",
                    "price": 350.00
                },
                "benchtop": {
                    "name": "Benchtop",
                    "unit": "meter",
                    "price": 280.00
                },
                "shelving": {
                    "name": "Shelving",
                    "unit": "meter",
                    "price": 95.00
                }
            }
        }
    }
    
    if not os.path.exists(SERVICES_FILE):
        with open(SERVICES_FILE, 'w') as f:
            json.dump(default_services, f, indent=2)
    
    if not os.path.exists(INVOICES_FILE):
        with open(INVOICES_FILE, 'w') as f:
            json.dump([], f)

init_services()

# API Routes
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/services', methods=['GET'])
def get_services():
    with open(SERVICES_FILE, 'r') as f:
        services = json.load(f)
    return jsonify(services)

@app.route('/api/services', methods=['PUT'])
def update_services():
    services = request.json
    with open(SERVICES_FILE, 'w') as f:
        json.dump(services, f, indent=2)
    return jsonify({"message": "Services updated successfully"})

@app.route('/api/invoices', methods=['GET'])
def get_invoices():
    with open(INVOICES_FILE, 'r') as f:
        invoices = json.load(f)
    return jsonify(invoices)

@app.route('/api/invoices', methods=['POST'])
def create_invoice():
    invoice = request.json
    settings = get_next_quote_number()
    
    # Generate quote number
    quote_number = f"{settings['quote_prefix']}{settings['next_quote_number']}"
    
    invoice['id'] = str(uuid.uuid4())
    invoice['quote_number'] = quote_number
    
    # Use Australian Eastern Standard Time
    aus_tz = pytz.timezone('Australia/Sydney')
    invoice['created_at'] = datetime.now(aus_tz).isoformat()
    
    # Increment quote number for next time
    increment_quote_number()
    
    with open(INVOICES_FILE, 'r') as f:
        invoices = json.load(f)
    
    invoices.append(invoice)
    
    with open(INVOICES_FILE, 'w') as f:
        json.dump(invoices, f, indent=2)
    
    return jsonify(invoice), 201

@app.route('/api/invoices/<invoice_id>', methods=['DELETE'])
def delete_invoice(invoice_id):
    with open(INVOICES_FILE, 'r') as f:
        invoices = json.load(f)
    
    invoices = [inv for inv in invoices if inv['id'] != invoice_id]
    
    with open(INVOICES_FILE, 'w') as f:
        json.dump(invoices, f, indent=2)
    
    return jsonify({"message": "Invoice deleted successfully"})

@app.route('/api/invoices/<invoice_id>', methods=['PUT'])
def update_invoice(invoice_id):
    updated_invoice = request.json
    
    with open(INVOICES_FILE, 'r') as f:
        invoices = json.load(f)
    
    # Find and update the invoice
    for i, inv in enumerate(invoices):
        if inv['id'] == invoice_id:
            # Keep the original ID and created_at
            updated_invoice['id'] = invoice_id
            updated_invoice['created_at'] = inv['created_at']
            updated_invoice['updated_at'] = datetime.now().isoformat()
            invoices[i] = updated_invoice
            break
    
    with open(INVOICES_FILE, 'w') as f:
        json.dump(invoices, f, indent=2)
    
    return jsonify(updated_invoice)

@app.route('/api/job-summary', methods=['GET'])
def get_job_summary():
    summary_file = os.path.join(DATA_DIR, 'job_summary.txt')
    
    default_summary = """Job Summary

This project includes the design, supply, and installation of a complete kitchen, tailored to your selections and specifications. The summary of work and materials is as follows:

Materials & Finishes
* Cabinetry: Choice of Melamine, Thermolaminate, or Polyurethane (Polyurethane / Poly) finishes for all cabinets, base units, wall units, and tall units.
* Benchtops: Selected from laminate, engineered stone, natural stone, porcelain, timber, or stainless steel. Fabrication includes sink and cooktop cutouts.
* Splashbacks: Options include tiled, glass, stone, or porcelain.
* Hardware & Accessories: Includes handles, soft-close hinges and drawers, pull-out bins, pantry inserts, and corner solutions.
* Doors & Special Features: Options include Pivot doors, Pocket doors, Bi-fold doors, and Lift-up units.

Scope of Work
1. Cabinetry Package: Supply and installation of all base, wall, tall, and island cabinets, including internal accessories and finishing details.
2. Benchtop Package: Supply, fabrication, and installation of selected benchtops.
3. Splashback Package: Supply and installation of splashback material as selected.
4. Appliances Package (Optional): Supply of appliances (oven, cooktop, rangehood, dishwasher, microwave, fridge) – installation included separately in Trades.
5. Trades Package: Full plumbing, electrical, tiling, stone, cabinet installation, demolition/site works, and Gyprock/plastering as required.
6. Project Management & Warranty: Full project scheduling, delivery of cabinets and stone, 10-year kitchen warranty, lifetime hardware warranty, and insurance where applicable.

Notes
* All selections and measurements are confirmed with the client prior to order and installation.
* Optional features such as LED lighting, decorative open shelving, and custom hardware can be included upon request.
* Installation timelines will be provided after final selections are confirmed."""
    
    if not os.path.exists(summary_file):
        with open(summary_file, 'w') as f:
            f.write(default_summary)
    
    with open(summary_file, 'r') as f:
        summary = f.read()
    
    return jsonify({"summary": summary})

@app.route('/api/job-summary', methods=['PUT'])
def update_job_summary():
    summary = request.json.get('summary', '')
    summary_file = os.path.join(DATA_DIR, 'job_summary.txt')
    
    with open(summary_file, 'w') as f:
        f.write(summary)
    
    return jsonify({"message": "Job summary updated successfully"})

@app.route('/api/company-settings', methods=['GET'])
def get_company_settings():
    settings = get_next_quote_number()
    return jsonify(settings)

@app.route('/api/company-settings', methods=['PUT'])
def update_company_settings():
    settings = request.json
    settings_file = os.path.join(DATA_DIR, 'company_settings.json')
    
    with open(settings_file, 'w') as f:
        json.dump(settings, f, indent=2)
    
    return jsonify({"message": "Company settings updated successfully"})

def get_next_quote_number():
    """
    Loads quote numbering settings.
    Creates default settings if file doesn't exist.
    Returns:
        {
            "quote_prefix": "JN",
            "next_quote_number": 5401,
            ...
        }
    """
    # Default settings
    default_settings = {
        "quote_prefix": "JN",
        "next_quote_number": 5401,

        # Allow other company fields to exist early on
        "company_name": "Your Company",
        "abn": "",
        "phone": "",
        "email": "",
        "address": "",
        "area_manager": "",
        "company_description": "",
        "payment_terms": "",
        "bank_account_name": "",
        "bank_bsb": "",
        "bank_account": ""
    }

    # If settings file missing → create with defaults
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(default_settings, f, indent=2)
        return default_settings

    # Load existing settings
    with open(SETTINGS_FILE, 'r') as f:
        settings = json.load(f)

    # Ensure missing fields are filled with defaults
    updated = False
    for key, value in default_settings.items():
        if key not in settings:
            settings[key] = value
            updated = True

    if updated:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)

    return settings

def increment_quote_number():
    """
    Increments the saved next_quote_number by 1.
    """
    settings = get_next_quote_number()
    settings['next_quote_number'] += 1

    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

@app.route('/api/invoices/<invoice_id>/pdf', methods=['GET'])
def generate_pdf_route(invoice_id):
    with open(INVOICES_FILE, 'r') as f:
        invoices = json.load(f)
    
    invoice = next((inv for inv in invoices if inv['id'] == invoice_id), None)
    
    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404
    
    # Get company settings
    settings = get_next_quote_number()  # or your company_settings.json
    
    # Generate PDF
    buffer = generate_pdf(invoice, settings)
    buffer.seek(0)
    
    filename = f"quote_{invoice.get('quote_number', invoice['id'][:8])}_{invoice['clientName'].replace(' ', '_')}.pdf"
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.lib import colors
import io
import os
from datetime import datetime

def generate_pdf(invoice, settings):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=20*mm, bottomMargin=25*mm,
                            leftMargin=15*mm, rightMargin=15*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title', parent=styles['Heading1'], fontSize=24, alignment=TA_LEFT)

    elements = []

    # ===== Logo top-right =====
    logo_path = os.path.join('data', 'logo.jpg')
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=80*mm, height=40*mm)
        logo.hAlign = 'RIGHT'
        elements.append(logo)
        elements.append(Spacer(1, 2*mm))

    # ===== Title top-left =====
    elements.append(Paragraph("<b>QUOTE</b>", title_style))
    elements.append(Spacer(1, 5*mm))

    # ===== Quote info & client info =====
    info_data = [
        [Paragraph(f"<b>Quote No:</b> {invoice.get('quote_number','N/A')}", styles['Normal']),
         Paragraph(f"<b>QUOTE TO:</b>", styles['Normal'])],
        [Paragraph(f"<b>Quote Date:</b> {datetime.fromisoformat(invoice['created_at']).strftime('%d %B %Y')}", styles['Normal']),
         Paragraph(f"<b>Client Name:</b> {invoice['clientName']}", styles['Normal'])],
        [Paragraph(f"<b>ABN:</b> {settings.get('abn','')}", styles['Normal']),
         Paragraph(f"<b>Client Number:</b> {invoice.get('clientNumber','N/A')}", styles['Normal'])]
    ]
    info_table = Table(info_data, colWidths=[90*mm, 90*mm])
    info_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    elements.append(info_table)
    elements.append(Spacer(1, 5*mm))

    # ===== Job Summary =====
    summary_file = os.path.join('data', 'job_summary.txt')
    if os.path.exists(summary_file):
        with open(summary_file, 'r') as f:
            job_summary = f.read()
        for line in job_summary.split('\n'):
            if line.strip():
                if line.startswith('Materials & Finishes') or line.startswith('Scope of Work') or line.startswith('Notes'):
                    elements.append(Paragraph(f"<b>{line}</b>", styles['Heading3']))
                else:
                    elements.append(Paragraph(line, styles['Normal']))
                elements.append(Spacer(1,2*mm))
    elements.append(Spacer(1,5*mm))

    # ===== Items Table =====
    table_data = [['NO.', 'DESCRIPTION', 'QTY', 'PRICE', 'TOTAL']]
    for idx, item in enumerate(invoice['items'], start=1):
        name = item.get('service', item.get('name'))
        if item.get('subService'):
            name += f" - {item['subService']}"
        table_data.append([
            str(idx),
            Paragraph(name, styles['Normal']),
            f"{item['quantity']} {item['unit']}{'s' if item['quantity']>1 else ''}",
            f"${item['price']:.2f}",
            f"${item['total']:.2f}"
        ])
        if item.get('notes'):
            note_style = ParagraphStyle('note', parent=styles['Normal'], fontSize=9, textColor=colors.grey, fontName='Helvetica-Oblique')
            table_data.append(['', Paragraph(f"<i>Note: {item['notes']}</i>", note_style), '', '', ''])

    subtotal = invoice['total']
    gst = subtotal * 0.1
    total_with_gst = subtotal + gst
    table_data.append(['', '', '', Paragraph('<b>Subtotal:</b>', styles['Normal']), f"${subtotal:.2f}"])
    table_data.append(['', '', '', Paragraph('<b>GST (10%):</b>', styles['Normal']), f"${gst:.2f}"])
    table_data.append(['', '', '', Paragraph('<b>Total:</b>', styles['Normal']), f"${total_with_gst:.2f}"])

    table = Table(table_data, colWidths=[15*mm, 90*mm, 25*mm, 30*mm, 25*mm])
    table.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-4),0.5,colors.grey),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('BACKGROUND',(0,0),(-1,0),colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(0,0),(0,-1),'CENTER'),
        ('ALIGN',(2,0),(-1,-1),'RIGHT'),
        ('VALIGN',(0,0),(-1,-1),'TOP')
    ]))
    elements.append(table)
    elements.append(Spacer(1,5*mm))

    # ===== Payment Info =====
    elements.append(Paragraph("<b>YOUR PAYMENT OPTIONS</b>", styles['Heading2']))
    elements.append(Spacer(1,2*mm))
    elements.append(Paragraph("<b>DIRECT DEPOSIT</b>", styles['Heading3']))
    elements.append(Spacer(1,2*mm))
    payment_info = f"""<b>Account Name:</b> {settings['bank_account_name']}<br/>
<b>BSB:</b> {settings['bank_bsb']}<br/>
<b>Account Number:</b> {settings['bank_account']}<br/>
<b>Reference:</b> {invoice.get('quote_number','N/A')}"""
    elements.append(Paragraph(payment_info, styles['Normal']))

    # ===== Footer: Contact Info at bottom of last page =====
    elements.append(Spacer(1, 50*mm))  # push footer down
    contact_info = f"""<b>INFO CONTACT:</b><br/>
{settings['company_name']}<br/>
{settings['phone']}<br/>
{settings['email']}<br/>
{settings['address']}<br/>
<b>{settings['area_manager']}</b><br/>
Area Manager"""
    elements.append(Paragraph(contact_info, styles['Normal']))

    doc.build(elements)
    buffer.seek(0)
    return buffer
'''
if __name__ == '__main__':
    # Use threaded=True and disable reloader to avoid Mac binding issues
    app.run(host='0.0.0.0', port=10000, debug=False, threaded=True)
    '''