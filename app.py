# app.py - Final with LibreOffice primary conversion (Windows)
import os
import shutil
import zipfile
import subprocess
import logging
import hashlib
from io import BytesIO
from functools import wraps
from datetime import datetime
from tempfile import TemporaryDirectory

from flask import (Flask, render_template, Response, request, redirect,
                   url_for, session, flash, send_from_directory)
from werkzeug.utils import secure_filename

import sqlite3
import cv2
import numpy as np
from pdf2image import convert_from_path
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation  # only kept if you want fallback usage later (not required)
from cvzone.HandTrackingModule import HandDetector

# -------------------------
# User-specific config
# -------------------------
BASE_DIR = r"C:C:\Users\anask\H_G_P_project"
UPLOAD_FOLDER = os.path.join(BASE_DIR, "ppt_uploads")
IMAGES_FOLDER = r"C:\temp_images"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf", "ppt", "pptx", "zip"}

# LibreOffice soffice.exe path (64-bit)
SOFFICE_PATH = r"C:\Program Files\LibreOffice\program\soffice.exe"

# Poppler bin path (where pdftoppm.exe lives) - from your input
POPPLER_BIN = r"C:\Users\anask\Downloads\poppler\Library\bin"

# Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["POPPLER_PATH"] = POPPLER_BIN

# ensure directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(IMAGES_FOLDER, exist_ok=True)

# logging
logging.basicConfig(level=logging.INFO)

# -------------------------
# Camera + Hand Detector
# -------------------------
width, height = 1280, 720
ws, hs = 213, 120

# On Windows, sometimes specifying CAP_DSHOW helps. If problems, fall back to default.
try:
    # Prefer DirectShow backend on Windows to avoid some driver issues
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
except TypeError:
    # Older OpenCV versions may not accept the second argument
    cap = cv2.VideoCapture(0)

# Safely try to set capture resolution; if it fails, log but don't crash.
try:
    if cap is not None:
        cap.set(3, width)
        cap.set(4, height)
except Exception as e:
    logging.error(f"Failed to set camera resolution: {e}")

detector = HandDetector(detectionCon=0.7, maxHands=1)

# -------------------------
# Application State
# -------------------------
class PresentationState:
    def __init__(self):
        self.pathImages = []       # absolute paths to slide images
        self.imgNumber = 0
        self.buttonPressed = False
        self.buttonCounter = 0
        self.buttonCooldown = 20
        self.annotations = [[]]
        self.annotationNumber = 0
        self.annotationStart = False

state = PresentationState()

# -------------------------
# Database (SQLite)
# -------------------------
DB_PATH = os.path.join(BASE_DIR, "presentation_users.db")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# -------------------------
# Helpers: files & conversion
# -------------------------
def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def clear_images_folder():
    """Delete all images in IMAGES_FOLDER (Option2 replacement behavior)."""
    if os.path.exists(IMAGES_FOLDER):
        for fn in os.listdir(IMAGES_FOLDER):
            fp = os.path.join(IMAGES_FOLDER, fn)
            try:
                if os.path.isfile(fp) or os.path.islink(fp):
                    os.unlink(fp)
                elif os.path.isdir(fp):
                    shutil.rmtree(fp)
            except Exception as e:
                logging.error(f"Failed to delete {fp}: {e}")
    else:
        os.makedirs(IMAGES_FOLDER, exist_ok=True)

def save_pil_as_jpg(pil_img: Image.Image, out_path: str, quality: int = 82):
    """Save PIL image as JPEG; default quality 82 balances speed and file size."""
    pil_img.convert("RGB").save(out_path, "JPEG", quality=quality, optimize=False)

def canonicalize_and_number_images(out_folder: str):
    """
    Rename JPG files in out_folder to slide_1.jpg, slide_2.jpg, ... and return absolute paths sorted.
    """
    jpgs = sorted([f for f in os.listdir(out_folder) if f.lower().endswith(('.jpg', '.jpeg'))], key=lambda x: x.lower())
    final = []
    for idx, name in enumerate(jpgs, start=1):
        src = os.path.join(out_folder, name)
        dst = os.path.join(out_folder, f"slide_{idx}.jpg")
        if os.path.abspath(src) != os.path.abspath(dst):
            try:
                os.replace(src, dst)
            except Exception:
                shutil.copy(src, dst)
                try:
                    os.remove(src)
                except Exception:
                    pass
        final.append(dst)
    return final

