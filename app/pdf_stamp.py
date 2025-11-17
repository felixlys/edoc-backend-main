from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black, Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from datetime import datetime
import os


APPROVED_DIR = os.getenv("APPROVED_DIR", "approved_docs")


def add_stamp_to_pdf(input_path, output_path, doc_info):
    reader = PdfReader(open(input_path, "rb"))
    writer = PdfWriter()

    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=(width, height))

        # === Font ===
        try:
            if os.path.exists("Calibri-Bold.ttf"):
                pdfmetrics.registerFont(TTFont("Calibri-Bold", "Calibri-Bold.ttf"))
                can.setFont("Calibri-Bold", 10)
            elif os.path.exists("Calibri.ttf"):
                pdfmetrics.registerFont(TTFont("Calibri", "Calibri.ttf"))
                can.setFont("Calibri", 10)
            else:
                can.setFont("Helvetica-Bold", 10)
        except:
            can.setFont("Helvetica-Bold", 10)

        # === Layout settings ===
        box_w, box_h = 140, 40
        margin_left, margin_bottom, gap_x, gap_y = 20, 30, 8, 10
        max_per_row = 4

        # === Data preparation ===
        boxes = []

        # Creator box
        boxes.append({
            "title": "Created By:",
            "name": doc_info.get("creator_name", "-"),
            "time": doc_info.get("timestamps", {}).get("creator", "-"),
            "color": Color(1, 1, 0.6)
        })

        # Approved approvers
        for a in doc_info.get("approvers", []):
            boxes.append({
                "title": "Approved By:",
                "name": a.get("name", "-"),
                "time": a.get("waktu", "-"),
                "color": Color(1, 1, 0.6)
            })

        # Rejected
        rejected_info = doc_info.get("rejected")
        if rejected_info and rejected_info.get("name"):
            boxes.append({
                "title": "Rejected By:",
                "name": rejected_info.get("name", "-"),
                "time": rejected_info.get("waktu", "-"),
                "color": Color(1, 0.7, 0.8)
            })

        # Jika tidak ada approver
        if not boxes:
            boxes = [{
                "title": "Created By:",
                "name": doc_info.get("creator_name", "-"),
                "time": doc_info.get("timestamps", {}).get("creator", "-"),
                "color": Color(1, 1, 0.6)
            }]

        # === Draw boxes ===
        for i, box in enumerate(boxes):
            row = i // max_per_row
            col = i % max_per_row
            x = margin_left + col * (box_w + gap_x)
            y = margin_bottom + (box_h + gap_y) * (1 - row)

            can.setFillColor(box["color"])
            can.rect(x, y, box_w, box_h, fill=1, stroke=0)

            can.setFillColor(black)
            can.drawString(x + 8, y + box_h - 13, box["title"])
            can.drawString(x + 8, y + box_h - 25, box["name"])
            can.drawString(x + 8, y + box_h - 37, box["time"])

        # === Document Number ===
        can.setFont("Helvetica-Bold", 10)
        can.drawString(margin_left, height - 30,
                       f"Document Number : {doc_info.get('no_surat', '-')}")

        can.save()
        packet.seek(0)
        overlay_pdf = PdfReader(packet)
        page.merge_page(overlay_pdf.pages[0])
        writer.add_page(page)
        packet.close()

    # Pastikan folder output ada
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path
