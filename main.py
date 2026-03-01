from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
import shutil
import tempfile
import os
import room_location
import target_position
import supabase
from supabase import create_client, Client

app = FastAPI()
SUPABASE_URL = "https://upsqvxtvlvxyuimngxil.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVwc3F2eHR2bHZ4eXVpbW5neGlsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzMDQ4NDUsImV4cCI6MjA4Nzg4MDg0NX0.rAiok4qC1RM88Iq5of_jsBgFcD7sQ6JCMBgCvDomPY4"


@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: Optional[str] = None):
    return {"item_id": item_id, "q": q}

@app.post("/api/upload-png")
async def upload_image(file: UploadFile = File(...)):
    # 1. Validate that it is actually a PNG
    if file.content_type != "image/png":
        raise HTTPException(status_code=400, detail="Only PNG images are allowed")

    # 2. Create a temporary file with same name but in the system's temp directory
    # 'delete=True' (default) ensures it vanishes when the file object is closed
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_file_path = os.path.join(temp_dir, file.filename)
        with open(custom_file_path, 'wb') as tmp:
            try:
                # 3. Stream the uploaded content into the temp file
                shutil.copyfileobj(file.file, tmp)
                
                # Move pointer to the start of the file if you need to read it immediately
                tmp.seek(0)
                
                # --- YOUR LOGIC HERE ---
                # Example: Get the path to pass to EasyOCR or OpenCV
                temp_path = tmp.name
                print(f"File temporarily saved at: {temp_path}")
                
                # Perform your processing (e.g., OCR, Image manipulation)
                result = room_location.map_room_numbers(temp_path)

                # insert result into Supabase database called "room_locations" with columns "id", "image", "room_number", "x", "y"
                for room_id, (x, y) in result.items():
                    # Assuming you have a Supabase client set up
                    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

                    supabase_client.table("room_locations").insert({"id": f"{os.path.basename(temp_path)}_{room_id}", "image": os.path.basename(temp_path), "room_number": room_id, "x": x, "y": y}).execute()
                    print(f"Inserting into DB: {os.path.basename(temp_path)}, {room_id}, {x}, {y}")

                
                target_position.template_match(temp_path)

                with open(temp_path, "rb") as f:
                    response = (
                        supabase.storage
                        .from_("avatars")
                        .upload(
                            file=f,
                            path=f"{os.path.basename(temp_path)}",
                            file_options={"cache-control": "3600", "upsert": "false"}
                        )
                    )
                
                return {"message": "Success", "temp_file": temp_path, "room_map": result, "target_position": "Success"}

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
            finally:
                # FastAPI's UploadFile also needs to be closed
                file.file.close()

# The file is now deleted because the 'with' block has ended