def extract_images_from_zip(zip_path: str, out_folder: str):
    out_paths = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            members = sorted([m for m in z.namelist() if m.lower().endswith(('.png', '.jpg', '.jpeg'))])
            for idx, member in enumerate(members, start=1):
                data = z.read(member)
                img = Image.open(BytesIO(data)).convert("RGB")
                pth = os.path.join(out_folder, f"slide_{idx}.jpg")
                img.save(pth, "JPEG", quality=82, optimize=False)
                out_paths.append(pth)
    except Exception as e:
        logging.error(f"Zip extraction error: {e}")
    return out_paths

def pdf_to_jpgs(pdf_path: str, out_folder: str, dpi: int = 120):
    """
    Convert PDF to JPGs using pdf2image (poppler). Returns list of paths.
    Uses lower DPI (120) and thread_count for faster conversion; output is
    still plenty sharp for 960x540 display.
    """
    poppler_path = app.config.get("POPPLER_PATH") or None
    thread_count = min(4, (os.cpu_count() or 2))
    try:
        pages = convert_from_path(
            pdf_path,
            dpi=dpi,
            poppler_path=poppler_path,
            thread_count=thread_count,
        )
    except Exception as e:
        logging.error(f"pdf2image conversion failed: {e}")
        return []
    out = []
    for i, page in enumerate(pages, start=1):
        pth = os.path.join(out_folder, f"slide_{i}.jpg")
        save_pil_as_jpg(page, pth, quality=82)
        out.append(pth)
    return out

def libreoffice_pptx_to_pdf(input_path: str, output_dir: str):
    """
    Convert PPT / PPTX to PDF using LibreOffice headless.
    Returns path to generated PDF or None on failure.
    """
    try:
        cmd = [
            SOFFICE_PATH,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            input_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        base = os.path.splitext(os.path.basename(input_path))[0]
        pdf_path = os.path.join(output_dir, f"{base}.pdf")
        if os.path.exists(pdf_path):
            return pdf_path
        else:
            logging.error("LibreOffice conversion completed but PDF was not found.")
            return None
    except FileNotFoundError:
        logging.error("LibreOffice (soffice.exe) not found at the configured path.")
        return None
    except subprocess.CalledProcessError as e:
        logging.error(f"LibreOffice conversion failed: {e}")
        return None

# -------------------------
# Gesture handling functions
# -------------------------
def process_hand_gestures(hands):
    if not hands:
        return
    hand = hands[0]
    fingers = detector.fingersUp(hand)

    if state.buttonCounter >= state.buttonCooldown:
        if fingers == [1, 0, 0, 0, 0] and state.imgNumber > 0:  # thumb up -> previous
            state.imgNumber -= 1
            state.buttonCounter = 0
        if fingers == [0, 0, 0, 0, 1] and state.pathImages and state.imgNumber < len(state.pathImages) - 1:  # pinky -> next
            state.imgNumber += 1
            state.buttonCounter = 0

    state.buttonCounter += 1

    if fingers == [0, 1, 0, 0, 0]:  # index -> draw
        x, y = int(hand['lmList'][8][0]), int(hand['lmList'][8][1])
        handle_drawing(x, y)
    if fingers == [0, 1, 1, 1, 0]:  # three fingers -> undo
        handle_undo()
    if fingers == [0, 0, 0, 0, 0]:  # fist -> clear
        handle_clear()

def handle_drawing(x, y):
    if not state.annotationStart:
        state.annotationStart = True
        state.annotationNumber += 1
        state.annotations.append([])
    while state.annotationNumber >= len(state.annotations):
        state.annotations.append([])
    state.annotations[state.annotationNumber].append((x, y))

def handle_undo():
    if state.annotations and len(state.annotations) > 1:
        state.annotations.pop(-1)
        state.annotationNumber = max(0, len(state.annotations) - 1)
        state.buttonPressed = True

def handle_clear():
    state.annotations = [[]]
    state.annotationNumber = 0
    state.buttonPressed = True

# -------------------------
# Video generation
# -------------------------
def get_current_slide():
    if not state.pathImages:
        return np.zeros((720, 1280, 3), np.uint8)
    if state.imgNumber < len(state.pathImages):
        img = cv2.imread(state.pathImages[state.imgNumber])
        if img is None:
            return np.zeros((720, 1280, 3), np.uint8)
        return img
    state.imgNumber = max(0, len(state.pathImages) - 1)
    return cv2.imread(state.pathImages[state.imgNumber])

def draw_annotations(imgSlide):
    for i in range(len(state.annotations)):
        for j in range(len(state.annotations[i])):
            if j != 0:
                cv2.line(imgSlide, state.annotations[i][j-1], state.annotations[i][j], (0,255,0), 5)

def generate_video():
    while True:
        try:
            success, frame = cap.read()

            if not success or frame is None:
                blank = np.zeros((540, 960, 3), np.uint8)
                ret, buffer = cv2.imencode('.jpg', blank)
                if not ret:
                    continue
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' +
                       frame_bytes + b'\r\n')
                continue

            frame = cv2.flip(frame, 1)

            # Load slide
            imgCurrent = get_current_slide()
            if imgCurrent is None:
                imgCurrent = np.zeros((720, 1280, 3), np.uint8)

            imgSlide = cv2.resize(imgCurrent, (960, 540))

            # Hand detection safe
            hands = []
            cam_img = frame
            try:
                result = detector.findHands(frame)
                if isinstance(result, tuple):
                    hands, cam_img = result
                else:
                    hands = result
            except Exception as e:
                logging.error(f"Hand detection error: {e}")

            # Process gestures
            process_hand_gestures(hands)

            # Draw annotations
            draw_annotations(imgSlide)

            # Overlay camera
            small = cv2.resize(cam_img, (ws, hs))
            imgSlide[0:hs, 960-ws:960] = small

            ret, buffer = cv2.imencode('.jpg', imgSlide)
            if not ret:
                continue

            frame_bytes = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' +
                   frame_bytes + b'\r\n')

        except Exception as e:
            logging.error(f"Stream error: {e}")
            continue
