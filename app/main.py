# app/main.py
from flask import Flask, render_template, send_from_directory
import requests
import time
import os
from datetime import datetime
import threading
from pathlib import Path
import logging
import pytz
from PIL import Image
import io
from astral import LocationInfo
from astral.sun import sun

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

IMAGES_DIR = Path("/app/images")
THUMBNAILS_DIR = Path("/app/thumbnails")
IMAGES_DIR.mkdir(exist_ok=True)
THUMBNAILS_DIR.mkdir(exist_ok=True)

def get_sun_times():
    # Chalupa na Rozcestí coordinates
    city = LocationInfo("Chalupa", "Czech Republic", "Europe/Prague", 
                       50.7056489, 15.6749678)
    # Set altitude after creation
    city.observer.elevation = 1350  # elevation in meters
    s = sun(city.observer, date=datetime.now())
    return s["sunrise"], s["sunset"]

def get_interval():
    now = datetime.now(pytz.timezone('Europe/Prague'))
    sunrise, sunset = get_sun_times()
    
    # Add 30 minutes buffer around sunrise/sunset
    sunrise_window = sunrise.timestamp() - 3600, sunrise.timestamp() + 3600
    sunset_window = sunset.timestamp() - 3600, sunset.timestamp() + 3600
    current_time = now.timestamp()
    
    if sunrise.timestamp() <= current_time <= sunset.timestamp():
        # During daytime
        if (sunrise_window[0] <= current_time <= sunrise_window[1] or 
            sunset_window[0] <= current_time <= sunset_window[1]):
            interval = 120  # 2 minutes around sunrise/sunset
            logger.info("Sunrise/sunset period - using 2 minute interval")
        else:
            interval = 600  # 10 minutes during day
            logger.info("Daytime period - using 10 minute interval")
    else:
        interval = 1800  # 30 minutes during night
        logger.info("Nighttime period - using 30 minute interval")
    
    return interval

def create_thumbnail(image_path):
    try:
        thumb_path = THUMBNAILS_DIR / f"thumb_{image_path.name}"
        if not thumb_path.exists():
            with Image.open(image_path) as img:
                img.thumbnail((400, 400))  # Smaller size for grid view
                img.save(thumb_path, "JPEG", quality=85)
        return thumb_path
    except Exception as e:
        logger.error(f"Error creating thumbnail: {e}")
        return None

def get_cet_time():
    utc_now = datetime.now(pytz.UTC)
    cet = pytz.timezone('Europe/Prague')
    return utc_now.astimezone(cet)

def download_image():
    try:
        # First download
        response1 = requests.get("https://chalupanarozcesti.cz/webcam/latest.php", stream=True)
        if response1.status_code == 200:
            content1 = response1.content
            
            # Wait a short moment
            time.sleep(5)
            
            # Second download
            response2 = requests.get("https://chalupanarozcesti.cz/webcam/latest.php", stream=True)
            if response2.status_code == 200:
                content2 = response2.content
                
                # Compare downloads
                if content1 == content2:
                    timestamp = get_cet_time().strftime("%Y%m%d_%H%M%S")
                    filename = IMAGES_DIR / f"image_{timestamp}.jpg"
                    
                    # Save the verified image
                    with open(filename, 'wb') as f:
                        f.write(content1)
                    
                    # Get all images from the last minute
                    current_minute = timestamp[:-2]  # Remove seconds
                    recent_images = list(IMAGES_DIR.glob(f'image_{current_minute}*.jpg'))
                    
                    if len(recent_images) > 1:
                        # Sort by size and keep only the largest
                        recent_images.sort(key=lambda x: x.stat().st_size, reverse=True)
                        for img in recent_images[1:]:
                            img.unlink()  # Delete smaller images
                            logger.info(f"Removed smaller duplicate: {img}")
                    
                    # Create thumbnail for the kept image
                    create_thumbnail(filename)
                    logger.info(f"Downloaded and verified image: {filename}")
                else:
                    logger.error("Downloads don't match, skipping save")
            
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        # Remove failed download if file was created
        if 'filename' in locals() and filename.exists():
            filename.unlink()

def run_scheduler():
    while True:
        download_image()
        interval = get_interval()
        time.sleep(interval)

@app.route('/')
def gallery():
    images = []
    is_daytime = False  # Initialize default value
    try:
        sunrise, sunset = get_sun_times()
        current_time = datetime.now(pytz.timezone('Europe/Prague'))
        is_daytime = sunrise.timestamp() <= current_time.timestamp() <= sunset.timestamp()
        
        image_files = sorted(list(IMAGES_DIR.glob('*.jpg')), reverse=True)
        
        for img_path in image_files:
            try:
                timestamp = img_path.stem.replace('image_', '')
                dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
                dt = pytz.timezone('Europe/Prague').localize(dt)
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                day = dt.strftime("%Y-%m-%d")
                
                # Ensure thumbnail exists
                create_thumbnail(img_path)
                
                images.append({
                    'path': img_path.name,
                    'thumb_path': f"thumb_{img_path.name}",
                    'formatted_time': formatted_time,
                    'day': day
                })
            except Exception as e:
                logger.error(f"Error processing image {img_path}: {e}")
                continue
                
        logger.info(f"Found {len(images)} images")
    except Exception as e:
        logger.error(f"Error listing images: {e}")
        
    return render_template('gallery.html', images=images, is_daytime=is_daytime)

@app.route('/images/<path:filename>')
def serve_image(filename):
    response = send_from_directory(str(IMAGES_DIR), filename)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/thumbnails/<path:filename>')
def serve_thumbnail(filename):
    response = send_from_directory(str(THUMBNAILS_DIR), filename)
    response.headers['Cache-Control'] = 'public, max-age=31536000'
    return response

if __name__ == '__main__':
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    app.run(host='0.0.0.0', port=8001, debug=True)
