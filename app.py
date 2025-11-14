from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import json
import os
from datetime import datetime
import uuid
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
import io

app = Flask(__name__, static_folder='static')
CORS(app)

# Data storage files
DATA_DIR = 'data'
SERVICES_FILE = os.path.join(DATA_DIR, 'services.json')
INVOICES_FILE = os.path.join(DATA_DIR, 'invoices.json')

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

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
    invoice['id'] = str(uuid.uuid4())
    invoice['created_at'] = datetime.now().isoformat()
    
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


@app.route('/api/invoices/<invoice_id>/pdf', methods=['GET'])
def generate_pdf(invoice_id):
    with open(INVOICES_FILE, 'r') as f:
        invoices = json.load(f)
    
    invoice = next((inv for inv in invoices if inv['id'] == invoice_id), None)
    
    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404
    
    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title = Paragraph(f"<b>INVOICE</b>", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 0.3*inch))
    
    # Client and Date info
    date_str = datetime.fromisoformat(invoice['created_at']).strftime('%B %d, %Y')
    info = Paragraph(f"<b>Client:</b> {invoice['clientName']}<br/><b>Date:</b> {date_str}<br/><b>Invoice ID:</b> {invoice['id'][:8]}", styles['Normal'])
    elements.append(info)
    elements.append(Spacer(1, 0.5*inch))
    
    # Items table
    table_data = [['Service', 'Quantity', 'Unit Price', 'Total']]
    
    for item in invoice['items']:
        service_name = item['service']
        if item.get('subService'):
            service_name += f" - {item['subService']}"
        
        table_data.append([
            service_name,
            f"{item['quantity']} {item['unit']}{'s' if item['quantity'] > 1 else ''}",
            f"${item['price']:.2f}",
            f"${item['total']:.2f}"
        ])
    
    # Add total row
    table_data.append(['', '', 'TOTAL', f"${invoice['total']:.2f}"])
    
    table = Table(table_data, colWidths=[3*inch, 1.5*inch, 1.2*inch, 1.2*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    filename = f"invoice_{invoice['clientName'].replace(' ', '_')}_{invoice['id'][:8]}.pdf"
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)