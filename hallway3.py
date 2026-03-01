import cv2
import numpy as np
from pathfinding.core.grid import Grid
from pathfinding.finder.a_star import AStarFinder

def find_floorplan_path(image_path, start_point, end_point):
    # 1. Get the weighted grid
    grid_matrix, img = preprocess_with_doors(image_path)

    # 2. Initialize Grid with weights
    grid = Grid(matrix=grid_matrix)

    start = grid.node(start_point[0], start_point[1])
    end = grid.node(end_point[0], end_point[1])

    # 3. RUN A* (The finder now respects the weights in the matrix)
    finder = AStarFinder()
    path, runs = finder.find_path(start, end, grid)

    if path:
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        
        # Draw path
        for point in path:
            img[point.y, point.x] = [0, 0, 255]
        
        cv2.circle(img, start_point, 5, (0, 255, 0), -1)
        cv2.circle(img, end_point, 5, (255, 0, 0), -1)
        
        success, buffer = cv2.imencode('.png', img)

        if not success:
            return None

        # 2. Convert the buffer to bytes
        raw_image_bytes = buffer.tobytes()

        # 3. Return as a Response with the correct MIME type
        return raw_image_bytes
    else:
        print("No path found.")
        return None

def preprocess_with_doors(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

    _, binary = cv2.threshold(img, 220, 255, cv2.THRESH_BINARY_INV)

    # STEP 1: CLOSE DOUBLE WALLS
    gap_closer_kernel = np.ones((3, 3), np.uint8)
    closed_walls = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, gap_closer_kernel)

    # display closed walls for debugging
    # cv2.imshow("Closed Walls", closed_walls)
    # cv2.waitKey(0)

    # --- STEP 2: SURGICAL DOOR REMOVAL (Hough Circles) ---
    # We detect circles/arcs and wipe them out.
    
    # 1. Blur slightly to help the detector ignore pixel noise
    arc_blur = cv2.GaussianBlur(closed_walls, (5, 5), 0)
    
    # 2. Find Circles
    # minDist: distance between centers (prevents double-detecting one door)
    # param1: Canny edge threshold
    # param2: Accumulator threshold (Lower = more sensitive to partial arcs)
    circles = cv2.HoughCircles(
        arc_blur, 
        cv2.HOUGH_GRADIENT, 
        dp=1.2, 
        minDist=20, 
        param1=50, 
        param2=70, # <--- Lower this if doors aren't being detected
        minRadius=10, 
        maxRadius=30
    )

    walls_only = closed_walls.copy()

    if circles is not None:
        circles = np.uint16(np.around(circles))
        for i in circles[0, :]:
            # Draw a black circle over the detected arc to "nuke" the door swing
            # We draw it slightly larger (radius + 2) to ensure the whole line is gone
            cv2.circle(walls_only, (i[0], i[1]), i[2] + 2, 0, thickness=-1)

    # Clean up any leftover tiny fragments from the arcs
    cleanup_kernel = np.ones((3, 3), np.uint8)
    walls_only = cv2.morphologyEx(walls_only, cv2.MORPH_OPEN, cleanup_kernel)

    # # STEP 3: REMOVE TEXT/NUMBERS
    contours, _ = cv2.findContours(walls_only, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        if cv2.contourArea(cnt) < 200:  # Threshold area to filter out small contours
            cv2.drawContours(walls_only, [cnt], -1, 0, -1)  # Fill small contours with black 

      
    # cv2.imshow("Walls Only", walls_only)
    # cv2.waitKey(0)

    # --- STEP 4: DISTANCE TRANSFORM FOR CENTERING ---
    # First, get the walkable area (invert walls_only)
    walkable_mask = cv2.bitwise_not(walls_only)

    # display walkable area for debugging
    # cv2.imshow("Walkable Area", walkable_mask)
    # cv2.waitKey(0)
    
    # Calculate distance from every white pixel to the nearest black wall
    dist = cv2.distanceTransform(walkable_mask, cv2.DIST_L2, 5)
    
    # Normalize distance for weighting (0 to 100 range)
    # The center of the hall will have the HIGHEST distance value.
    max_dist = np.max(dist) if np.max(dist) > 0 else 1
    
    # Create a Weight Map:
    # We want center pixels to be 1 (cheap) and pixels near walls to be high (expensive).
    # Weight = (Max_Distance - Current_Distance) + 1
    # We use a power of 2 to make the "repulsion" from walls even stronger.
    weights = (max_dist - dist)

    weights = np.power(weights, 3)  # Add 1 to ensure walkable areas are > 0
    weights = np.where(walls_only > 0, 0, weights) # 0 is still a wall (blocked)

    






    # --- STEP 5: ROBUST EXTERIOR PENALTY ---
    
   # --- STEP 5: TARGETED EXTERIOR PENALTY ---
    
    # 1. Create a "Leaktight" version of the walls to define the boundary
    # We use a large kernel to bridge doors/gaps (31x31 is usually safe)
    hull_kernel = np.ones((31, 31), np.uint8)
    # Note: Using 'binary' here (where walls are 255)
    leaktight_hull = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, hull_kernel)
    
    # 2. Flood fill the exterior from the image corners
    h, w = leaktight_hull.shape
    exterior_mask = np.zeros((h, w), np.uint8)
    
    # We create a temporary image for floodfilling (0=floor, 255=wall)
    temp_hull = leaktight_hull.copy()
    ff_mask = np.zeros((h + 2, w + 2), np.uint8)
    
    # Seed from all 4 corners to capture the entire "yard"
    for seed in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]:
        if temp_hull[seed[1], seed[0]] == 0:
            cv2.floodFill(temp_hull, ff_mask, seed, 127)
            
    # 3. Identify ONLY the pixels that are truly outside
    is_outside = (temp_hull == 127)

    # 4. Create the final grid
    # Logic: 
    # IF pixel is a wall (walls_only > 0) -> 0 (Blocked)
    # ELSE IF pixel is outside (is_outside) -> 10000 (Penalty)
    # ELSE (Inside the building) -> Use existing distance-based weights
    
    penalty_value = 10000
    
    # Start with your internal distance weights
    # final_grid = weights.copy()
    
    # # Only apply the penalty to the "Outside" area
    # final_grid[is_outside] = penalty_value
    
    # # Ensure all structural walls are absolute zero (blocked)
    # final_grid[walls_only > 0] = 0
    
    # # Final cleanup: Ensure internal walkable areas are at least 1 (A* requirement)
    # # and everything is an integer.
    # final_grid = np.where((final_grid > 0) & (final_grid < penalty_value), 
    #                       final_grid + 1, 
    #                       final_grid).astype(int)
    


    # DEBUG: You can visualize the separation



    # --- STEP 6: DEBUG VISUALIZATION (INTERNAL ONLY) ---
    
    # 1. Normalize the internal weights to 0-255 so we can see the "heat map"
    # We only want to normalize the values that are INSIDE the building
    internal_mask = np.logical_not(is_outside) & (walls_only == 0)




    internal_max = np.max(weights[internal_mask]) if np.any(internal_mask) else 1
    weights_scaled = (weights / internal_max) * 255
    
    final_grid = weights_scaled.copy()
    final_grid[is_outside] = penalty_value # Keep exterior penalty massive
    final_grid[walls_only > 0] = 0 # Keep walls blocked
    
    final_grid = final_grid.astype(int)




    
    # Create a display image (starts as dark gray for the "outside")
    debug_view = np.full((h, w), 50, dtype=np.uint8) 
    
    if np.any(internal_mask):
        # Extract internal weights
        internal_weights = final_grid[internal_mask]
        
        # Normalize internal weights to 0-255 (Lower weight = Brighter/Better)
        # We invert it (255 - normalized) so the "Center" of the hall looks brightest
        norm_weights = cv2.normalize(internal_weights.astype(float), None, 0, 255, cv2.NORM_MINMAX)
        debug_view[internal_mask] = (255 - norm_weights.flatten()).astype(np.uint8)

    # 2. Make walls pitch black so they stand out
    debug_view[walls_only > 0] = 0

    # 3. Apply a ColorMap to make it look like a "Heat Map"
    # This makes the "center" of hallways look Yellow/Red and edges look Blue
    color_debug = cv2.applyColorMap(debug_view, cv2.COLORMAP_JET)
    
    # 4. Black out the outside again (since ColorMap colors everything)
    color_debug[is_outside] = [30, 30, 30] # Dark Gray for "Undesirable"
    color_debug[walls_only > 0] = [0, 0, 0] # Pure Black for "Walls"

    # cv2.imshow("Weight Map Debug (Inside Only)", color_debug)
    # cv2.waitKey(0) # Use 1 to let it update without freezing, or 0 to pause




    
    # # Final cleanup: Ensure walkable areas are at least 1 (A* needs > 0)
    # # We scale the weights so the library handles them as integers effectively.
    # final_grid = np.where(weights > 0, weights + 1, 0).astype(int)

    return final_grid, img

if __name__ == "__main__":
    find_floorplan_path('thing.png', (109, 91), (708, 584))