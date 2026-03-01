# calls upload_image function from main.py
# to upload a floorplan to the database
# calls every 10 seconds
# for every floorplan in data_without_tickers

import time
import os
import requests
FLOORPLAN_DIR = "/Users/aadit/Documents/GitHub/hackIllinois_26/data_without_tickers_png"
API_URL = "http://localhost:8000/api/upload-png"   

def upload_floorplans():
    for filename in os.listdir(FLOORPLAN_DIR):
        if filename.endswith(".png"):
            file_path = os.path.join(FLOORPLAN_DIR, filename)
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f, 'image/png')}
                response = requests.post(API_URL, files=files)
                print(f"Uploaded {filename}: {response.status_code} - {response.text}")
        
if __name__ == "__main__":
    while True:
        upload_floorplans()
        time.sleep(10)  # Wait for 10 seconds before the next upload cycle


