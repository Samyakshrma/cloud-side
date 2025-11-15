import sqlite3
import datetime
from pathlib import Path
import os
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# --- Configuration (Must match main.py) ---
DB_NAME = "incident_data.db"
TABLE_NAME = "validated_incidents"
DNN_CHECK_DIR = Path("dnn_check") 
REPORT_FILENAME = "Incident_Report.pdf"

# --- Main Report Generation Function ---
def generate_incident_report() -> Path:
    """
    Queries validated incidents from the database, collects corresponding images, 
    and generates a PDF report.
    
    Returns:
        Path: The path to the generated PDF file.
    """
    print("LOG: Starting incident report generation...")
    report_path = Path(REPORT_FILENAME)
    conn = None
    
    try:
        # 1. Connect and Query Data
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row # Allows access by column name
        cursor = conn.cursor()
        
        # Select all incidents, ordered by validation time
        cursor.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY validation_time ASC")
        incidents = cursor.fetchall()

        # 2. Setup PDF Document
        doc = SimpleDocTemplate(str(report_path), pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        # Custom style for incident details
        styles.add(ParagraphStyle(name='IncidentDetail', fontName='Helvetica', fontSize=10, leading=14))
        
        # Report Title Page/Header
        story.append(Paragraph("Incident Verification Report", styles['Title']))
        story.append(Spacer(1, 0.25 * inch))
        story.append(Paragraph(f"Total Validated Incidents: {len(incidents)}", styles['h2']))
        story.append(Paragraph(f"Report Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
        story.append(Spacer(1, 0.5 * inch))
        story.append(Paragraph("<hr/>", styles['Normal']))

        if not incidents:
            story.append(Spacer(1, 0.5 * inch))
            story.append(Paragraph("No validated incidents found to report.", styles['Normal']))
        else:
            # 3. Iterate over incidents and build the content (Story)
            for incident in incidents:
                image_name = incident['image_name']
                image_path = DNN_CHECK_DIR / image_name

                # Incident Heading
                story.append(Paragraph(f"Incident ID: <b>{image_name}</b>", styles['h2']))
                story.append(Spacer(1, 0.1 * inch))

                # Image Inclusion
                if image_path.exists():
                    img_max_width = 6 * inch # Max image width on the page
                    
                    try:
                        img = Image(str(image_path))
                        # Scale the image to fit the defined max width
                        scale_factor = img_max_width / img.drawWidth
                        img.drawWidth = img_max_width
                        img.drawHeight = img.drawHeight * scale_factor
                        
                        story.append(img)
                        story.append(Spacer(1, 0.1 * inch))
                    except Exception as img_e:
                        story.append(Paragraph(f"Image Error: Could not display image {image_name}. Check image format.", styles['IncidentDetail']))
                else:
                    story.append(Paragraph(f"<b>Image Missing!</b> File not found at {image_path}", styles['IncidentDetail']))

                # Details from SQLite
                story.append(Paragraph(f"<b>Alert Type:</b> {incident['alert_type']}", styles['IncidentDetail']))
                story.append(Paragraph(f"<b>Validated Face Count:</b> {incident['face_count_dnn']}", styles['IncidentDetail']))
                story.append(Paragraph(f"<b>Validation Timestamp:</b> {incident['validation_time']}", styles['IncidentDetail']))
                
                # Separator for the next incident
                story.append(Spacer(1, 0.5 * inch))
                story.append(Paragraph("<hr/>", styles['Normal']))
                story.append(Spacer(1, 0.25 * inch))
                
        # 4. Build the PDF
        doc.build(story)
        print(f"LOG: Report successfully generated at {report_path.resolve()}")
        return report_path

    except Exception as e:
        print(f"FATAL ERROR during report generation: {e}")
        # Clean up partial file if needed
        if report_path.exists():
            os.remove(report_path)
        raise Exception(f"Failed to generate report due to an internal error: {e}")
    finally:
        if conn:
            conn.close()