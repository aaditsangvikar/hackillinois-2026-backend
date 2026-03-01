# Illini Relief: Autonomous Indoor Pathfinding API

**Illini Relief** is a high-performance backend engine that transforms static 2D architectural floor plans into navigable, weighted grids. Unlike traditional navigation systems that require manual node-mapping, this API uses **Computer Vision** and **Non-Linear Distance Transforms** to automatically understand building topology and calculate optimal, centered paths.

## Key Features

* **Door Removal:** Uses **Hough Circle Transforms** to detect quarter-circle door swings and "nuke" them from the wall mask, opening paths into rooms.
* **Double-Line Wall Reconstruction:** Automatically bridges the gap between architectural double-lines to create solid structural barriers.
* **Centering Physics:** Implements an exponential weighting system to force paths into the middle of hallways.
* **Leaktight Exterior Hull:** Uses **Flood Fill** and massive morphological kernels to prevent paths from "leaking" out of windows or thin gaps in the drawing.
* **Intelligent Snap-to-Floor:** Automatically teleports user clicks from walls or room numbers to the nearest valid walkable pixel.

---

## Technical Architecture

### 1. Image Processing Pipeline

The backend processes the raw image through a multi-stage OpenCV pipeline:

1. **Binary Inversion:** Walls $\rightarrow$ White ($255$), Floor $\rightarrow$ Black ($0$).
2. **Morphological Closing:** Bridges double-line walls using a $4 \times 4$ kernel.
3. **Hough Circle Detection:** Identifies door arcs and fills them with black pixels to create "walkable" space.
4. **Contour Filtering:** Removes room numbers and text "islands" based on a minimum area threshold ($350 \text{px}^2$).

### 2. The Weighting Engine

To ensure a "natural" walking path, we calculate the cost of every pixel $W$ based on its Euclidean distance $d$ to the nearest wall:

$$W(d) = (d_{max} - d)^3$$

By cubing the inverse distance, we create an **exponential repulsion field** around walls. The A* algorithm then finds the path of least resistance:

$$\min \sum_{i \in \text{path}} W(d_i)$$

---

## Installation & Setup

### Prerequisites

* Python 3.10+
* OpenCV (`opencv-python`)
* NumPy
* `pathfinding` library

```bash
pip install opencv-python numpy pathfinding

```

### Quick Start

```python
from hallway2 import find_floorplan_path

# Define (x, y) coordinates
start = (109, 91)
end = (708, 584)

# Run the engine
find_floorplan_path('your_floorplan.png', start, end)

```

---

## API Logic Flow

| Stage | Logic | Result |
| --- | --- | --- |
| **Input** | Raw PNG/JPG | Grayscale Matrix |
| **Clean** | Median Blur & Area Filter | No Room Numbers |
| **Logic** | Hough Circles | No Doors (Walkable) |
| **Physics** | Distance Transform | Weighted Heatmap |
| **Search** | A* Algorithm | Optimal Centered Path |

---

## Challenges Overcome

* **The "Leaky" Building:** Solved by creating a "Leaktight Hull"—an ultra-thick version of the building used only to define the "Outside" via Flood Fill, preventing paths from exiting through windows.
* **Wall Hugging:** Initially, A* took the shortest geometric path (scraping walls). We solved this by implementing the cubic weight scale to prioritize hallway centers.
* **Connectivity:** Added a fallback mechanism that, if a target is unreachable, calculates the nearest valid "island" coordinate to provide the user with the closest possible destination.
