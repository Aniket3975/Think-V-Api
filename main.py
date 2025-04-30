from fastapi import FastAPI, HTTPException, Request, Form, Body, APIRouter, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
import json
import os

app = FastAPI(title="IoT Analytics Platform", description="ThingSpeak-like API for IoT data")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Add session middleware for admin login and user authentication
app.add_middleware(SessionMiddleware, secret_key="admin123")

os.makedirs("static", exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# -----------------------------
# Data Models
# -----------------------------

class ChannelField(BaseModel):
    field_id: int
    name: str
    value: float = 0
    last_updated: str = Field(default_factory=lambda: datetime.now().isoformat())

class Channel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    fields: Dict[int, ChannelField] = {}
    metadata: Optional[Dict[str, Any]] = None
    api_key: str = Field(default_factory=lambda: "thinkv_" + str(uuid.uuid4()))
    delete_secret: str  # Secret phrase used for deletion
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_entry_id: int = 0

    class Config:
        orm_mode = True

class ChannelCreate(BaseModel):
    name: str
    description: Optional[str] = None
    field_names: List[str] = []
    delete_secret: str  # Required secret phrase for deletion

# New model for creating a field in an existing channel
class FieldCreate(BaseModel):
    name: str
    value: Optional[float] = 0

# -----------------------------
# Persistence Storage Functions
# -----------------------------

channels_db = {}
data_points_db = {}

def save_data_to_file():
    with open("data/channels.json", "w") as f:
        channels_json = {k: v.dict() for k, v in channels_db.items()}
        json.dump(channels_json, f)
    with open("data/data_points.json", "w") as f:
        json.dump(data_points_db, f)

def load_data_from_file():
    try:
        with open("data/channels.json", "r") as f:
            channels_json = json.load(f)
            for k, v in channels_json.items():
                channels_db[k] = Channel(**v)
    except FileNotFoundError:
        pass
    try:
        with open("data/data_points.json", "r") as f:
            data_points = json.load(f)
            data_points_db.update(data_points)
    except FileNotFoundError:
        pass

# Load data at startup
load_data_from_file()

# -----------------------------
# Authentication Dependency
# -----------------------------

async def require_authentication(request: Request):
    if not request.session.get("user_authenticated"):
        request.session["requested_url"] = str(request.url).replace(str(request.base_url), "/")
        return RedirectResponse(url="/login", status_code=303)
    return True

# -----------------------------
# Routes for Authentication
# -----------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return """
    <html>
        <head>
            <title>Login - IoT Analytics Platform</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <style> body { padding: 20px; } .container { max-width: 400px; margin-top: 100px; } </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="card-header">Login Required</div>
                    <div class="card-body">
                        <form action="/login" method="post">
                            <div class="mb-3">
                                <label for="password" class="form-label">Password</label>
                                <input type="password" class="form-control" id="password" name="password" required>
                            </div>
                            <button type="submit" class="btn btn-primary w-100">Login</button>
                        </form>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """

@app.post("/login")
async def process_login(request: Request, password: str = Form(...)):
    if password == "meta#2025&A":
        request.session["user_authenticated"] = True
        # Redirect to the page they were trying to access or home page
        redirect_url = request.session.get("requested_url", "/")
        request.session.pop("requested_url", None)
        return RedirectResponse(url=redirect_url, status_code=303)
    else:
        return """
        <html>
            <head>
                <title>Login Failed - IoT Analytics Platform</title>
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
                <style> body { padding: 20px; } .container { max-width: 400px; margin-top: 100px; } </style>
            </head>
            <body>
                <div class="container">
                    <div class="alert alert-danger">Invalid password. Please try again.</div>
                    <a href="/login" class="btn btn-primary">Back to Login</a>
                </div>
            </body>
        </html>
        """

@app.get("/logout")
async def logout(request: Request):
    request.session.pop("user_authenticated", None)
    return RedirectResponse(url="/login", status_code=303)

# -----------------------------
# Routes for Public Pages (now protected)
# -----------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, auth: bool = Depends(require_authentication)):
    if isinstance(auth, RedirectResponse):
        return auth
    
    return """
    <html>
        <head>
            <title>IoT Analytics Platform</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <style> body { padding: 20px; } .container { max-width: 800px; } </style>
        </head>
        <body>
            <div class="container">
                <h1>IoT Analytics Platform</h1>
                <p class="lead">A ThingSpeak-like platform for IoT data collection and visualization</p>
                <div class="card mb-4">
                    <div class="card-header">Channels</div>
                    <div class="card-body">
                        <a href="/channels" class="btn btn-primary">View All Channels (Public)</a>
                        <a href="/create-channel" class="btn btn-success">Create New Channel</a>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header">Admin Dashboard</div>
                    <div class="card-body">
                        <a href="/admin/dashboard" class="btn btn-warning">View All Channels (Admin)</a>
                    </div>
                </div>
                <div class="mt-3">
                    <a href="/logout" class="btn btn-outline-danger">Logout</a>
                </div>
            </div>
        </body>
    </html>
    """

@app.get("/channels", response_class=HTMLResponse)
async def list_channels(request: Request, auth: bool = Depends(require_authentication)):
    if isinstance(auth, RedirectResponse):
        return auth
        
    channels_html = "".join([
        f"""
        <div class="card mb-3">
            <div class="card-header">{channel.name}</div>
            <div class="card-body">
                <p>{channel.description or ""}</p>
                <p><small>Created: {channel.created_at}</small></p>
                <a href="/dashboard/{channel.id}" class="btn btn-primary">View Channel Dashboard</a>
                <a href="/channels/{channel.id}" class="btn btn-info">API Info</a>
            </div>
        </div>
        """ for channel in channels_db.values()
    ])
    
    return f"""
    <html>
        <head>
            <title>Channels - IoT Analytics Platform</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <style> body {{ padding: 20px; }} .container {{ max-width: 800px; }} </style>
        </head>
        <body>
            <div class="container">
                <h1>Channels (Public View)</h1>
                <div class="mb-4">
                    <a href="/" class="btn btn-secondary">Home</a>
                    <a href="/create-channel" class="btn btn-success">Create New Channel</a>
                    <a href="/logout" class="btn btn-outline-danger float-end">Logout</a>
                </div>
                {channels_html if channels_db else '<div class="alert alert-info">No channels created yet.</div>'}
            </div>
        </body>
    </html>
    """

@app.get("/create-channel", response_class=HTMLResponse)
async def create_channel_form(request: Request, auth: bool = Depends(require_authentication)):
    if isinstance(auth, RedirectResponse):
        return auth
        
    return """
    <html>
        <head>
            <title>Create Channel - IoT Analytics Platform</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <style> body { padding: 20px; } .container { max-width: 800px; } </style>
        </head>
        <body>
            <div class="container">
                <h1>Create New Channel</h1>
                <div class="mb-4">
                    <a href="/channels" class="btn btn-secondary">Back to Channels</a>
                    <a href="/logout" class="btn btn-outline-danger float-end">Logout</a>
                </div>
                <div class="card">
                    <div class="card-body">
                        <form action="/channels" method="post">
                            <div class="mb-3">
                                <label for="name" class="form-label">Channel Name</label>
                                <input type="text" class="form-control" id="name" name="name" required>
                            </div>
                            <div class="mb-3">
                                <label for="description" class="form-label">Description</label>
                                <textarea class="form-control" id="description" name="description" rows="3"></textarea>
                            </div>
                            <div class="mb-3">
                                <label for="delete_secret" class="form-label">Secret Phrase for Deletion</label>
                                <input type="text" class="form-control" id="delete_secret" name="delete_secret" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Fields (up to 8)</label>
                                <div class="row">
                                    <div class="col-md-6 mb-2"><input type="text" class="form-control" name="field_names" placeholder="Field 1"></div>
                                    <div class="col-md-6 mb-2"><input type="text" class="form-control" name="field_names" placeholder="Field 2"></div>
                                    <div class="col-md-6 mb-2"><input type="text" class="form-control" name="field_names" placeholder="Field 3"></div>
                                    <div class="col-md-6 mb-2"><input type="text" class="form-control" name="field_names" placeholder="Field 4"></div>
                                    <div class="col-md-6 mb-2"><input type="text" class="form-control" name="field_names" placeholder="Field 5"></div>
                                    <div class="col-md-6 mb-2"><input type="text" class="form-control" name="field_names" placeholder="Field 6"></div>
                                    <div class="col-md-6 mb-2"><input type="text" class="form-control" name="field_names" placeholder="Field 7"></div>
                                    <div class="col-md-6 mb-2"><input type="text" class="form-control" name="field_names" placeholder="Field 8"></div>
                                </div>
                            </div>
                            <button type="submit" class="btn btn-primary">Create Channel</button>
                        </form>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """

@app.post("/channels")
async def create_channel(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    delete_secret: str = Form(...),
    field_names: List[str] = Form([])
):
    # Filter out empty field names
    field_names = [name for name in field_names if name.strip()]
    
    # Create channel
    channel_data = ChannelCreate(
        name=name,
        description=description,
        field_names=field_names,
        delete_secret=delete_secret
    )
    
    channel = Channel(
        name=channel_data.name,
        description=channel_data.description,
        delete_secret=channel_data.delete_secret
    )
    
    # Add fields
    for i, field_name in enumerate(channel_data.field_names, 1):
        channel.fields[i] = ChannelField(field_id=i, name=field_name)
    
    # Save channel
    channels_db[channel.id] = channel
    data_points_db[channel.id] = {field_id: [] for field_id in channel.fields.keys()}
    save_data_to_file()
    
    return RedirectResponse(url=f"/channels/{channel.id}", status_code=303)

@app.get("/channels/{channel_id}", response_class=HTMLResponse)
async def channel_detail(request: Request, channel_id: str, auth: bool = Depends(require_authentication)):
    if isinstance(auth, RedirectResponse):
        return auth
        
    if channel_id not in channels_db:
        return HTMLResponse("<h1>Channel not found</h1>", status_code=404)
    
    channel = channels_db[channel_id]
    
    fields_html = "".join([
        f"""
        <tr>
            <td>{field.field_id}</td>
            <td>{field.name}</td>
            <td>{field.value}</td>
            <td>{field.last_updated}</td>
        </tr>
        """ for field in channel.fields.values()
    ])
    
    return f"""
    <html>
        <head>
            <title>{channel.name} - API Info</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <style> body {{ padding: 20px; }} .container {{ max-width: 800px; }} </style>
        </head>
        <body>
            <div class="container">
                <h1>{channel.name}</h1>
                <p>{channel.description or ""}</p>
                
                <div class="mb-4">
                    <a href="/channels" class="btn btn-secondary">Back to Channels</a>
                    <a href="/dashboard/{channel.id}" class="btn btn-primary">View Dashboard</a>
                    <a href="/logout" class="btn btn-outline-danger float-end">Logout</a>
                </div>
                
                <div class="card mb-4">
                    <div class="card-header">Channel Information</div>
                    <div class="card-body">
                        <p><strong>Channel ID:</strong> {channel.id}</p>
                        <p><strong>Created:</strong> {channel.created_at}</p>
                        <p><strong>Last Entry ID:</strong> {channel.last_entry_id}</p>
                        <p><strong>API Key:</strong> {channel.api_key}</p>
                    </div>
                </div>
                
                <div class="card mb-4">
                    <div class="card-header">Fields</div>
                    <div class="card-body">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>Field ID</th>
                                    <th>Name</th>
                                    <th>Current Value</th>
                                    <th>Last Updated</th>
                                </tr>
                            </thead>
                            <tbody>
                                {fields_html}
                            </tbody>
                        </table>
                    </div>
                </div>
                
                <div class="card mb-4">
                    <div class="card-header">API Endpoints</div>
                    <div class="card-body">
                        <h5>Get Channel Info</h5>
                        <p><code>GET /api/v1/channels/{channel.id}</code></p>
                        
                        <h5>Update Channel with New Values</h5>
                        <p><code>POST /api/v1/channels/{channel.id}/update</code></p>
                        <p>Required parameters: <code>api_key</code> and at least one field value (e.g., <code>field1=23.5</code>)</p>
                        <p>Example: <code>/api/v1/channels/{channel.id}/update?api_key={channel.api_key}&field1=23.5&field2=45.2</code></p>
                        
                        <h5>Get Field Data</h5>
                        <p><code>GET /api/v1/channels/{channel.id}/fields/FIELD_ID</code></p>
                        <p>Example: <code>/api/v1/channels/{channel.id}/fields/1</code> (for field 1)</p>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """

@app.get("/dashboard/{channel_id}", response_class=HTMLResponse)
async def channel_dashboard(request: Request, channel_id: str, auth: bool = Depends(require_authentication)):
    if isinstance(auth, RedirectResponse):
        return auth
        
    if channel_id not in channels_db:
        return HTMLResponse("<h1>Channel not found</h1>", status_code=404)
    
    channel = channels_db[channel_id]
    
    fields_html = "".join([
        f"""
        <div class="col-md-6 mb-4">
            <div class="card">
                <div class="card-header">
                    <h5>{field.name}</h5>
                </div>
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center">
                        <h3>{field.value}</h3>
                        <small class="text-muted">Last updated: {field.last_updated.split('T')[0]} {field.last_updated.split('T')[1].split('.')[0]}</small>
                    </div>
                    <div id="chart-field-{field.field_id}" class="mt-3" style="height: 200px; background-color: #f8f9fa; border-radius: 4px;">
                        <div class="text-center pt-5">Chart visualization would go here</div>
                    </div>
                </div>
            </div>
        </div>
        """ for field in channel.fields.values()
    ])
    
    return f"""
    <html>
        <head>
            <title>{channel.name} - Dashboard</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <style> body {{ padding: 20px; }} .container {{ max-width: 1200px; }} </style>
        </head>
        <body>
            <div class="container">
                <h1>{channel.name}</h1>
                <p>{channel.description or ""}</p>
                
                <div class="mb-4">
                    <a href="/channels" class="btn btn-secondary">Back to Channels</a>
                    <a href="/channels/{channel.id}" class="btn btn-info">API Info</a>
                    <a href="/logout" class="btn btn-outline-danger float-end">Logout</a>
                </div>
                
                <div class="row">
                    {fields_html}
                </div>
                
                <div class="card mt-3">
                    <div class="card-header">Channel Data</div>
                    <div class="card-body">
                        <p><strong>Channel ID:</strong> {channel.id}</p>
                        <p><strong>Created:</strong> {channel.created_at}</p>
                        <p><strong>Last Entry ID:</strong> {channel.last_entry_id}</p>
                        <p><strong>API Key:</strong> {channel.api_key}</p>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """

# -----------------------------
# API Router for IoT Data
# -----------------------------
api_router = APIRouter(prefix="/api/v1")

@api_router.get("/channels/{channel_id}")
async def api_get_channel(channel_id: str):
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    channel = channels_db[channel_id]
    return {
        "id": channel.id,
        "name": channel.name,
        "description": channel.description,
        "created_at": channel.created_at,
        "last_entry_id": channel.last_entry_id,
        "fields": [
            {
                "id": field_id,
                "name": field.name,
                "value": field.value,
                "last_updated": field.last_updated
            }
            for field_id, field in channel.fields.items()
        ]
    }

@api_router.get("/channels/{channel_id}/fields/{field_id}")
async def api_get_field_data(channel_id: str, field_id: int):
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    channel = channels_db[channel_id]
    
    if field_id not in channel.fields:
        raise HTTPException(status_code=404, detail=f"Field {field_id} not found")
    
    field = channel.fields[field_id]
    data_points = data_points_db.get(channel_id, {}).get(field_id, [])
    
    return {
        "channel_id": channel_id,
        "field_id": field_id,
        "name": field.name,
        "current_value": field.value,
        "last_updated": field.last_updated,
        "data_points": data_points
    }

@api_router.post("/channels/{channel_id}/update")
async def api_update_channel(
    channel_id: str,
    api_key: str,
    field1: Optional[float] = None,
    field2: Optional[float] = None,
    field3: Optional[float] = None,
    field4: Optional[float] = None,
    field5: Optional[float] = None,
    field6: Optional[float] = None,
    field7: Optional[float] = None,
    field8: Optional[float] = None
):
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    channel = channels_db[channel_id]
    
    if channel.api_key != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    timestamp = datetime.now().isoformat()
    channel.last_entry_id += 1
    
    field_values = {
        1: field1, 2: field2, 3: field3, 4: field4,
        5: field5, 6: field6, 7: field7, 8: field8
    }
    
    for field_id, value in field_values.items():
        if value is not None and field_id in channel.fields:
            # Update the field value
            channel.fields[field_id].value = value
            channel.fields[field_id].last_updated = timestamp
            
            # Store the data point
            if field_id not in data_points_db.get(channel_id, {}):
                data_points_db.setdefault(channel_id, {})[field_id] = []
            
            data_points_db[channel_id][field_id].append({
                "entry_id": channel.last_entry_id,
                "value": value,
                "timestamp": timestamp
            })
    
    save_data_to_file()
    
    return {"success": True, "entry_id": channel.last_entry_id}

# New Endpoint: Delete a channel (requires correct secret phrase)
@api_router.delete("/channels/{channel_id}")
async def api_delete_channel(channel_id: str, delete_secret: str):
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    channel = channels_db[channel_id]
    
    if channel.delete_secret != delete_secret:
        raise HTTPException(status_code=401, detail="Invalid secret phrase")
    
    del channels_db[channel_id]
    if channel_id in data_points_db:
        del data_points_db[channel_id]
    
    save_data_to_file()
    
    return {"success": True, "message": "Channel deleted successfully"}

# New Endpoint: Add a new field to an existing channel
@api_router.post("/channels/{channel_id}/fields", response_model=ChannelField)
async def api_add_field(channel_id: str, field: FieldCreate):
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    channel = channels_db[channel_id]
    new_field_id = max(channel.fields.keys(), default=0) + 1
    timestamp = datetime.now().isoformat()
    
    new_field = ChannelField(field_id=new_field_id, name=field.name, value=field.value, last_updated=timestamp)
    channel.fields[new_field_id] = new_field
    
    if channel_id in data_points_db:
        data_points_db[channel_id][new_field_id] = []
    else:
        data_points_db[channel_id] = {new_field_id: []}
    
    save_data_to_file()
    
    return new_field

app.include_router(api_router)

# -----------------------------
# Admin Login and Dashboard
# -----------------------------

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, auth: bool = Depends(require_authentication)):
    if isinstance(auth, RedirectResponse):
        return auth
    
    # Build admin dashboard HTML with more details
    channels_html = ""
    for channel in channels_db.values():
        channels_html += f"""
        <div class="card mb-3">
            <div class="card-header">
                <h3>{channel.name}</h3>
            </div>
            <div class="card-body">
                <p>{channel.description or ""}</p>
                <p><strong>Channel ID:</strong> {channel.id}</p>
                <p><strong>Created:</strong> {channel.created_at}</p>
                <p><strong>Last Entry ID:</strong> {channel.last_entry_id}</p>
                <p><strong>API Key:</strong> {channel.api_key}</p>
                <p><strong>Delete Secret:</strong> {channel.delete_secret}</p>
                <h5>API Endpoints:</h5>
                <ul>
                    <li>GET Channel: <code>/api/v1/channels/{channel.id}</code></li>
                    <li>Update Channel: <code>/api/v1/channels/{channel.id}/update?api_key={channel.api_key}</code></li>
                    <li>Delete Channel: <code>DELETE /api/v1/channels/{channel.id}?delete_secret={channel.delete_secret}</code></li>
                    <li>Add Field: <code>POST /api/v1/channels/{channel.id}/fields</code></li>
                </ul>
                <div class="mt-3">
                    <a href="/dashboard/{channel.id}" class="btn btn-info">View Channel Dashboard</a>
                    <a href="/channels/{channel.id}" class="btn btn-primary">View Channel API Info</a>
                    <button class="btn btn-danger" onclick="if(confirm('Are you sure you want to delete this channel?')) deleteChannel('{channel.id}', '{channel.delete_secret}')">Delete Channel</button>
                </div>
            </div>
        </div>
        """
    
    return f"""
    <html>
        <head>
            <title>Admin Dashboard - All Channels</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body {{ padding: 20px; }}
                .container {{ max-width: 1000px; margin: 0 auto; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Admin Dashboard</h1>
                <div class="mb-4">
                    <a href="/" class="btn btn-secondary">Home</a>
                    <a href="/channels" class="btn btn-primary">Public Channels</a>
                    <a href="/create-channel" class="btn btn-success">Create New Channel</a>
                    <a href="/logout" class="btn btn-outline-danger float-end">Logout</a>
                </div>
                
                {channels_html if channels_db else '<div class="alert alert-info">No channels found.</div>'}
            </div>
            
            <script>
                function deleteChannel(channelId, deleteSecret) {{
                    fetch(`/api/v1/channels/${{channelId}}?delete_secret=${{deleteSecret}}`, {{
                        method: 'DELETE'
                    }})
                    .then(response => response.json())
                    .then(data => {{
                        if (data.success) {{
                            alert('Channel deleted successfully!');
                            window.location.reload();
                        }} else {{
                            alert('Failed to delete channel: ' + data.message);
                        }}
                    }})
                    .catch(error => {{
                        alert('Error: ' + error);
                    }});
                }}
            </script>
        </body>
    </html>
    """

# -----------------------------
# Main Startup
# -----------------------------

# Create an admin_login.html template file
with open("templates/admin_login.html", "w") as f:
    f.write("""
    <!DOCTYPE html>
    <html>
        <head>
            <title>Admin Login - IoT Analytics Platform</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { padding: 20px; }
                .container { max-width: 400px; margin-top: 100px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="card-header">Admin Login</div>
                    <div class="card-body">
                        <form action="/admin/login" method="post">
                            <div class="mb-3">
                                <label for="username" class="form-label">Username</label>
                                <input type="text" class="form-control" id="username" name="username" required>
                            </div>
                            <div class="mb-3">
                                <label for="password" class="form-label">Password</label>
                                <input type="password" class="form-control" id="password" name="password" required>
                            </div>
                            <button type="submit" class="btn btn-primary w-100">Login</button>
                        </form>
                        <div class="mt-3 text-center">
                            <a href="/" class="text-decoration-none">Back to Public Site</a>
                        </div>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """)

# Create a custom CSS file for styling
with open("static/style.css", "w") as f:
    f.write("""
    /* Custom styles for IoT Analytics Platform */
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        background-color: #f5f7fa;
    }
    
    .container {
        padding: 1.5rem;
    }
    
    .card {
        box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
        margin-bottom: 1.5rem;
        border-radius: 0.375rem;
        overflow: hidden;
    }
    
    .btn {
        border-radius: 0.25rem;
        font-weight: 500;
    }
    
    .chart-container {
        height: 250px;
        background-color: #f8f9fa;
        border-radius: 4px;
        margin-top: 1rem;
        position: relative;
    }
    
    .field-value {
        font-size: 2rem;
        font-weight: 600;
    }
    
    .timestamp {
        font-size: 0.75rem;
        color: #6c757d;
    }
    """)

# For production, you would run the application like this:
if __name__ == "__main__":
     import uvicorn
     uvicorn.run(app, host="0.0.0.0", port=8000)

