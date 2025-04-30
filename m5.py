# m5.py (Full Code - v1.5.1 incorporating Showcase Files/Appearance)

# --- Imports ---
from fastapi import (FastAPI, HTTPException, Request, Form, Body, Depends,
                     File, UploadFile, Query)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
import json
import os
import random
from contextlib import asynccontextmanager
import io
import shutil # For file operations
from pathlib import Path # For path manipulation

# --- QR Code Imports ---
try:
    import qrcode
    from PIL import Image
    QRCODE_INSTALLED = True
except ImportError:
    QRCODE_INSTALLED = False
    print("\n" + "="*60); print("WARNING: 'qrcode' or 'Pillow' not installed."); print("QR code generation feature will be disabled."); print("Install using: pip install qrcode[pil] Pillow"); print("="*60 + "\n")

# --- Directory Setup ---
DATA_DIR = Path("data")
STATIC_DIR = Path("static")
UPLOAD_DIR = STATIC_DIR / "uploads" # Place uploads inside static
TEMPLATES_DIR = Path("templates")
DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

# --- Data models ---
class ChannelField(BaseModel):
    field_id: int
    name: str
    value: float = 0.0
    last_updated: str = Field(default_factory=lambda: datetime.now().isoformat())

class ShowcaseAppearance(BaseModel):
    bg_color: Optional[str] = '#f8f9fa' # Default light gray
    section_bg_color: Optional[str] = '#ffffff' # Default white
    accent_color: Optional[str] = '#0d6efd' # Default primary blue
    background_image_url: Optional[str] = None # Relative path '/static/uploads/...'

    @field_validator('bg_color', 'section_bg_color', 'accent_color', mode='before')
    @classmethod
    def check_color_format(cls, value):
        if value is None: return value
        if isinstance(value, str) and value.startswith('#') and (len(value) == 7 or len(value) == 4): return value # Allow #RGB and #RRGGBB
        if isinstance(value, str) and not value: return None # Allow empty string to clear/reset maybe
        # Basic check, could use a regex library for more robustness
        print(f"Warning: Invalid color format received '{value}'. Using default.")
        # Instead of raising, maybe return default? Or None? Let's return None for now.
        return None # Return None if invalid, default factory will handle it if needed.
        # raise ValueError('Color must be a valid hex code (e.g., #RRGGBB)')

class ShowcaseData(BaseModel):
    introduction: Optional[str] = ""
    achievements: List[str] = Field(default_factory=list)
    image_urls: List[str] = Field(default_factory=list) # Allow any string URL for now
    youtube_links: List[str] = Field(default_factory=list) # Allow any string URL

    poster_image_url: Optional[str] = None # Relative path
    poster_filename: Optional[str] = None
    slides_url: Optional[str] = None       # Relative path
    slides_filename: Optional[str] = None
    slides_link_external: Optional[str] = None # External URL link

    appearance: ShowcaseAppearance = Field(default_factory=ShowcaseAppearance)

    model_config = { "from_attributes": True, "validate_assignment": True }

class Channel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    fields: Dict[int, ChannelField] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    showcase: ShowcaseData = Field(default_factory=ShowcaseData) # Ensures it's never None
    api_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_entry_id: int = 0
    delete_secret: Optional[str] = None
    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
        "json_encoders": { datetime: lambda dt: dt.isoformat() },
        "validate_assignment": True,
    }

class ChannelCreate(BaseModel):
    name: str
    description: Optional[str] = None
    field_names: List[str] = Field(default_factory=list)

class ChannelMetadataUpdate(BaseModel):
    team_name: Optional[str] = None
    logo_url: Optional[str] = None # Allow string URL

# --- In-memory database and persistence ---
channels_db: Dict[str, Channel] = {}
data_points_db: Dict[str, Dict[int, List[Dict[str, Any]]]] = {}

CHANNELS_FILE = DATA_DIR / "channels.json"
DATA_POINTS_FILE = DATA_DIR / "data_points.json"
MAX_DATA_POINTS_PER_FIELD = 100

# --- Persistence Functions ---
def save_data_to_file():
    """Saves current channels and data points to JSON files."""
    try:
        channels_serializable = {k: v.model_dump(mode='json') for k, v in channels_db.items()}
        with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(channels_serializable, f, indent=2, ensure_ascii=False)
    except Exception as e: print(f"Error saving channels: {e}")
    try:
        dp_serializable = {cid: {str(fid): data for fid, data in f_data.items()} for cid, f_data in data_points_db.items()}
        with open(DATA_POINTS_FILE, "w", encoding="utf-8") as f:
            json.dump(dp_serializable, f, indent=2, ensure_ascii=False)
    except Exception as e: print(f"Error saving data points: {e}")

