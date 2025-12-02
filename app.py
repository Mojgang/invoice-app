from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import os
from datetime import datetime
import uuid
import io
import pytz
import psycopg2
from psycopg2.extras import RealDictCursor, Json

# ReportLab imports
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

app = Flask(__name__, static_folder='static')
CORS(app)

# ============================================
# DATABASE CONNECTION (POSTGRESQL ONLY)
# ============================================

def get_db_connection():
    """Get PostgreSQL connection from Supabase"""
    db_url = os.environ.get('DATABASE_URL')
    
    if not db_url:
        # Build from individual components
        host = os.environ.get('SUPABASE_DB_HOST')
        password = os.environ.get('SUPABASE_DB_PASSWORD')
        
        if host and password:
            db_url = f"postgresql://postgres.{host}:5432/postgres?password={password}"
    
    if not db_url:
        raise Exception("No database credentials found. Set DATABASE_URL or SUPABASE_DB_HOST + SUPABASE_DB_PASSWORD")
    
    try:
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        raise

def init_database():
    """Initialize database tables"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        print("Creating database tables...")
        
        # Create invoices table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id TEXT PRIMARY KEY,
                quote_number TEXT,
                client_name TEXT,
                client_number TEXT,
                project_notes TEXT,
                items JSONB,
                total DECIMAL(10,2),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ
            )
        """)
        
        # Create settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value JSONB,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoices_created 
            ON invoices(created_at DESC)
        """)
        
        # Initialize default settings if not exist
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES ('company_settings', %s)
            ON CONFLICT (key) DO NOTHING
        """, (Json({
            "quote_prefix": "JN",
            "next_quote_number": 5401,
            "company_name": "Your Company",
            "abn": "",
            "phone": "",
            "email": "",
            "address": "",
            "area_manager": "",
            "bank_account_name": "",
            "bank_bsb": "",
            "bank_account": ""
        }),))
        
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES ('services', %s)
            ON CONFLICT (key) DO NOTHING
        """, (Json({
            "electrician": {"name": "Electrician", "price": 85, "unit": "hour"},
            "plumber": {"name": "Plumber", "price": 90, "unit": "hour"}
        }),))
        
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES ('job_summary', %s)
            ON CONFLICT (key) DO NOTHING
        """, (Json({"text": "Default job summary..."}),))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Database initialized successfully")
        return True
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise

# Initialize database on startup
try:
    init_database()
