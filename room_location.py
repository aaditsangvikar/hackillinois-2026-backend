import easyocr
import numpy as np
import gc

# Initialize the reader (English language)
# This takes a second to load, so do it once at the top of your script
reader = easyocr.Reader(['en'], gpu=False)

def map_room_numbers(image_path):
    """
    Scans the floorplan and returns a dictionary: {'101': (x, y), '102': (x, y)}
    """
    print("Scanning for room numbers... (this may take a few seconds)")
    results = reader.readtext(image_path)
    
    room_map = {}
    for (bbox, text, prob) in results:
        # EasyOCR returns bbox as [[top_left], [top_right], [bottom_right], [bottom_left]]
        # We calculate the center point of the box
        (tl, tr, br, bl) = bbox
        center_x = int((tl[0] + br[0]) / 2)
        center_y = int((tl[1] + br[1]) / 2)
        
        # Clean the text (remove spaces/extra chars)
        room_id = text.strip()
        room_map[room_id] = (center_x, center_y)

        del reader
        gc.collect()
        
    return room_map