# -------------------------
# Routes
# -------------------------
@app.route('/')
def root():
    return redirect(url_for('gesture_presentation'))

@app.route('/gesture_presentation')
def gesture_presentation():
    # If you are not enforcing login, comment out login requirement.
    # For this final file I'm not enforcing login to simplify testing.
    # If you want auth, re-add @login_required and related routes.
    user = session.get('username')
    return render_template('gesture_presentation.html', username=user)

@app.route('/video_feed')
def video_feed():
    """Stream MJPEG with no-cache headers so live preview updates reliably."""
    return Response(
        generate_video(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
        }
    )
@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(IMAGES_FOLDER, filename)

# Upload route (uses LibreOffice first for ppt/pptx)
@app.route('/upload_file', methods=['POST'])
def upload_file():
    if 'presentation_file' not in request.files:
        flash("No file part", "error")
        return redirect(url_for('gesture_presentation'))
    file = request.files['presentation_file']
    if file.filename == '':
        flash("No file selected", "error")
        return redirect(url_for('gesture_presentation'))
    if not allowed_file(file.filename):
        flash("File type not allowed", "error")
        return redirect(url_for('gesture_presentation'))

    filename = secure_filename(file.filename)
    saved_tmp = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        file.save(saved_tmp)
    except Exception as e:
        logging.error(f"Saving uploaded file failed: {e}")
        flash("Save failed", "error")
        return redirect(url_for('gesture_presentation'))

    # Replace previous images
    clear_images_folder()

    ext = filename.rsplit('.', 1)[1].lower()
    final_list = []

    try:
        if ext in ('jpg', 'jpeg', 'png'):
            # Single image -> slide_1.jpg
            img = Image.open(saved_tmp).convert("RGB")
            out = os.path.join(IMAGES_FOLDER, "slide_1.jpg")
            img.save(out, "JPEG", quality=85)
            final_list = [out]

        elif ext == 'zip':
            final_list = extract_images_from_zip(saved_tmp, IMAGES_FOLDER)

        elif ext == 'pdf':
            final_list = pdf_to_jpgs(saved_tmp, IMAGES_FOLDER)

        elif ext in ('ppt', 'pptx'):
            # 1) Convert PPTX -> PDF using LibreOffice to a temp dir
            with TemporaryDirectory() as tmpdir:
                pdf_path = libreoffice_pptx_to_pdf(saved_tmp, tmpdir)
                if not pdf_path:
                    # LibreOffice failed - flash and try fallback: pdf2image from saved_tmp if it's pdf
                    logging.error("LibreOffice conversion failed for PPT/PPTX.")
                    flash("LibreOffice conversion failed. Ensure LibreOffice is installed at the configured path.", "error")
                    return redirect(url_for('gesture_presentation'))

                # 2) Convert the generated PDF to JPG pages using poppler/pdf2image
                final_list = pdf_to_jpgs(pdf_path, IMAGES_FOLDER)
        else:
            flash("Unsupported file type", "error")
            return redirect(url_for('gesture_presentation'))

        # canonicalize names slide_1..N
        final_list = canonicalize_and_number_images(IMAGES_FOLDER)

        if not final_list:
            flash("No slides generated. Try a different file.", "error")
            return redirect(url_for('gesture_presentation'))

        # update state
        state.pathImages = final_list
        state.imgNumber = 0
        state.annotations = [[]]
        state.annotationNumber = 0
        state.annotationStart = False

        flash("Upload converted and loaded.", "success")
    except Exception as e:
        logging.error(f"Upload/conversion error: {e}")
        flash("Error during conversion", "error")
    finally:
        try:
            if os.path.exists(saved_tmp):
                os.remove(saved_tmp)
        except Exception:
            pass

    return redirect(url_for('gesture_presentation'))