except Exception as e:
    print(f"❌ FATAL: Cannot start without database: {e}")
    import sys
    sys.exit(1)

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_setting(key, default_value):
    """Get setting from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = %s", (key,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if row:
            return row['value']
        return default_value
        
    except Exception as e:
        print(f"Error fetching {key} from DB: {e}")
        return default_value

def set_setting(key, value):
    """Set setting in database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (key) 
            DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
        """, (key, Json(value), datetime.now().isoformat()))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving {key} to DB: {e}")
        return False

# ============================================
# ROUTES - MAIN
# ============================================

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({"status": "healthy", "database": "connected"})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# ============================================
# ROUTES - SERVICES
# ============================================

@app.route('/api/services', methods=['GET'])
def get_services():
    """Get services from database"""
    defaults = {
        "electrician": {"name": "Electrician", "price": 85, "unit": "hour"},
        "plumber": {"name": "Plumber", "price": 90, "unit": "hour"}
    }
    services = get_setting('services', defaults)
    return jsonify(services)

@app.route('/api/services', methods=['PUT'])
def update_services():
    """Update services in database"""
    services = request.json
    success = set_setting('services', services)
    if success:
        return jsonify({"message": "Services updated successfully"})
    return jsonify({"error": "Failed to update services"}), 500

@app.route('/api/services/migrate', methods=['POST'])
def migrate_services():
    """Migrate services - returns current services from DB"""
    services = get_setting('services', {})
    return jsonify({
        "message": "Services loaded from database",
        "services": services
    })

# ============================================
# ROUTES - INVOICES
# ============================================

@app.route('/api/invoices', methods=['GET'])
def get_invoices():
    """Get all invoices from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoices ORDER BY created_at DESC")
        invoices = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify([dict(inv) for inv in invoices])
    except Exception as e:
        print(f"Error fetching invoices: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/invoices', methods=['POST'])
def create_invoice():
    """Create new invoice in database"""
    try:
        invoice = request.json
        
        # Get settings for quote number
        settings = get_setting('company_settings', {
            'quote_prefix': 'JN',
            'next_quote_number': 5401
        })
        
        # Generate quote number
        quote_number = f"{settings.get('quote_prefix', 'JN')}{settings.get('next_quote_number', 5401)}"
        invoice_id = str(uuid.uuid4())
        
        # Use Australian timezone
        aus_tz = pytz.timezone('Australia/Sydney')
        created_at = datetime.now(aus_tz).isoformat()
        
        # Save to database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO invoices (id, quote_number, client_name, client_number, 
                                 project_notes, items, total, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            invoice_id,
            quote_number,
            invoice['clientName'],
            invoice.get('clientNumber', ''),
            invoice.get('projectNotes', ''),
            Json(invoice['items']),
            invoice['total'],
            created_at
        ))
        
        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        
        # Increment quote number
        settings['next_quote_number'] = settings.get('next_quote_number', 5401) + 1
        set_setting('company_settings', settings)
        
        return jsonify(dict(result)), 201
        
    except Exception as e:
        print(f"Error creating invoice: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/invoices/<invoice_id>', methods=['DELETE'])
def delete_invoice(invoice_id):
    """Delete invoice from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Invoice deleted successfully"})
    except Exception as e:
        print(f"Error deleting invoice: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/invoices/<invoice_id>', methods=['PUT'])
def update_invoice(invoice_id):
    """Update invoice in database"""
    try:
        invoice = request.json
        updated_at = datetime.now().isoformat()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE invoices 
            SET client_name = %s, client_number = %s, project_notes = %s,
                items = %s, total = %s, updated_at = %s
            WHERE id = %s
            RETURNING *
        """, (
            invoice['clientName'],
            invoice.get('clientNumber', ''),
            invoice.get('projectNotes', ''),
            Json(invoice['items']),
            invoice['total'],
            updated_at,
            invoice_id
        ))
        
        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        
        if result:
            return jsonify(dict(result))
        return jsonify({"error": "Invoice not found"}), 404
        
    except Exception as e:
        print(f"Error updating invoice: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================
# ROUTES - JOB SUMMARY
# ============================================

@app.route('/api/job-summary', methods=['GET'])
def get_job_summary():
    """Get job summary from database"""
    data = get_setting('job_summary', {"text": "Default summary..."})
    return jsonify({"summary": data.get('text', '')})

@app.route('/api/job-summary', methods=['PUT'])
def update_job_summary():
    """Update job summary in database"""
    summary_text = request.json.get('summary', '')
    success = set_setting('job_summary', {"text": summary_text})
    if success:
        return jsonify({"message": "Job summary updated successfully"})
    return jsonify({"error": "Failed to update job summary"}), 500

# ============================================
# ROUTES - COMPANY SETTINGS
# ============================================

@app.route('/api/company-settings', methods=['GET'])
def get_company_settings():
    """Get company settings from database"""
    defaults = {
        "quote_prefix": "JN",
        "next_quote_number": 5401,
        "company_name": "Your Company",
        "abn": "",
        "phone": "",
        "email": "",
        "address": "",
        "area_manager": "",
        "bank_account_name": "",
        "bank_bsb": "",
        "bank_account": ""
    }
    settings = get_setting('company_settings', defaults)
    return jsonify(settings)

@app.route('/api/company-settings', methods=['PUT'])
def update_company_settings():
    """Update company settings in database"""
    settings = request.json
    success = set_setting('company_settings', settings)
    if success:
        return jsonify({"message": "Company settings updated successfully"})
    return jsonify({"error": "Failed to update settings"}), 500

# ============================================
# ROUTES - PDF GENERATION
# ============================================

@app.route('/api/invoices/<invoice_id>/pdf', methods=['GET'])
def generate_pdf_route(invoice_id):
    """Generate PDF for invoice"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not row:
            return jsonify({"error": "Invoice not found"}), 404
        
        invoice = dict(row)
        
        # Get settings and job summary
        settings = get_setting('company_settings', {})
        summary_data = get_setting('job_summary', {"text": ""})
        job_summary_text = summary_data.get('text', '')
        
        # Generate PDF
        buffer = generate_pdf(invoice, settings, job_summary_text)
        buffer.seek(0)
        
        filename = f"quote_{invoice.get('quote_number', 'draft')}_{invoice.get('client_name', 'client').replace(' ', '_')}.pdf"
        
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================
# PDF GENERATION FUNCTION
# ============================================

def generate_pdf(invoice, settings, job_summary_text):
    """Generate PDF content"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)

    styles = getSampleStyleSheet()
    
    # Header styles
    header_title = ParagraphStyle('HeaderTitle', parent=styles['Heading1'], 
                                   fontSize=24, spaceAfter=8, textColor=colors.black)
    header_text = ParagraphStyle('HeaderText', parent=styles['Normal'], 
                                  fontSize=10, leading=14)
    total_label_style = ParagraphStyle('TotalLabel', parent=styles['Normal'], 
                                        alignment=TA_RIGHT)
    
    # Job summary styles
    summary_main = ParagraphStyle('SummaryMain', parent=styles['Normal'], 
                                   fontSize=11, leading=15, fontName='Helvetica-Bold', 
                                   spaceBefore=10, spaceAfter=4)
    summary_sub = ParagraphStyle('SummarySub', parent=styles['Normal'], 
                                  fontSize=10, leading=14, fontName='Helvetica-Bold', 
                                  spaceBefore=3)
    summary_bullet = ParagraphStyle('SummaryBullet', parent=styles['Normal'], 
                                     fontSize=10, leading=14, leftIndent=12)

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

    # Logo placeholder (you can upload logo to static folder and reference it)
    right_column = [Paragraph("", header_text)]

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

    # ================= JOB SUMMARY =================
    if job_summary_text:
        elements.append(Paragraph("JOB SUMMARY:", summary_main))

        for line in job_summary_text.split('\n'):
            line = line.strip()
            if not line:
                continue 

            if line.startswith('##'):
                clean_text = line[2:].strip()
                elements.append(Paragraph(clean_text, summary_sub))
            elif line.startswith('#'):
                clean_text = line[1:].strip()
                elements.append(Paragraph(clean_text, summary_main))
            elif line.startswith('*') or line.startswith('-'):
                clean_text = line.lstrip('*-').strip()
                elements.append(Paragraph(f"• {clean_text}", summary_bullet))
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
            note_style = ParagraphStyle('note', parent=styles['Normal'], 
                                        fontSize=9, textColor=colors.grey, 
                                        fontName='Helvetica-Oblique')
            table_data.append(['', Paragraph(f"<i>Note: {item['notes']}</i>", note_style), ''])

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

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)