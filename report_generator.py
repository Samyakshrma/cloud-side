# report_generator.py
import datetime
from pathlib import Path
import os
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# --- CORRECTED IMPORTS ---
from database import (
    get_db_connection, 
    get_and_clear_all_stats, # <-- FIXED: Changed from get_and_clear_verification_stats
    TABLE_INCIDENTS
)

DNN_CHECK_DIR = Path("dnn_check") 
REPORT_FILENAME = "Incident_Report.pdf"

def generate_incident_report():
    """
    1. Queries validated incidents from Postgres.
    2. Queries verification stats (metrics).
    3. Generates PDF.
    4. Clears BOTH tables in Postgres.
    
    Returns:
        (Path, Dict): The path to the PDF and the dictionary of stats.
    """
    print("LOG: Starting incident report generation...")
    report_path = Path(REPORT_FILENAME)
    conn = get_db_connection()
    
    if not conn:
        raise Exception("Database connection failed during report generation.")

    incidents = []
    stats_data = {}

    try:
        cursor = conn.cursor()
        
        # 1. Fetch Incidents (for the PDF)
        cursor.execute(f"SELECT image_name, alert_type, face_count_dnn, validation_time FROM {TABLE_INCIDENTS} ORDER BY validation_time ASC")
        # Convert tuple rows to list of dicts for easier handling
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        incidents = [dict(zip(columns, row)) for row in rows]

        # 2. Fetch Stats (for the Frontend Graphs)
        # This function also internally clears the stats table!
        stats_data = get_and_clear_all_stats() # <-- FIXED: Correct function call

        # 3. Generate PDF Report
        doc = SimpleDocTemplate(str(report_path), pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        styles.add(ParagraphStyle(name='IncidentDetail', fontName='Helvetica', fontSize=10, leading=14))
        
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
            for incident in incidents:
                image_name = incident['image_name']
                # Ensure we handle the Path correctly
                image_path = DNN_CHECK_DIR / image_name

                story.append(Paragraph(f"Incident ID: <b>{image_name}</b>", styles['h2']))
                story.append(Spacer(1, 0.1 * inch))

                if image_path.exists():
                    img_max_width = 6 * inch 
                    try:
                        img = Image(str(image_path))
                        scale_factor = img_max_width / img.drawWidth
                        img.drawWidth = img_max_width
                        img.drawHeight = img.drawHeight * scale_factor
                        story.append(img)
                        story.append(Spacer(1, 0.1 * inch))
                    except Exception as img_e:
                        story.append(Paragraph(f"Image Error: Could not display image.", styles['IncidentDetail']))
                else:
                    story.append(Paragraph(f"<b>Image Missing!</b> File not found.", styles['IncidentDetail']))

                story.append(Paragraph(f"<b>Alert Type:</b> {incident['alert_type']}", styles['IncidentDetail']))
                story.append(Paragraph(f"<b>Face Count:</b> {incident['face_count_dnn']}", styles['IncidentDetail']))
                story.append(Paragraph(f"<b>Time:</b> {incident['validation_time']}", styles['IncidentDetail']))
                story.append(Paragraph("<hr/>", styles['Normal']))
                
        doc.build(story)
        print(f"LOG: PDF generated at {report_path.resolve()}")

        # 4. Clear the Incidents Table (Stats were cleared in step 2)
        if incidents:
            print(f"LOG: Clearing {len(incidents)} records from {TABLE_INCIDENTS}...")
            cursor.execute(f"DELETE FROM {TABLE_INCIDENTS}")
            conn.commit()

        # Return both the file path and the stats for the frontend
        return report_path, stats_data

    except Exception as e:
        print(f"FATAL ERROR during report generation: {e}")
        if conn:
            conn.rollback()
        raise Exception(f"Failed to generate report: {e}")
    finally:
        if conn:
            conn.close()