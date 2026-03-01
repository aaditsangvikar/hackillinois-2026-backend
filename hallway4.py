import cv2
import numpy as np
from pathfinding.core.grid import Grid
from pathfinding.finder.a_star import AStarFinder

def snap_to_nearest_walkable(grid_matrix, point, penalty_threshold=10000):
    """
    If the point is on a wall (0) or outside (>= penalty_threshold), 
    find the nearest valid internal floor pixel.
    """
    x, y = point
    # Check if currently invalid
    if grid_matrix[y, x] > 0 and grid_matrix[y, x] < penalty_threshold:
        return point # Already on a good spot

    # Find all valid 'internal' pixels
    valid_indices = np.where((grid_matrix > 0) & (grid_matrix < penalty_threshold))
    valid_coords = np.column_stack(valid_indices) # Returns [y, x]
    
    # Calculate distances from our point to all valid pixels
    distances = (valid_coords[:, 0] - y)**2 + (valid_coords[:, 1] - x)**2
    closest_idx = np.argmin(distances)
    
    snapped_y, snapped_x = valid_coords[closest_idx]
    print(f"Snapped point {point} to ({snapped_x}, {snapped_y})")
    return (int(snapped_x), int(snapped_y))

def find_floorplan_path(image_path, start_point, end_point):
    grid_matrix, img = preprocess_with_doors(image_path)
    
    # --- NEW: SNAP START AND END TO VALID FLOOR ---
    # This prevents the A* from failing immediately if the user clicks a wall
    start_point = snap_to_nearest_walkable(grid_matrix, start_point)
    # We don't necessarily snap the end point yet because your Fallback Logic 
    # already handles unreachable destinations, but snapping here helps A* succeed.
    end_point = snap_to_nearest_walkable(grid_matrix, end_point)

    grid = Grid(matrix=grid_matrix)
    start = grid.node(start_point[0], start_point[1])
    end = grid.node(end_point[0], end_point[1])

    finder = AStarFinder()
    path, runs = finder.find_path(start, end, grid)

    # --- FALLBACK LOGIC ---
    if not path:
        print("Target unreachable. Finding nearest accessible point...")
        
        # 1. Get all walkable pixels from the grid_matrix (where value > 0)
        # We only care about pixels reachable from the START
        # OpenCV's connectedComponents is perfect for this
        walkable_mask = (grid_matrix > 0).astype(np.uint8)
        num_labels, labels = cv2.connectedComponents(walkable_mask)
        
        # 2. Identify which 'island' the start point belongs to
        start_label = labels[start_point[1], start_point[0]]
        
        if start_label == 0:
            print("Error: Start point is inside a wall!")
            return

        # 3. Get coordinates of all pixels in the same island as the start
        reachable_pixels = np.column_stack(np.where(labels == start_label)) 
        # Note: np.where returns (row, col) which is (y, x)
        
        # 4. Find the pixel in that island closest to the original end_point
        # Using Euclidean distance: (y-y1)^2 + (x-x1)^2
        target_y, target_x = end_point[1], end_point[0]
        distances = (reachable_pixels[:, 0] - target_y)**2 + (reachable_pixels[:, 1] - target_x)**2
        closest_idx = np.argmin(distances)
        
        nearest_coords = reachable_pixels[closest_idx] # returns [y, x]
        new_end = grid.node(nearest_coords[1], nearest_coords[0])
        
        # 5. Path to the nearest neighbor
        path, runs = finder.find_path(start, new_end, grid)
        
        if path:
            print(f"Pathing to nearest point: ({nearest_coords[1]}, {nearest_coords[0]})")
            # Update end_point for drawing the blue circle later
            end_point = (int(nearest_coords[1]), int(nearest_coords[0]))

    # --- VISUALIZATION ---
    if path:
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        
        for point in path[::15]:
            # img[point.y, point.x] = [0, 0, 255]
            cv2.circle(img, (point.x, point.y), 5, (255, 0, 0), -1)
        
        # cv2.circle(img, start_point, 5, (0, 255, 0), -1)
        cv2.drawMarker(img, start_point, (255, 0, 0), markerType=cv2.MARKER_DIAMOND, markerSize=30, thickness=25)
        cv2.drawMarker(img, end_point, (0, 0, 255), markerType=cv2.MARKER_SQUARE, markerSize=28, thickness=25)
        # cv2.circle(img, end_point, 5, (255, 0, 0), -1) # This is now the "closest" point

        success, buffer = cv2.imencode('.png', img)
        if not success:
            return None
        return buffer.tobytes()
    
    else:
        print("Completely trapped. No walkable area found around start.")
        return None

def preprocess_with_doors(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

    _, binary = cv2.threshold(img, 220, 255, cv2.THRESH_BINARY_INV)

    # STEP 1: CLOSE DOUBLE WALLS
    gap_closer_kernel = np.ones((4, 4), np.uint8)
    closed_walls = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, gap_closer_kernel)

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

    # --- STEP 4: DISTANCE TRANSFORM FOR CENTERING ---
    # First, get the walkable area (invert walls_only)
    walkable_mask = cv2.bitwise_not(walls_only)
    
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




    
    # # Final cleanup: Ensure walkable areas are at least 1 (A* needs > 0)
    # # We scale the weights so the library handles them as integers effectively.
    # final_grid = np.where(weights > 0, weights + 1, 0).astype(int)

    return final_grid, img

if __name__ == "__main__":
    find_floorplan_path('thing.png', (109, 91), (708, 584))