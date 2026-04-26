import os
import logging
import json
from datetime import datetime

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from database import (
    get_db_conn,
    get_client_by_id,
    get_client_by_phone_number,
    get_flow_config,
    get_user_session,
    update_user_session,
    clear_user_session,
    create_lead,
    check_client_lead_limit,
    log_error
)
from flow_engine import FlowEngine
from action import WhatsAppActions
from admin_dashboard import router as admin_router

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Include admin dashboard routes - MUST be before other routes
app.include_router(admin_router)

templates = Jinja2Templates(directory="templates")
wa = WhatsAppActions()
flow_engine = FlowEngine()

VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "ganpatiai_2025_secret")

@app.get("/test-db")
async def test_db():
    try:
        from database import get_client_by_id
        client = get_client_by_id(1)
        if client:
            return {"status": "connected", "client": client["company_name"]}
        else:
            return {"status": "connected but client not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html>
    <head><title>Ganpati AI</title></head>
    <body>
        <h1>Ganpati AI Universal Chatbot</h1>
        <p>Status: Running</p>
        <p><a href="/health">Health Check</a></p>
        <p><a href="/admin/login">Admin Login</a></p>
    </body>
    </html>
    """)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/whatsapp")
async def verify_meta_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if mode and token and mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified")
        return int(challenge)
    return {"error": "Verification failed"}, 403

@app.post("/whatsapp")
async def handle_meta_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        if "messages" not in value:
            return {"status": "ignored"}
        
        message_obj = value["messages"][0]
        phone = message_obj.get("from")
        
        receiving_number = value.get("metadata", {}).get("display_phone_number")
        
        contacts = value.get("contacts", [])
        name = contacts[0].get("profile", {}).get("name", "User") if contacts else "User"
        
        msg_body = None
        interactive_data = None
        
        if message_obj.get("type") == "text":
            msg_body = message_obj.get("text", {}).get("body", "").strip()
        elif message_obj.get("type") == "interactive":
            interactive_data = message_obj.get("interactive")
        
        if not phone:
            return {"status": "ignored"}
        
        background_tasks.add_task(
            process_message,
            phone,
            name,
            msg_body,
            interactive_data,
            receiving_number
        )
        
    except Exception as e:
        logger.error(f"Webhook Error: {e}", exc_info=True)
        log_error(phone="unknown", error_message=str(e))
    
    return {"status": "ok"}

async def process_message(phone: str, name: str, message: str, interactive_data: dict, receiving_number: str = None):
    try:
        session = get_user_session(phone)
        
        client_id = None
        
        if message and message.startswith("START_"):
            parts = message.split("_")
            try:
                if len(parts) == 2:
                    client_id = int(parts[1])
                elif len(parts) >= 3:    
                    client_id = int(parts[2])
                else:
                    client_id = None
            except ValueError:
                client_id = None
        
        if not client_id and session.get('client_id'):
            client_id = session['client_id']
        
        if not client_id:
            await wa.send_text(phone, "Welcome to Ganpati AI. Please scan the QR code provided by the business to start.")
            return
        
        client = get_client_by_id(client_id)
        if not client:
            await wa.send_text(phone, "Invalid business reference. Please contact support.")
            return
        
        if not check_client_lead_limit(client_id):
            await wa.send_text(phone, "This service is currently unavailable. Please try again later.")
            return
        
        flow_config = get_flow_config(client_id)
        if not flow_config:
            await wa.send_text(phone, "Configuration error. Please contact support.")
            return
        
        update_user_session(phone, {
            'client_id': client_id,
            'industry_type': client.get('industry_type', 'general')
        })
        
        await flow_engine.process(
            phone=phone,
            name=name,
            message=message,
            interactive_data=interactive_data,
            client=client,
            flow_config=flow_config,
            session=session,
            wa=wa
        )
        
    except Exception as e:
        logger.error(f"Process message error: {e}", exc_info=True)
        log_error(phone=phone, client_id=client_id, error_message=str(e))
        await wa.send_text(phone, "Sorry, something went wrong. Please try again.")

# ============ QR CODE ENDPOINTS ============

@app.get("/qr/generate/{client_id}")
async def generate_qr_code(client_id: str):
    import qrcode
    from fastapi.responses import FileResponse
    
    try:
        os.makedirs("static/qrcodes", exist_ok=True)
        
        # Your test phone number (formatted without + or spaces)
        phone_number = "918438813814"
        
        # Create QR code that opens WhatsApp with your test number
        qr_data = f"https://wa.me/{phone_number}?text=START_{client_id}"
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        file_path = f"static/qrcodes/{client_id}.png"
        img.save(file_path)
        
        return FileResponse(file_path, media_type="image/png", filename=f"{client_id}.png")
        
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Failed: {str(e)}"})


@app.get("/qr/{client_id}")
async def get_qr_code(client_id: str):
    """
    Get existing QR code for a client
    """
    from fastapi.responses import FileResponse
    
    file_path = f"static/qrcodes/{client_id}.png"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/png")
    else:
        return JSONResponse(
            status_code=404, 
            content={"error": "QR code not found. Generate it first using /qr/generate/{client_id}"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))