def load_data_from_file():
    global channels_db, data_points_db
    print("--- Attempting to load data ---")
    channels_db = {}; data_points_db = {}
    if CHANNELS_FILE.exists():
        try:
            print(f"Loading channels from: {CHANNELS_FILE}")
            with open(CHANNELS_FILE, "r", encoding="utf-8") as f: channels_json = json.load(f)
            temp_channels = {}
            for k, v_dict in channels_json.items():
                try:
                    loaded_fields = { int(f_id): ChannelField(**f_data) for f_id, f_data in v_dict.get("fields", {}).items() if isinstance(f_data, dict) }
                    v_dict["fields"] = loaded_fields
                    v_dict["metadata"] = v_dict.get("metadata", {}) if isinstance(v_dict.get("metadata"), dict) else {}
                    # Showcase loading: Let Pydantic handle creation with defaults if missing/invalid
                    showcase_data = v_dict.get("showcase")
                    if not isinstance(showcase_data, dict):
                        v_dict.pop("showcase", None) # Remove invalid data
                        print(f"  Info: Resetting invalid showcase data for channel {k}")
                    # Appearance loading: Let Pydantic handle creation within ShowcaseData
                    if isinstance(showcase_data, dict) and "appearance" in showcase_data and not isinstance(showcase_data.get("appearance"), dict):
                        showcase_data.pop("appearance", None) # Remove invalid appearance data
                        print(f"  Info: Resetting invalid showcase appearance data for channel {k}")

                    temp_channels[k] = Channel(**v_dict)
                except Exception as e: print(f"  ERROR Parsing channel {k}: {e}. Skipping."); import traceback; traceback.print_exc(); continue
            channels_db = temp_channels
            print(f"Finished loading channels. Loaded: {len(channels_db)}")
        except Exception as e: print(f"Error loading channels file: {e}. Starting fresh.")
    else: print(f"{CHANNELS_FILE} not found. Starting fresh.")
    if DATA_POINTS_FILE.exists():
        try:
            print(f"Loading data points from: {DATA_POINTS_FILE}")
            with open(DATA_POINTS_FILE, "r", encoding="utf-8") as f: dp_json = json.load(f)
            data_points_db = {cid: {int(fid): data for fid, data in f_data.items() if isinstance(data, list)} for cid, f_data in dp_json.items() if isinstance(f_data, dict)}
            print(f"Finished loading data points. Channels: {len(data_points_db)}")
        except Exception as e: print(f"Error loading data points: {e}. Starting fresh.")
    else: print(f"{DATA_POINTS_FILE} not found. Starting fresh.")
    print("--- Data loading finished ---")

