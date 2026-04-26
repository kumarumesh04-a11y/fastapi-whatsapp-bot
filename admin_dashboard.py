from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import logging
import csv
from io import StringIO

from database import (
    get_leads_by_client,
    get_all_leads,
    verify_client_login,
    hash_password
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])
templates = Jinja2Templates(directory="templates")

# Simple session store (use Redis in production)
client_sessions = {}

def get_current_client(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in client_sessions:
        return None
    return client_sessions[session_id]

@router.get("/login", response_class=HTMLResponse)
async def client_login_page(request: Request, error: str = None):
    error_html = f'<div class="error">{error}</div>' if error else ""
    
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Client Login - Ganpati AI</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
            .login-container {{ background: white; padding: 40px; border-radius: 10px; 
                              box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 300px; }}
            h2 {{ text-align: center; color: #333; margin-bottom: 30px; }}
            input {{ width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ddd; 
                     border-radius: 5px; box-sizing: border-box; }}
            button {{ width: 100%; padding: 10px; background: #667eea; color: white; 
                      border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }}
            button:hover {{ background: #5a67d8; }}
            .error {{ color: #ff6b6b; background: #fff5f5; padding: 10px; 
                      border-radius: 5px; text-align: center; margin-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="login-container">
            <h2>Client Login</h2>
            {error_html}
            <form method="post" action="/admin/auth">
                <input type="email" name="email" placeholder="Email" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Login</button>
            </form>
        </div>
    </body>
    </html>
    """)

@router.get("/auth")
async def auth_get():
    return RedirectResponse(url="/admin/login", status_code=303)


@router.post("/auth")
async def client_auth(email: str = Form(...), password: str = Form(...)):
    try:
        client = verify_client_login(email, password)
        
        if not client:
            return RedirectResponse(url="/admin/login?error=Invalid+credentials", status_code=303)
        
        session_id = hashlib.sha256(f"{email}{client['id']}".encode()).hexdigest()
        client_sessions[session_id] = {
            'client_id': client['id'],
            'email': client['email'],
            'company_name': client['company_name'],
            'industry_type': client.get('industry_type', 'general')
        }
        
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=86400)
        return response
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return RedirectResponse(url=f"/admin/login?error=System+error", status_code=303)

@router.get("/logout")
async def client_logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id and session_id in client_sessions:
        del client_sessions[session_id]
    
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("session_id")
    return response

@router.get("/dashboard", response_class=HTMLResponse)
async def client_dashboard(request: Request):
    client = get_current_client(request)
    if not client:
        return RedirectResponse(url="/admin/login", status_code=303)
    
    try:
        leads = get_leads_by_client(client['client_id'])
        industry = client.get('industry_type', 'general')
        
        # Dynamic headers based on industry
        if industry == 'legal_services':
            headers = ['ID', 'Name', 'Phone', 'Case Type', 'Urgency', 'Score', 'Status', 'Created']
        elif industry == 'real_estate':
            headers = ['ID', 'Name', 'Phone', 'Location', 'Budget', 'Score', 'Status', 'Created']
        else:
            headers = ['ID', 'Name', 'Phone', 'Details', 'Score', 'Status', 'Created']
        
        # Build table rows dynamically
        rows_html = ""
        for lead in leads:
            status_class = "status-new"
            if lead.get('status') == 'contacted':
                status_class = "status-contacted"
            elif lead.get('status') == 'closed':
                status_class = "status-closed"
            
            # Extract data from lead_data JSON
            lead_data = lead.get('lead_data', {})
            if isinstance(lead_data, str):
                import json
                try:
                    lead_data = json.loads(lead_data)
                except:
                    lead_data = {}
            
            if industry == 'legal_services':
                detail_cells = f"""
                    <td>{lead_data.get('case_type', '-')}</td>
                    <td>{lead_data.get('urgency', '-')}</td>
                """
            elif industry == 'real_estate':
                detail_cells = f"""
                    <td>{lead_data.get('location', '-')}</td>
                    <td>{lead_data.get('budget', '-')}</td>
                """
            else:
                detail_cells = f"<td>{str(lead_data)[:50]}</td>"
            
            rows_html += f"""
                <tr>
                    <td>{lead.get('id', '')}</td>
                    <td>{lead.get('name', '')}</td>
                    <td>{lead.get('phone', '')}</td>
                    {detail_cells}
                    <td>{lead.get('lead_score', 0)}</td>
                    <td><span class="{status_class}">{lead.get('status', 'New')}</span></td>
                    <td>{lead.get('created_at', '')}</td>
                </tr>
            """
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{client['company_name']} - Dashboard</title>
            <style>
                body {{ font-family: Arial, sans-serif; padding: 20px; background: #f0f0f0; margin: 0; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                          color: white; padding: 20px; margin-bottom: 20px; border-radius: 5px; }}
                .stats {{ background: white; padding: 15px; margin-bottom: 20px; 
                          border-radius: 5px; display: flex; gap: 20px; }}
                .stat-box {{ flex: 1; text-align: center; padding: 15px; 
                            background: #f8f9fa; border-radius: 5px; }}
                table {{ width: 100%; border-collapse: collapse; background: white; 
                        border-radius: 5px; overflow: hidden; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #667eea; color: white; }}
                tr:hover {{ background: #f5f5f5; }}
                .status-new {{ background: #ff9800; color: white; padding: 3px 8px; 
                               border-radius: 3px; font-size: 12px; }}
                .status-contacted {{ background: #2196F3; color: white; padding: 3px 8px; 
                                     border-radius: 3px; font-size: 12px; }}
                .status-closed {{ background: #4CAF50; color: white; padding: 3px 8px; 
                                  border-radius: 3px; font-size: 12px; }}
                .nav {{ background: white; padding: 10px; margin-bottom: 20px; border-radius: 5px; }}
                .nav a {{ color: #667eea; text-decoration: none; margin-right: 20px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{client['company_name']}</h1>
                <p>Lead Management Dashboard</p>
            </div>
            
            <div class="nav">
                <a href="/admin/dashboard">Dashboard</a>
                <a href="/admin/export-csv">Export CSV</a>
                <a href="/admin/logout">Logout</a>
            </div>
            
            <div class="stats">
                <div class="stat-box">
                    <h3>Total Leads</h3>
                    <p>{len(leads)}</p>
                </div>
            </div>
            
            <div style="overflow-x: auto;">
            <table>
                <thead>
                    <tr>
                        {''.join(f'<th>{h}</th>' for h in headers)}
                    </tr>
                </thead>
                <tbody>
                    {rows_html if rows_html else '<tr><td colspan="' + str(len(headers)) + '">No leads yet</td></tr>'}
                </tbody>
            </table>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html)
        
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>", status_code=500)

@router.get("/export-csv")
async def export_leads_csv(request: Request):
    client = get_current_client(request)
    if not client:
        return RedirectResponse(url="/admin/login", status_code=303)
    
    leads = get_leads_by_client(client['client_id'], limit=10000)
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ID', 'Name', 'Phone', 'Lead Data', 'Score', 'Status', 'Created At'])
    
    for lead in leads:
        writer.writerow([
            lead.get('id', ''),
            lead.get('name', ''),
            lead.get('phone', ''),
            str(lead.get('lead_data', '')),
            lead.get('lead_score', 0),
            lead.get('status', ''),
            lead.get('created_at', '')
        ])
    
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={client['company_name']}_leads.csv"}
    )

@router.get("/master", response_class=HTMLResponse)
async def master_admin_dashboard():
    """Master admin - view all leads"""
    try:
        leads = get_all_leads()
        
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Master Admin - All Leads</title>
            <style>
                body { font-family: Arial, sans-serif; padding: 20px; background: #f0f0f0; }
                h1 { color: #333; }
                table { width: 100%; border-collapse: collapse; background: white; }
                th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
                th { background: #dc3545; color: white; }
                tr:hover { background: #f5f5f5; }
            </style>
        </head>
        <body>
            <h1>Master Admin - All Leads</h1>
            <h3>Total: """ + str(len(leads)) + """</h3>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Client</th>
                        <th>Name</th>
                        <th>Phone</th>
                        <th>Industry</th>
                        <th>Score</th>
                        <th>Status</th>
                        <th>Created</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for lead in leads:
            html += f"""
                <tr>
                    <td>{lead.get('id', '')}</td>
                    <td>{lead.get('client_name', 'Unknown')}</td>
                    <td>{lead.get('name', '')}</td>
                    <td>{lead.get('phone', '')}</td>
                    <td>{lead.get('industry_type', '-')}</td>
                    <td>{lead.get('lead_score', 0)}</td>
                    <td>{lead.get('status', 'New')}</td>
                    <td>{lead.get('created_at', '')}</td>
                </tr>
            """
        
        html += """
                </tbody>
            </table>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html)
        
    except Exception as e:
        logger.error(f"Master dashboard error: {e}")
        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>", status_code=500)