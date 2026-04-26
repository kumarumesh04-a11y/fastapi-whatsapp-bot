import qrcode
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class QRGenerator:
    def __init__(self, base_whatsapp_number: str = "918438813814"):
        self.base_number = base_whatsapp_number
        self.static_dir = "static/qr_codes"
        os.makedirs(self.static_dir, exist_ok=True)
    
    def generate_client_qr(self, client_id: int, industry_type: str, 
                          company_name: str = "") -> str:
        """Generate QR code for a client"""
        
        # Format: START_LEGAL_5
        message = f"START_{industry_type.upper()}_{client_id}"
        
        # WhatsApp click-to-chat URL
        wa_url = f"https://wa.me/{self.base_number}?text={message}"
        
        # Generate QR
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(wa_url)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save
        filename = f"client_{client_id}_{industry_type}.png"
        filepath = os.path.join(self.static_dir, filename)
        img.save(filepath)
        
        logger.info(f"QR generated for client {client_id}: {filepath}")
        return filepath
    
    def get_qr_url(self, client_id: int, industry_type: str) -> str:
        """Get URL path for client's QR code"""
        filename = f"client_{client_id}_{industry_type}.png"
        return f"/static/qr_codes/{filename}"