# --- File Handling Helpers ---
def save_uploaded_file(upload_file: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("wb") as buffer: shutil.copyfileobj(upload_file.file, buffer)
    except Exception as e:
        print(f"Error saving file to {destination}: {e}")
        raise # Re-raise after logging
    finally: upload_file.file.close()

def generate_safe_filename(channel_id: str, original_filename: str) -> str:
    original_filename = Path(original_filename).name # Sanitize: use only filename part
    extension = Path(original_filename).suffix.lower()
    allowed_img_ext = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']
    allowed_doc_ext = ['.pdf', '.ppt', '.pptx']
    if extension not in allowed_img_ext + allowed_doc_ext: raise ValueError(f"Unsupported file type: {extension}")
    # Limit filename length before adding UUID if necessary
    base_name = Path(original_filename).stem[:50] # Limit base name length
    return f"{channel_id}_{base_name}_{uuid.uuid4().hex[:8]}{extension}" # Shorter UUID part

def remove_file_if_exists(relative_url_path: Optional[str]):
    if not relative_url_path or not relative_url_path.startswith(f"/{STATIC_DIR.name}/{UPLOAD_DIR.name}/"): return
    try:
        # Construct filesystem path from URL path relative to project root
        file_path = Path(relative_url_path.lstrip('/')) # e.g., static/uploads/...
        if file_path.is_file():
            file_path.unlink()
            print(f"Deleted old file: {file_path}")
        else:
            print(f"Old file not found for deletion: {file_path}")
    except Exception as e: print(f"Error deleting file {relative_url_path}: {e}")

# --- Internal Helper to Update Channel Data ---
def _update_channel_data(channel: Channel, update_values: Dict[int, float]) -> bool:
    """Internal helper to update channel fields and store historical data."""
    if not channel or not isinstance(update_values, dict):
        print("Warning: _update_channel_data received invalid input.")
        return False

    timestamp = datetime.now().isoformat()
    updated = False

    # --- FIX: Get channel_id from the channel object ---
    channel_id = channel.id
    # --- END FIX ---

    # Now it's safe to use channel_id
    # Ensure base structure exists for the channel in data_points_db
    if channel_id not in data_points_db:
        print(f"Initializing data_points_db entry for channel {channel_id}")
        data_points_db[channel_id] = {}

    for field_id, value in update_values.items():
        # Check if field_id is valid for this channel
        if field_id in channel.fields:
            try:
                float_value = float(value)
                channel.fields[field_id].value = float_value
                channel.fields[field_id].last_updated = timestamp
                updated = True

                # Ensure field list exists in data_points_db[channel_id]
                if field_id not in data_points_db[channel_id]:
                    data_points_db[channel_id][field_id] = []

                # Store historical data point
                data_point = {"value": float_value, "timestamp": timestamp}
                data_points_db[channel_id][field_id].append(data_point)

                # Trim historical data
                data_points_db[channel_id][field_id] = data_points_db[channel_id][field_id][-MAX_DATA_POINTS_PER_FIELD:]

            except (ValueError, TypeError) as e:
                print(f"Warning: Could not process value '{value}' for field {field_id} in channel {channel_id}. Error: {e}")
                continue # Skip this field update
        else:
             print(f"Warning: Field ID {field_id} not found in channel {channel_id} fields during update.")


    if updated:
        channel.last_entry_id += 1
        save_data_to_file() # Save data after successful updates
        return True

    return False # Return False if no fields were actually updated

# --- Channel Creation (API Helper) ---
async def create_channel_api(channel_create: ChannelCreate) -> Channel: # ... (Keep implementation) ...
    channel_id = str(uuid.uuid4()); fields = {};
    for i, name in enumerate(channel_create.field_names[:8], 1): cleaned_name = name.strip();
    if cleaned_name: fields[i] = ChannelField(field_id=i, name=cleaned_name)
    new_channel = Channel( id=channel_id, name=channel_create.name.strip(), description=channel_create.description.strip() if channel_create.description else None, fields=fields, api_key=str(uuid.uuid4()) )
    channels_db[channel_id] = new_channel; data_points_db[channel_id] = {field_id: [] for field_id in fields.keys()}; save_data_to_file(); print(f"Channel created: {channel_id} ({new_channel.name})"); return new_channel

# --- Lifespan Context Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI): # ... (Keep implementation with sample data creation) ...
    print("--- Application Starting ---"); load_data_from_file()
    if not channels_db:
        print("No channels found, creating sample channel..."); sample_create = ChannelCreate( name="Greenhouse Monitor", description="Monitors conditions in the main greenhouse.", field_names=["Temperature (°C)", "Humidity (%)", "Soil Moisture", "Light Level (Lux)"] )
        try:
            sample_channel = await create_channel_api(sample_create)
            initial_data = {1: 24.8, 2: 62.5, 3: 75.0, 4: 15000.0}; _update_channel_data(sample_channel, initial_data)
            sample_channel.showcase = ShowcaseData( introduction="Monitoring system...", achievements=["Deployed", "Harvest!"], image_urls=["https://via.placeholder.com/400"], poster_image_url="/static/placeholder_poster.png", slides_link_external="https://example.com" )
            sample_channel.metadata = {"team_name": "Garden Tech", "logo_url": "/static/placeholder_logo.png"}
            save_data_to_file(); print(f"Sample channel {sample_channel.id} created and saved.")
        except Exception as e: print(f"Error creating sample channel: {e}")
    else: print(f"Startup complete. {len(channels_db)} channels available.")
    yield; print("--- Application Shutting Down ---")

# --- FastAPI App ---
app = FastAPI( title="IoT Analytics Platform", description="ThingSpeak-like API.", version="1.5.2", lifespan=lifespan )

# --- Static Files and Templates ---
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ===========================
# --- API Endpoints ---
# ===========================

# --- Pages ---
@app.get("/", response_class=HTMLResponse, tags=["Pages"])
async def home(request: Request): return templates.TemplateResponse("home.html", {"request": request})
@app.get("/channels", response_class=HTMLResponse, tags=["Pages"])
async def list_channels_page(request: Request): sorted_channels = sorted(channels_db.values(), key=lambda c: c.name); return templates.TemplateResponse("channels_list.html", {"request": request, "channels": sorted_channels})
@app.get("/create-channel", response_class=HTMLResponse, tags=["Pages"])
async def create_channel_form_page(request: Request): return templates.TemplateResponse("create_channel_form.html", {"request": request})
@app.get("/dashboard/{channel_id}", response_class=HTMLResponse, tags=["Pages"])
async def get_dashboard_page(request: Request, channel_id: str):
    if channel_id not in channels_db: return RedirectResponse(url="/channels?error=channel_not_found", status_code=307)
    channel = channels_db[channel_id]
    # Ensure nested objects exist for template rendering
    if channel.showcase is None: channel.showcase = ShowcaseData()
    if channel.metadata is None: channel.metadata = {}
    if channel.showcase.appearance is None: channel.showcase.appearance = ShowcaseAppearance()
    sorted_fields = dict(sorted(channel.fields.items())) if isinstance(channel.fields, dict) else {}
    # Prepare JSON strings safely
    js_fields_json_string = json.dumps({str(f_id): f.model_dump(mode='json') for f_id, f in sorted_fields.items()}, ensure_ascii=False) if sorted_fields else "{}"
    js_showcase_json_string = json.dumps(channel.showcase.model_dump(mode='json'), ensure_ascii=False)
    context = {"request": request, "channel": channel, "sorted_fields": sorted_fields, "js_fields_json": js_fields_json_string, "js_showcase_json": js_showcase_json_string }
    try: return templates.TemplateResponse("dashboard.html", context)
    except Exception as e: print(f"!!!!! ERROR RENDERING DASHBOARD: {e} !!!!!"); import traceback; traceback.print_exc(); raise HTTPException(status_code=500, detail="Error rendering dashboard.")

# --- Channel Actions ---
@app.post("/channels", status_code=303, tags=["Channel Actions"])
async def create_channel_submit(request: Request): # ... (Keep implementation) ...
    form_data = await request.form(); name = form_data.get("name"); 
    if not name or not name.strip(): 
        return templates.TemplateResponse("create_channel_form.html", {"request": request, "error": "Channel Name required."}, status_code=400); desc = form_data.get("description", ""); 
    f_names = [f.strip() for f in form_data.getlist("field_names") if f and f.strip()]
    c_create = ChannelCreate(name=name.strip(), description=desc.strip() if desc else None, field_names=f_names)
    try: 
        n_ch = await create_channel_api(c_create)
        return RedirectResponse(url=f"/dashboard/{n_ch.id}", status_code=303)
    except Exception as e: print(f"Error form create: {e}"); return templates.TemplateResponse("create_channel_form.html", {"request": request, "error": "Unexpected error."}, status_code=500)

@app.post("/dashboard/{channel_id}/send_data", response_model=Dict[str, Any], tags=["Dashboard Actions"])
async def send_data_from_dashboard_api(request: Request, channel_id: str):
    """Handles the 'Send Custom Data' form submission via Fetch API."""
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel = channels_db[channel_id]
    form_data = await request.form()
    print(f"API Form data for {channel_id}: {form_data}")

    values_to_update: Dict[int, float] = {}
    has_error = False
    err_detail = ""
    err_fld_name = None # Use a more descriptive variable name

    # Iterate through fields DEFINED in the channel
    for f_id, f_obj in channel.fields.items():
        form_field_key = f"field{f_id}" # e.g., field1, field2

        # --- FIX: Indentation for the check and try/except ---
        if form_field_key in form_data and form_data[form_field_key]:
            value_str = form_data[form_field_key]
            try:
                # Attempt to convert the value to float
                values_to_update[f_id] = float(value_str)
                print(f"  Parsed {form_field_key}: {values_to_update[f_id]}")
            except (ValueError, TypeError):
                # If conversion fails, record the error and stop processing
                has_error = True
                err_fld_name = f_obj.name # Get the field's actual name for the error message
                err_detail = f"Invalid numeric value provided for field '{err_fld_name}'."
                print(f"Submit Error: {err_detail} Value received: '{value_str}'")
                break # Exit the loop on the first error

    # --- FIX: These checks happen AFTER the loop ---
    if has_error:
        # If an error occurred during the loop, raise HTTP 400
        raise HTTPException(status_code=400, detail=err_detail)

    if not values_to_update:
        # If the loop finished without errors but no valid data was found
        raise HTTPException(status_code=400, detail="No valid data submitted for existing fields.")

    # If we reach here, data is valid, attempt to update
    print(f"API Attempting to update {channel_id} with: {values_to_update}")
    updated = _update_channel_data(channel, values_to_update)

    if updated:
        print("API Update successful.")
        return JSONResponse(
            content={"success": True, "entry_id": channel.last_entry_id, "message": "Data sent successfully."},
            status_code=200
        )
    else:
        # This would indicate an internal issue in _update_channel_data
        print("API Update failed unexpectedly in _update_channel_data.")
        raise HTTPException(status_code=500, detail="Server error during data update.")

@app.put("/channels/{channel_id}/metadata", response_model=Channel, tags=["Channel Actions"])
async def update_channel_metadata(channel_id: str, metadata_update: ChannelMetadataUpdate):
    """Updates the metadata (team name, logo) for a channel."""
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")

    # --- FIX: Ensure channel is assigned BEFORE accessing its attributes ---
    channel = channels_db[channel_id]

    # Safety check (though unlikely if previous check passed)
    if channel is None:
         print(f"ERROR: Channel data for {channel_id} is unexpectedly None.")
         raise HTTPException(status_code=500, detail="Internal server error: Inconsistent channel data.")

    # --- FIX: Decompress and correct initialization logic ---
    # Ensure channel.metadata is a dictionary *before* trying to modify it
    if channel.metadata is None:
        print(f"Initializing metadata for channel {channel_id} as it was None.")
        channel.metadata = {}

    updated = False # Initialize updated flag here

    # Now modify the dictionary which is guaranteed to exist
    if metadata_update.team_name is not None:
        # Add validation if needed (e.g., length)
        channel.metadata["team_name"] = metadata_update.team_name.strip()
        updated = True
        print(f"  Updated team_name for {channel_id}")

    if metadata_update.logo_url is not None:
        # Add URL validation if needed
        channel.metadata["logo_url"] = str(metadata_update.logo_url).strip()
        updated = True
        print(f"  Updated logo_url for {channel_id}")
    # --- END FIX ---

    if updated:
        save_data_to_file() # Save changes
        print(f"Metadata successfully updated and saved for channel {channel_id}: {channel.metadata}")
    else:
         print(f"No metadata changes provided for channel {channel_id}")

    return channel # Return the full channel object
@app.put("/channels/{channel_id}/showcase", response_model=ShowcaseData, tags=["Showcase Actions"])
async def update_showcase(
    channel_id: str,
    showcase_data_json: str = Form(..., alias="showcase_data"),
    poster_image_file: Optional[UploadFile] = File(None, alias="poster_image_file"),
    slides_file: Optional[UploadFile] = File(None, alias="slides_file"),
    background_image_file: Optional[UploadFile] = File(None, alias="background_image_file")
):
    if channel_id not in channels_db: raise HTTPException(404, "Channel not found")
    channel = channels_db[channel_id]
    if channel.showcase is None: channel.showcase = ShowcaseData()
    if channel.showcase.appearance is None: channel.showcase.appearance = ShowcaseAppearance()

    # 1. Parse JSON data
    try:
        data_dict = json.loads(showcase_data_json)
        # Validate and update non-file text/list fields
        channel.showcase.introduction = data_dict.get("introduction", channel.showcase.introduction)
        channel.showcase.achievements = data_dict.get("achievements", channel.showcase.achievements)
        channel.showcase.image_urls = data_dict.get("image_urls", channel.showcase.image_urls)
        channel.showcase.youtube_links = data_dict.get("youtube_links", channel.showcase.youtube_links)
        channel.showcase.slides_link_external = data_dict.get("slides_link_external", channel.showcase.slides_link_external)

        # Update appearance from JSON
        appearance_data = data_dict.get("appearance")
        if isinstance(appearance_data, dict):
            app = channel.showcase.appearance
            app.bg_color = appearance_data.get("bg_color", app.bg_color)
            app.section_bg_color = appearance_data.get("section_bg_color", app.section_bg_color)
            app.accent_color = appearance_data.get("accent_color", app.accent_color)
            # BG Image URL from JSON is handled below ONLY if no file is uploaded

    except json.JSONDecodeError: raise HTTPException(400, "Invalid JSON in 'showcase_data'.")
    except Exception as e: raise HTTPException(400, f"Error processing showcase JSON: {e}")

    # 2. Define upload directory & base URL
    upload_base_url = f"/{STATIC_DIR.name}/{UPLOAD_DIR.name}" # e.g., /static/uploads
    channel_upload_dir = UPLOAD_DIR / "showcase" / channel_id
    allowed_image_types = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"]
    allowed_slides_types = ["application/pdf", "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"]

    # 3. Handle Poster Upload
    if poster_image_file and poster_image_file.filename:
        if poster_image_file.content_type not in allowed_image_types: raise HTTPException(400, "Poster must be image.")
        remove_file_if_exists(channel.showcase.poster_image_url)
        try: filename=generate_safe_filename(channel_id,poster_image_file.filename); dest=channel_upload_dir/"poster"/filename; save_uploaded_file(poster_image_file,dest); channel.showcase.poster_image_url=f"{upload_base_url}/showcase/{channel_id}/poster/{filename}"; channel.showcase.poster_filename=poster_image_file.filename; print(f"Saved poster: {dest}")
        except Exception as e: raise HTTPException(500, f"Save poster failed: {e}")

    # 4. Handle Slides Upload
    if slides_file and slides_file.filename:
        if slides_file.content_type not in allowed_slides_types: raise HTTPException(400, "Slides must be PDF/PPT/PPTX.")
        remove_file_if_exists(channel.showcase.slides_url)
        try: filename=generate_safe_filename(channel_id,slides_file.filename); dest=channel_upload_dir/"slides"/filename; save_uploaded_file(slides_file,dest); channel.showcase.slides_url=f"{upload_base_url}/showcase/{channel_id}/slides/{filename}"; channel.showcase.slides_filename=slides_file.filename; print(f"Saved slides: {dest}")
        except Exception as e: raise HTTPException(500, f"Save slides failed: {e}")

    # 5. Handle Background Upload
    if background_image_file and background_image_file.filename:
        if background_image_file.content_type not in allowed_image_types: raise HTTPException(400, "Background must be image.")
        remove_file_if_exists(channel.showcase.appearance.background_image_url)
        try: filename=generate_safe_filename(channel_id,background_image_file.filename); dest=channel_upload_dir/"background"/filename; save_uploaded_file(background_image_file,dest); channel.showcase.appearance.background_image_url=f"{upload_base_url}/showcase/{channel_id}/background/{filename}"; print(f"Saved background: {dest}")
        except Exception as e: raise HTTPException(500, f"Save background failed: {e}")
    # Use JSON url only if no file was uploaded and it was present in JSON
    elif isinstance(appearance_data, dict) and "background_image_url" in appearance_data and not background_image_file:
         channel.showcase.appearance.background_image_url = appearance_data.get("background_image_url", channel.showcase.appearance.background_image_url)


    save_data_to_file()
    return channel.showcase # Return updated data

# --- API Data/Info Endpoints ---
@app.post("/channels/api", response_model=Channel, status_code=201, tags=["API - Channels"])
async def create_channel_api_route(channel_data: ChannelCreate): # ... (Keep implementation) ...
    try: return await create_channel_api(channel_data)
    except Exception as e: print(f"API create error: {e}"); raise HTTPException(500,"Internal error.")

@app.get("/channels/{channel_id}", response_model=Channel, tags=["API - Channels"])
async def get_channel_info_api(channel_id: str):
    """API endpoint to get detailed information about a specific channel."""
    if channel_id not in channels_db:
        # This is the correct way to handle not found
        raise HTTPException(status_code=404, detail="Channel not found")

    # Accessing with [] assumes the key exists because of the check above
    channel = channels_db[channel_id]

    # --- Ensure channel object itself isn't None (safety check) ---
    if channel is None:
         print(f"ERROR: Found key {channel_id} in channels_db but the value is None!")
         # This indicates a deeper data corruption issue if it ever happens
         raise HTTPException(status_code=500, detail="Internal server error: Channel data is inconsistent.")
    # --- End safety check ---

    # Return the valid Channel object
    return channel

@app.get("/update", response_model=Dict[str, Any], status_code=200, tags=["API - Data Update"])
async def update_fields_get(
    request: Request,
    channel_id: str,
    api_key: str
):
    """
    Updates channel fields using GET request query parameters.
    Example: /update?channel_id=YOUR_ID&api_key=YOUR_KEY&field1=25.5&field2=60
    Returns JSON with success status and entry_id on success.
    Raises HTTPException on errors (like invalid channel/key).
    Returns specific JSON error if no valid data sent.
    """
    print(f"Received GET /update for channel: {channel_id}")

    # 1. Validate Channel ID
    if channel_id not in channels_db:
        print(f"  Error: Channel {channel_id} not found.")
        # Raise standard HTTP error for not found
        raise HTTPException(status_code=404, detail="Channel not found")

    channel = channels_db[channel_id]
    if channel is None: # Safety check
        print(f"  ERROR: Channel object for {channel_id} is None in db!")
        raise HTTPException(status_code=500, detail="Internal server error: Inconsistent channel data")

    # 2. Validate API Key
    if channel.api_key != api_key:
        print(f"  Error: Invalid API key provided for channel {channel_id}.")
         # Raise standard HTTP error for unauthorized/forbidden
        raise HTTPException(status_code=401, detail="Invalid API key") # 401 Unauthorized is typical

    # 3. Parse field values
    field_values_to_update: Dict[int, float] = {}
    print(f"  Parsing query params: {request.query_params}")
    for i in range(1, 9):
        field_key = f"field{i}"
        if field_key in request.query_params:
            value_str = request.query_params[field_key]
            if i in channel.fields:
                try:
                    value_float = float(value_str)
                    field_values_to_update[i] = value_float
                except (ValueError, TypeError):
                    print(f"      Warning: Invalid value '{value_str}' for {field_key}. Ignoring field.")
                    # Optionally raise 400 if you want strict validation
                    # raise HTTPException(status_code=400, detail=f"Invalid numeric value for {field_key}")
            else:
                 print(f"      Warning: Field {i} provided but does not exist in channel {channel_id}. Ignoring.")

    # 4. Check if any valid data was found
    if not field_values_to_update:
         print(f"  No valid field data parsed for existing fields in channel {channel_id}.")
         # --- FIX: Return JSON error for this specific case ---
         # Use status 400 Bad Request
         return JSONResponse(
             status_code=400,
             content={"success": False, "error": "No valid field data provided for existing fields."}
         )

    # 5. Attempt to update data
    print(f"  Attempting update with values: {field_values_to_update}")
    try:
        updated = _update_channel_data(channel, field_values_to_update)
    except Exception as e:
        print(f"  ERROR during _update_channel_data call: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal error during data update.")

    # 6. Return result
    if updated:
        entry_id = channel.last_entry_id
        print(f"  Update GET successful. New entry ID: {entry_id}")
        # --- FIX: Return JSON success response ---
        return JSONResponse(
            content={"success": True, "entry_id": entry_id, "message": "Data updated successfully."},
            status_code=200 # Explicitly set 200 OK
        )
    else:
        # This case (update ran but returned False) is less common, but return error
        print(f"  Update GET: _update_channel_data returned False for {channel_id}.")
        # --- FIX: Return JSON error ---
        # Maybe 500 is better here? Or 400 if it implies bad input somehow? Let's use 500.
        raise HTTPException(status_code=500, detail="Data update failed unexpectedly on server.")

@app.put("/channels/{channel_id}/gallery/images", response_model=List[str], tags=["Showcase Actions"])
async def upload_gallery_images(
    channel_id: str,
    api_key: str = Query(..., description="The Write API Key for the channel."),
    gallery_files: List[UploadFile] = File(..., alias="gallery_images", description="List of image files for the showcase gallery.")
):
    """
    Uploads multiple images for the showcase gallery, replacing any existing gallery images.
    Requires the channel's Write API Key.
    """
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel = channels_db[channel_id]

    # Check API Key
    if channel.api_key != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Ensure showcase object exists
    if channel.showcase is None:
        channel.showcase = ShowcaseData()
    # No need to check appearance here as we only modify image_urls

    print(f"Received {len(gallery_files)} files for gallery upload for channel {channel_id}")

    # --- Logic to replace gallery ---
    # 1. Clear existing files and URLs
    clear_gallery_files(channel_id, channel.showcase) # This also sets channel.showcase.image_urls = []

    # 2. Process new files
    new_gallery_urls: List[str] = []
    upload_base_url = f"/{STATIC_DIR.name}/{UPLOAD_DIR.name}"
    channel_upload_dir = UPLOAD_DIR / "showcase" / channel_id
    gallery_dir = channel_upload_dir / "gallery"
    allowed_image_types = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"]

    for file in gallery_files:
        if file.filename: # Check if a file was actually uploaded
            print(f"Processing gallery file: {file.filename}, type: {file.content_type}")
            if file.content_type not in allowed_image_types:
                print(f"Warning: Skipping invalid gallery file type: {file.filename}")
                continue # Skip this file
            try:
                safe_filename = generate_safe_filename(channel_id, file.filename)
                destination = gallery_dir / safe_filename
                save_uploaded_file(file, destination) # Saves the file
                new_url = f"{upload_base_url}/showcase/{channel_id}/gallery/{safe_filename}"
                new_gallery_urls.append(new_url)
            except ValueError as val_err: # Catch error from generate_safe_filename (e.g., bad extension)
                 print(f"Warning: Skipping file '{file.filename}' due to validation error: {val_err}")
            except Exception as e:
                # Log error but try to continue with other files
                print(f"Warning: Failed to save gallery image '{file.filename}': {e}")
        else:
            print("Skipping empty file upload in gallery list.")

    # 3. Update the showcase data with the list of successfully saved URLs
    channel.showcase.image_urls = new_gallery_urls
    print(f"Updated gallery for channel {channel_id} with {len(new_gallery_urls)} images.")

    # 4. Save the overall channel data
    save_data_to_file()

    # 5. Return the new list of URLs
    return channel.showcase.image_urls

@app.post("/update_multiple", response_model=Dict[str, Any], tags=["API - Data Update"])
async def update_multiple_fields_post(
    request: Request,
    channel_id_form: Optional[str] = Form(None, alias="channel_id"),
    api_key_form: Optional[str] = Form(None, alias="api_key")
):
    """
    Updates multiple fields using POST. Accepts form data or JSON.
    JSON needs 'channel_id', 'api_key'. Fields can be top-level 'fieldX' or nested in 'field_values'.
    Form data needs 'channel_id', 'api_key', and 'fieldX'.
    """
    content_type = request.headers.get("content-type", "").lower()
    f_vals: Dict[str, Any] = {} # Store potential field values (key is string field number '1', '2', etc.)
    ch_id: Optional[str] = None
    api_key: Optional[str] = None

    if "application/json" in content_type:
        print("Processing POST update as JSON")
        try:
            p = await request.json()
            if not isinstance(p, dict): raise HTTPException(400,"Invalid JSON payload: Expected an object.")

            ch_id = p.get("channel_id")
            api_key = p.get("api_key")
            if not ch_id: raise HTTPException(400, "Missing 'channel_id' in JSON payload")
            if not api_key: raise HTTPException(400, "Missing 'api_key' in JSON payload")

            # Check for nested 'field_values' first, fallback to top-level payload
            raw_values = p.get("field_values", p)
            if not isinstance(raw_values, dict):
                # Only error if 'field_values' explicitly provided but not a dict
                if "field_values" in p: raise HTTPException(400, "Invalid JSON: 'field_values' must be an object.")
                # If 'field_values' wasn't provided, raw_values is 'p' itself, which we know is a dict.

            # Extract field data
            for k, v in raw_values.items():
                if k.startswith("field") and k[5:].isdigit():
                    f_vals[k[5:]] = v  # Store key as '1', '2' etc.
                elif k.isdigit():
                    f_vals[k] = v
                # Silently ignore other keys like channel_id, api_key if present in raw_values

        # --- FIX: Indentation for except block ---
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON payload.")
        except HTTPException as http_exc: # Re-raise specific HTTP exceptions
            raise http_exc
        except Exception as e:
            print(f"Error processing JSON body: {e}") # Log the error
            raise HTTPException(400, f"Could not process JSON payload: {e}")

    else: # Assume form data
        print("Processing POST update as Form Data")
        ch_id = channel_id_form
        api_key = api_key_form
        if not ch_id: raise HTTPException(400, "Missing 'channel_id' form field")
        if not api_key: raise HTTPException(400, "Missing 'api_key' form field")

        form_data = await request.form()
        for i in range(1, 9):
            k = f"field{i}"
            if k in form_data:
                f_vals[str(i)] = form_data[k] # Store key as '1', '2' etc.

    # --- Validation (Channel ID and API Key) ---
    if not ch_id or ch_id not in channels_db:
        raise HTTPException(404, "Channel not found")
    channel = channels_db[ch_id]
    if not api_key or channel.api_key != api_key:
        raise HTTPException(401, "Invalid API key")

    # --- Process Field Values ---
    num_vals: Dict[int, float] = {}
    for id_s, v in f_vals.items():
        if id_s.isdigit():
            id_i = int(id_s)
            # Check if field ID is valid for *this* channel
            if 1 <= id_i <= 8 and id_i in channel.fields:
                try:
                    num_vals[id_i] = float(v)
                except (ValueError, TypeError): # Catch specific errors
                    print(f"Warn POST: Bad value '{v}' for field {id_i}")
                    # Optional: Raise HTTP 400 here if you want strict validation
                    # raise HTTPException(400, f"Invalid numeric value provided for field {id_i}")
            # --- FIX: Corrected logic for warning ---
            else:
                 # Only print warning if the key wasn't handled above AND isn't a standard ignored key
                 if id_s not in ["channel_id", "api_key", "field_values"]: # Check if it was a valid field ID for *this* channel
                     print(f"Warn POST: Invalid or non-existent field ID '{id_s}' for channel {ch_id}")
        elif id_s not in ["channel_id", "api_key", "field_values"]: # Ignore specific keys
             print(f"Warn POST: Ignoring non-numeric key '{id_s}'")


    if not num_vals:
        raise HTTPException(400, "No valid field data provided for existing fields")

    # --- Update Data ---
    updated = _update_channel_data(channel, num_vals)
    if updated:
        return {"success": True, "entry_id": channel.last_entry_id}
    else:
        # This *shouldn't* happen if num_vals had items, indicates internal issue
        print(f"Error: _update_channel_data returned False unexpectedly for channel {ch_id} with data {num_vals}")
        raise HTTPException(500, "Update failed unexpectedly on server")@app.get("/channels/{channel_id}/fields/{field_id}", response_model=ChannelField, tags=["API - Data Retrieval"])
    
async def get_field_info_api(channel_id: str, field_id: int): # ... (Keep implementation) ...
     if channel_id not in channels_db: raise HTTPException(404,"Ch not found"); channel=channels_db[channel_id]; 
     if field_id not in channel.fields: raise HTTPException(404,f"Field {field_id} not found"); return channel.fields[field_id]
@app.get("/channels/{channel_id}/fields/{field_id}/data", response_model=List[Dict[str, Any]], tags=["API - Data Retrieval"])
async def get_field_historical_data(channel_id: str, field_id: int, results: int = 50):
    """API endpoint to get historical data points for a specific field."""
    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Validate results count
    results = min(max(1, results), MAX_DATA_POINTS_PER_FIELD)

    # Check if channel or specific field data exists in the data points DB
    channel_data = data_points_db.get(channel_id)
    if channel_data is None or field_id not in channel_data:
        # --- FIX: Ensure this returns an empty list ---
        print(f"No historical data found for ch:{channel_id} field:{field_id}. Returning empty list.")
        return []
        # --- END FIX ---

    # Get the stored data points for the field, defaulting to empty list if key somehow disappears
    field_data_list = channel_data.get(field_id, [])

    # Return the last 'results' number of data points
    return field_data_list[-results:]# --- Showcase Page & QR ---
@app.get("/showcase/{channel_id}", response_class=HTMLResponse, tags=["Showcase"])
async def get_showcase_page(request: Request, channel_id: str):
    """Serves the public showcase page for a channel."""

    if channel_id not in channels_db:
        # Consider rendering a simple "Not Found" page instead of raising HTTPException
        # return templates.TemplateResponse("404_showcase.html", {"request": request, "channel_id": channel_id}, status_code=404)
        raise HTTPException(status_code=404, detail="Showcase page not found for this channel.")

    channel = channels_db[channel_id]

    # Ensure nested objects are correctly initialized (handle None cases)
    # Use the default factory behavior by checking for None
    metadata = channel.metadata if channel.metadata is not None else {}
    showcase = channel.showcase if channel.showcase is not None else ShowcaseData() # Get default if None
    # Ensure appearance within showcase is also initialized
    if showcase.appearance is None:
        showcase.appearance = ShowcaseAppearance() # Get default if None

    fields = channel.fields if isinstance(channel.fields, dict) else {}
    sorted_live_fields = dict(sorted(fields.items()))

    # Prepare context for the template
    context = {
        "request": request,
        "channel_name": channel.name,
        "channel_description": channel.description,
        "showcase": showcase, # Pass the potentially initialized ShowcaseData object
        "metadata": metadata, # Pass the potentially initialized metadata dict
        "channel_id": channel.id,
        "current_year": datetime.now().year,
        "live_fields": sorted_live_fields
    }

    # Check if the template file exists
    template_path = TEMPLATES_DIR / "showcase.html"
    if not template_path.exists():
        print(f"ERROR: Template file not found at {template_path}")
        raise HTTPException(status_code=500, detail="Showcase template file is missing on the server.")

    # Render the template
    try:
        return templates.TemplateResponse("showcase.html", context)
    except Exception as e:
        print(f"!!!!! ERROR RENDERING SHOWCASE TEMPLATE for {channel_id}: {e} !!!!!")
        import traceback
        traceback.print_exc()
        # Return a generic error page or raise an exception
        raise HTTPException(status_code=500, detail="Error rendering showcase page.")
    
@app.get("/channels/{channel_id}/showcase/qr", tags=["Showcase"])
async def get_showcase_qr_code(request: Request, channel_id: str):
    """Generates and returns a QR code image for the channel's public showcase page."""

    if not QRCODE_INSTALLED:
        print("QR Code generation requested but libraries not installed.")
        raise HTTPException(status_code=501, detail="QR code generation library not installed on server.")

    if channel_id not in channels_db:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Construct the public URL
    # Prioritize X-Forwarded headers if behind a proxy
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    # Ensure host doesn't include port if standard ports are used with headers
    if (scheme == "https" and host.endswith(":443")) or \
       (scheme == "http" and host.endswith(":80")):
        host = host.rsplit(":", 1)[0]

    showcase_url = f"{scheme}://{host}/showcase/{channel_id}"
    print(f"Generating QR code for URL: {showcase_url}")

    try:
        # Configure QR code generation
        qr = qrcode.QRCode(
            version=1, # Auto version detection is usually fine too
            error_correction=qrcode.constants.ERROR_CORRECT_L, # L = Low (7%), M, Q, H
            box_size=10, # Size of each "box" in pixels
            border=4,    # Thickness of the border (quiet zone)
        )
        qr.add_data(showcase_url)
        qr.make(fit=True) # Optimize the QR code size

        # Create the image using Pillow
        img = qr.make_image(fill_color="black", back_color="white")

        # Save image to a bytes buffer
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0) # Rewind buffer to the beginning

        # Return the image data as a response
        return Response(content=img_byte_arr.getvalue(), media_type="image/png")

    except Exception as e:
        print(f"Error during QR code generation for {channel_id}: {e}")
        import traceback
        traceback.print_exc() # Log full traceback for debugging
        raise HTTPException(status_code=500, detail="Could not generate QR code due to an internal error.")
    
# --- Health Check ---
@app.get("/health", tags=["System"])
async def health_check(): return {"status": "healthy", "timestamp": datetime.now().isoformat(), "version": app.version, "channels_count": len(channels_db), "data_points_keys_count": len(data_points_db), "qrcode_installed": QRCODE_INSTALLED }

# --- Template File Checks ---
required_templates = ["home.html", "channels_list.html", "create_channel_form.html", "dashboard.html", "showcase.html"]
for template_name in required_templates:
    if not (TEMPLATES_DIR / template_name).exists(): print(f"WARNING: Template 'templates/{template_name}' not found!")

# --- Run the application ---
if __name__ == "__main__":
    import uvicorn
    print("--- Starting FastAPI Server ---")
    print(f"Version: {app.version}"); print(f"Data dir: {DATA_DIR.resolve()}"); print(f"Static dir: {STATIC_DIR.resolve()}"); print(f"Uploads dir: {UPLOAD_DIR.resolve()}"); print(f"Templates dir: {TEMPLATES_DIR.resolve()}"); print(f"QR Code Enabled: {QRCODE_INSTALLED}"); print("Access: http://127.0.0.1:8000"); uvicorn.run("m5:app", host="0.0.0.0", port=8000, reload=True)