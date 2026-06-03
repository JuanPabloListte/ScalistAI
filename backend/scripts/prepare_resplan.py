import pickle
import os
import sys
from pathlib import Path
import random
import multiprocessing as mp

import cv2
import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, Point

# ScalistAI Mappings
# CLASS_NAMES = ["background", "wall", "room", "door", "window", "sliding_door", "beam", "column", "roof"]
# -> [0, 1, 2, 3, 4, 5, 6, 7, 8]
MAPPING = {
    "wall": 1,
    "room": 2,
    "door": 3,
    "front_door": 3,
    "window": 4,
    # "sliding_door" is missing in ResPlan, they use window/door
}

def scale_geom(geom, factor=2.0):
    if geom is None or getattr(geom, 'is_empty', True):
        return geom
    return affinity.scale(geom, xfact=factor, yfact=factor, origin=(0, 0))

def poly_to_mask(geom, shape, color, thickness=-1):
    h, w = shape
    img = np.zeros((h, w), dtype=np.uint8)
    
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        return img
        
    for poly in polys:
        pts = np.array(poly.exterior.coords, dtype=np.int32)
        if thickness > 0:
            cv2.polylines(img, [pts], isClosed=True, color=color, thickness=thickness)
        else:
            cv2.fillPoly(img, [pts], color=color)
            
        for interior in poly.interiors:
            pts_in = np.array(interior.coords, dtype=np.int32)
            if thickness > 0:
                cv2.polylines(img, [pts_in], isClosed=True, color=0, thickness=thickness)
            else:
                cv2.fillPoly(img, [pts_in], color=0)
    return img

def lines_to_mask(geom, shape, color, thickness=2):
    h, w = shape
    img = np.zeros((h, w), dtype=np.uint8)
    
    if isinstance(geom, LineString):
        lines = [geom]
    elif isinstance(geom, MultiLineString):
        lines = list(geom.geoms)
    else:
        return img
        
    for line in lines:
        pts = np.array(line.coords, dtype=np.int32)
        cv2.polylines(img, [pts], isClosed=False, color=color, thickness=thickness)
    return img

def draw_geom(geom, shape, color, thickness=-1):
    if geom is None or getattr(geom, 'is_empty', True):
        return np.zeros(shape, dtype=np.uint8)
    
    if isinstance(geom, (Polygon, MultiPolygon)):
        return poly_to_mask(geom, shape, color, thickness)
    elif isinstance(geom, (LineString, MultiLineString)):
        return lines_to_mask(geom, shape, color, max(1, thickness))
    return np.zeros(shape, dtype=np.uint8)

def process_batch(args):
    start_idx, end_idx, out_dir, pkl_path = args
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)
        
    batch_data = data[start_idx:end_idx]
    
    for i, plan in enumerate(batch_data):
        idx = start_idx + i
        
        # Scale to 512x512
        H, W = 512, 512
        shape = (H, W)
        
        # Render image (RGB)
        img = np.full((H, W, 3), 255, dtype=np.uint8)
        
        # Render rooms as slight gray to give some texture, or keep white. Real plans are mostly white.
        # Let's keep it white, maybe add some noise later.
        
        # Render walls (Black)
        walls = scale_geom(plan.get("wall"), factor=2.0)
        wall_mask = draw_geom(walls, shape, 255, thickness=-1)
        img[wall_mask > 0] = (0, 0, 0)
        
        # Render doors and windows (Gray/Thin lines)
        doors = scale_geom(plan.get("door"), factor=2.0)
        front_doors = scale_geom(plan.get("front_door"), factor=2.0)
        windows = scale_geom(plan.get("window"), factor=2.0)
        
        door_mask = draw_geom(doors, shape, 255, thickness=2)
        front_door_mask = draw_geom(front_doors, shape, 255, thickness=2)
        win_mask = draw_geom(windows, shape, 255, thickness=2)
        
        img[door_mask > 0] = (100, 100, 100)
        img[front_door_mask > 0] = (100, 100, 100)
        img[win_mask > 0] = (150, 150, 150)
        
        # Add some noise/blur to make it look like a scanned real plan
        img = cv2.GaussianBlur(img, (3, 3), 0)
        noise = np.random.normal(0, 10, img.shape).astype(np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        
        # -------------------------------------------------------------
        # Render Mask (1 channel, values 0-8)
        # -------------------------------------------------------------
        target = np.zeros(shape, dtype=np.uint8)
        
        # Rooms (2)
        room_keys = ['living', 'bedroom', 'bathroom', 'kitchen', 'balcony', 'inner']
        for rk in room_keys:
            r_geom = scale_geom(plan.get(rk), factor=2.0)
            r_mask = draw_geom(r_geom, shape, MAPPING["room"], thickness=-1)
            target = np.maximum(target, r_mask)
            
        # Overwrite with walls (1)
        wall_mask_target = draw_geom(walls, shape, MAPPING["wall"], thickness=-1)
        target = np.where(wall_mask_target > 0, wall_mask_target, target)
        
        # Overwrite with openings (3 and 4)
        # Notice that in real ground truth, openings are drawn exactly where the wall is broken.
        # ResPlan vectors represent doors/windows as polygons or lines where the opening is.
        # Let's draw them with a slight thickness so they are visible.
        # Actually, draw_geom thickness for polygons doesn't matter if it's -1 (filled).
        door_mask_target = draw_geom(doors, shape, MAPPING["door"], thickness=-1)
        front_door_mask_target = draw_geom(front_doors, shape, MAPPING["door"], thickness=-1)
        win_mask_target = draw_geom(windows, shape, MAPPING["window"], thickness=-1)
        
        target = np.where(door_mask_target > 0, door_mask_target, target)
        target = np.where(front_door_mask_target > 0, front_door_mask_target, target)
        target = np.where(win_mask_target > 0, win_mask_target, target)
        
        # Save to disk
        # We group them in batches of 1000 so the directory doesn't explode
        batch_folder = out_dir / f"var_{idx // 1000 * 1000:05d}_{idx // 1000 * 1000 + 999:05d}"
        batch_folder.mkdir(parents=True, exist_ok=True)
        
        sample_dir = batch_folder / f"page_{idx:05d}"
        sample_dir.mkdir(parents=True, exist_ok=True)
        
        cv2.imwrite(str(sample_dir / "image.png"), img)
        cv2.imwrite(str(sample_dir / "mask.png"), target)

def main():
    pkl_path = "storage/resplan_raw/ResPlan.pkl"
    out_dir = Path("storage/dataset_resplan/train")
    
    if not os.path.exists(pkl_path):
        print(f"Error: {pkl_path} not found.")
        sys.exit(1)
        
    print("Loading PKL (this takes a few seconds)...")
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)
    
    total = min(len(data), 2000)
    print(f"Generating {total} plans out of {len(data)}.")
    
    # We will use multiprocessing to speed this up
    num_workers = mp.cpu_count()
    chunk_size = total // num_workers
    args = []
    
    for i in range(num_workers):
        start = i * chunk_size
        end = total if i == num_workers - 1 else (i + 1) * chunk_size
        args.append((start, end, out_dir, pkl_path))
        
    print(f"Generating synthetic dataset using {num_workers} processes...")
    with mp.Pool(num_workers) as pool:
        pool.map(process_batch, args)
        
    print("Done! Dataset saved in storage/dataset_resplan/train")

if __name__ == "__main__":
    main()