# Load a folder of images (absolute path) and copy them into IMAGES_FOLDER
@app.route('/upload_folder', methods=['POST'])
def upload_folder():
    folder_path = request.form.get("folder_path")
    if not folder_path:
        flash("No folder provided", "error")
        return redirect(url_for('gesture_presentation'))
    abs_path = os.path.abspath(folder_path)
    if not os.path.isdir(abs_path):
        flash("Invalid folder path", "error")
        return redirect(url_for('gesture_presentation'))

    clear_images_folder()
    copied = []
    for fn in sorted(os.listdir(abs_path)):
        if fn.lower().endswith(('.jpg', '.jpeg', '.png')):
            src = os.path.join(abs_path, fn)
            dst = os.path.join(IMAGES_FOLDER, fn)
            try:
                shutil.copy(src, dst)
                # convert non-jpg to jpg
                if not dst.lower().endswith(('.jpg', '.jpeg')):
                    img = Image.open(dst).convert("RGB")
                    outp = os.path.splitext(dst)[0] + ".jpg"
                    img.save(outp, "JPEG", quality=85)
                    try: os.remove(dst)
                    except: pass
                    dst = outp
                copied.append(dst)
            except Exception as e:
                logging.error(f"Copy error: {e}")

    if not copied:
        flash("No images found in folder", "error")
        return redirect(url_for('gesture_presentation'))

    final_list = canonicalize_and_number_images(IMAGES_FOLDER)
    state.pathImages = final_list
    state.imgNumber = 0
    state.annotations = [[]]
    state.annotationNumber = 0
    state.annotationStart = False
    flash("Folder loaded and slides ready", "success")
    return redirect(url_for('gesture_presentation'))

# Simple slide control endpoints
@app.route('/next_slide')
def next_slide():
    if state.imgNumber < len(state.pathImages) - 1:
        state.imgNumber += 1
    return "OK"

@app.route('/previous_slide')
def previous_slide():
    if state.imgNumber > 0:
        state.imgNumber -= 1
    return "OK"

@app.route('/clear_drawings')
def clear_drawings():
    state.annotations = [[]]
    state.annotationNumber = 0
    return "OK"

# -------------------------
# Auth (basic) - optional
# -------------------------
@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        confirm = request.form.get('confirm_password','')
        if not username or not password:
            flash("Username and password required", "error")
            return render_template('signup.html')
        if password != confirm:
            flash("Passwords do not match", "error")
            return render_template('signup.html')
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hash_password(password)))
                conn.commit()
            flash("Account created. Please sign in.", "success")
            return redirect(url_for('signin'))
        except sqlite3.IntegrityError:
            flash("Username already exists", "error")
    return render_template('signup.html')

@app.route('/signin', methods=['GET','POST'])
def signin():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, username FROM users WHERE username = ? AND password = ?", (username, hash_password(password)))
            row = cur.fetchone()
            if row:
                session['user_id'] = row[0]
                session['username'] = row[1]
                cur.execute("INSERT INTO user_sessions (user_id) VALUES (?)", (row[0],))
                conn.commit()
                flash("Sign in successful", "success")
                return redirect(url_for('gesture_presentation'))
            else:
                flash("Invalid credentials", "error")
    return render_template('signin.html')

@app.route('/signout')
def signout():
    session.clear()
    flash("Signed out", "info")
    return redirect(url_for('signin'))

# Info pages
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/introduction')
def introduction():
    return render_template('introduction.html')

# -------------------------
# App start
# -------------------------
if __name__ == "__main__":
    # set poppler path for pdf2image
    app.config["POPPLER_PATH"] = POPPLER_BIN
    # Ensure DB and folders exist
    init_db()
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(IMAGES_FOLDER, exist_ok=True)
    logging.info("Starting app with LibreOffice conversion enabled.")
    app.run(debug=False, host="0.0.0.0", port=5000)
