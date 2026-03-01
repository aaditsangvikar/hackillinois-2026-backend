from typing import Optional
from fastapi import FastAPI, Response, UploadFile, File, HTTPException
import shutil
import tempfile
import os
import room_location
import target_position
import hallway4
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
                        supabase_client.storage
                        .from_("floorplans")
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

@app.get("/api/calculate_route")
def calculate_route(building: str, floor: str, curr_room: str, target_room: str, bathroom: bool = False, water_fountain: bool = False):
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Verify the building and floor exist in the database
    building_floor_check = supabase_client.table("room_locations").select("image").eq("image", f"{building}_{floor}.png").execute()
    if not building_floor_check.data:
        raise HTTPException(status_code=404, detail="Building or floor not found")
    
    # calculate current room location
    curr_room_check = supabase_client.table("room_locations").select("x", "y").eq("image", f"{building}_{floor}.png").eq("room_number", curr_room).execute()
    if not curr_room_check.data:
        raise HTTPException(status_code=404, detail="Current room not found")
    
    # pull image from Supabase storage
    image_response = supabase_client.storage.from_("floorplans").download(f"{building}_{floor}.png")
    if not image_response:
        raise HTTPException(status_code=404, detail="Floorplan image not found in storage")
    
    # temporarily save the image to disk for processing
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(image_response)
        temp_image_path = tmp.name
    
    # If bathroom is requested, find the nearest bathroom to the current room
    if bathroom:
        
        # find the nearest bathroom to the current room
        curr_x = curr_room_check.data[0]["x"]
        curr_y = curr_room_check.data[0]["y"]

        # Get all bathroom locations for this building/floor
        bathroom_locations = supabase_client.table("ticker_locations").select("x", "y", "ticker").eq("image", f"{building}_{floor}.png").in_("ticker", ["male.png", "female.png", "neutral.png"]).execute()

        if not bathroom_locations.data:
            raise HTTPException(status_code=404, detail="No bathrooms found in this building/floor")

        # Find the nearest bathroom
        nearest_bathroom = None
        min_distance = float('inf')

        for bathroom in bathroom_locations.data:
            distance = ((bathroom["x"] - curr_x) ** 2 + (bathroom["y"] - curr_y) ** 2) ** 0.5
            if distance < min_distance:
                min_distance = distance
                nearest_bathroom = bathroom

        # calculate path using hallway4.py
        path_image = hallway4.find_floorplan_path(temp_image_path, (curr_room_check.data[0]["x"], curr_room_check.data[0]["y"]), (nearest_bathroom["x"], nearest_bathroom["y"]))

        if path_image is None:
            raise HTTPException(status_code=404, detail="No path found to the nearest bathroom")

        # 3. Return as a Response with the correct MIME type
        return Response(content=path_image, media_type="image/png")
    

    
    # If water fountain is requested, find the nearest water fountain to the current room
    if water_fountain:
        
        # find the nearest water fountain to the current room
        curr_x = curr_room_check.data[0]["x"]
        curr_y = curr_room_check.data[0]["y"]

        # Get all water fountain locations for this building/floor
        water_fountain_locations = supabase_client.table("ticker_locations").select("x", "y", "ticker").eq("image", f"{building}_{floor}.png").eq("ticker", "water_fountain").execute()

        if not water_fountain_locations.data:
            raise HTTPException(status_code=404, detail="No water fountains found in this building/floor")

        # Find the nearest water fountain
        nearest_water_fountain = None
        min_distance = float('inf')

        for fountain in water_fountain_locations.data:
            distance = ((fountain["x"] - curr_x) ** 2 + (fountain["y"] - curr_y) ** 2) ** 0.5
            if distance < min_distance:
                min_distance = distance
                nearest_water_fountain = fountain
        
        # calculate path using hallway4.py
        path_image = hallway4.find_floorplan_path(temp_image_path, (curr_room_check.data[0]["x"], curr_room_check.data[0]["y"]), (nearest_water_fountain["x"], nearest_water_fountain["y"]))

        if path_image is None:
            raise HTTPException(status_code=404, detail="No path found to the nearest water fountain")
        
        # 3. Return as a Response with the correct MIME type
        return Response(content=path_image, media_type="image/png")
    
    # calculate target room location
    target_room_check = supabase_client.table("room_locations").select("x", "y").eq("image", f"{building}_{floor}.png").eq("room_number", target_room).execute()
    if not target_room_check.data:
        raise HTTPException(status_code=404, detail="Target room not found")
    
    target_room_x = target_room_check.data[0]["x"]
    target_room_y = target_room_check.data[0]["y"]

    # calculate path using hallway4.py
    path_image = hallway4.find_floorplan_path(temp_image_path, (curr_room_check.data[0]["x"], curr_room_check.data[0]["y"]), (target_room_x, target_room_y))

    if path_image is None:
        raise HTTPException(status_code=404, detail="No path found to the target room")
    
    # 3. Return as a Response with the correct MIME type
    return Response(content=path_image, media_type="image/png")
