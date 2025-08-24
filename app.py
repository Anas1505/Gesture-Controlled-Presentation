from flask import Flask, render_template, Response, request, redirect, url_for, session, flash
from cvzone.HandTrackingModule import HandDetector
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime
import cv2
import numpy as np
import os
import sqlite3
import hashlib
import logging

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration
UPLOAD_FOLDER = "uploaded_presentation"
ALLOWED_EXTENSIONS = {"jpg", "png"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Ensure upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Camera and Image Processing Settings
width, height = 1280, 720
ws, hs = 213, 120
gestureThreshold = 300

# Initialize Camera
cap = cv2.VideoCapture(0)
cap.set(3, width)
cap.set(4, height)

# Initialize Hand Detector
detector = HandDetector(detectionCon=0.7, maxHands=1)

# Global State Variables
class PresentationState:
    def __init__(self):
        self.pathImages = []
        self.imgNumber = 0
        self.buttonPressed = False
        self.buttonCounter = 0
        self.buttonCooldown = 20
        self.annotations = [[]]
        self.annotationNumber = 0
        self.annotationStart = False

state = PresentationState()

# Database Initialization and Management
def init_db():
    with sqlite3.connect('presentation_users.db') as conn:
        cursor = conn.cursor()
        # Users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Sessions table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        conn.commit()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Authentication Decorators
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('signin'))
        return view(*args, **kwargs)
    return wrapped_view

def admin_required(view):
    @wraps(view)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('username') != 'admin':
            flash('Admin access required', 'error')
            return redirect(url_for('signin'))
        return view(*args, **kwargs)
    return decorated_function

# Gesture Processing Functions
def process_hand_gestures(hands):
    if not hands:
        return
    
    hand = hands[0]
    fingers = detector.fingersUp(hand)
    
    if state.buttonCounter >= state.buttonCooldown:
        # Previous Slide (Thumb Up)
        if fingers == [1, 0, 0, 0, 0] and state.imgNumber > 0:
            state.imgNumber -= 1
            state.buttonCounter = 0

        # Next Slide (Pinky Finger)
        if fingers == [0, 0, 0, 0, 1] and state.pathImages and state.imgNumber < len(state.pathImages) - 1:
            state.imgNumber += 1
            state.buttonCounter = 0

    state.buttonCounter += 1

    # Drawing Controls
    if fingers == [0, 1, 0, 0, 0]:  # Index finger up - Start drawing
        x, y = int(hand['lmList'][8][0]), int(hand['lmList'][8][1])
        handle_drawing(x, y)
    
    if fingers == [0, 1, 1, 1, 0]:  # Undo last drawing
        handle_undo()
    
    if fingers == [0, 0, 0, 0, 0]:  # Clear all drawings
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

# Video Processing Functions
def get_current_slide():
    if not state.pathImages:
        return np.zeros((720, 1280, 3), np.uint8)
    
    if state.imgNumber < len(state.pathImages):
        return cv2.imread(state.pathImages[state.imgNumber])
    
    state.imgNumber = max(0, len(state.pathImages) - 1)
    return cv2.imread(state.pathImages[state.imgNumber])

def draw_annotations(imgSlide):
    for i in range(len(state.annotations)):
        if i < len(state.annotations):
            for j in range(len(state.annotations[i])):
                if j != 0:
                    cv2.line(imgSlide, state.annotations[i][j - 1], 
                            state.annotations[i][j], (0, 255, 0), 5)

# Route Handlers
@app.route('/')
@login_required
def index():
    return render_template("gesture_presentation.html", username=session.get('username'))

@app.route('/video_feed')
def video_feed():
    return Response(generate_video(), mimetype='multipart/x-mixed-replace; boundary=frame')

def generate_video():
    while True:
        success, img = cap.read()
        if not success:
            logging.error("Camera not detected!")
            continue

        img = cv2.flip(img, 1)
        imgCurrent = get_current_slide()
        imgSlide = cv2.resize(imgCurrent, (960, 540))
        
        hands, img = detector.findHands(img)
        process_hand_gestures(hands)
        
        draw_annotations(imgSlide)
        
        imgSmall = cv2.resize(img, (ws, hs))
        imgSlide[0:hs, 960-ws:960] = imgSmall

        try:
            _, buffer = cv2.imencode('.jpg', imgSlide)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
        except Exception as e:
            logging.error(f"Error encoding frame: {e}")
            continue

# Authentication Routes
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('signup.html')
        
        try:
            with sqlite3.connect('presentation_users.db') as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                              (username, hash_password(password)))
                conn.commit()
                flash('Account created successfully! Please sign in.', 'success')
                return redirect(url_for('signin'))
        except sqlite3.IntegrityError:
            flash('Username already exists. Please choose another.', 'error')
        
    return render_template('signup.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        with sqlite3.connect('presentation_users.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, username FROM users WHERE username = ? AND password = ?',
                         (username, hash_password(password)))
            user = cursor.fetchone()
            
            if user:
                session['user_id'] = user[0]
                session['username'] = user[1]
                
                # Log the session
                cursor.execute('INSERT INTO user_sessions (user_id) VALUES (?)', (user[0],))
                conn.commit()
                
                flash('Sign in successful!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Invalid username or password', 'error')
        
    return render_template('signin.html')

@app.route('/signout')
def signout():
    session.clear()
    flash('You have been signed out', 'info')
    return redirect(url_for('signin'))

# Admin Routes
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    try:
        with sqlite3.connect('presentation_users.db') as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, username, created_at,
                (SELECT COUNT(*) FROM user_sessions WHERE user_id = users.id) as login_count
                FROM users
                ORDER BY created_at DESC
            ''')
            users = cursor.fetchall()
            
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE created_at > datetime("now", "-24 hours")')
            new_users_24h = cursor.fetchone()[0]
            
            return render_template('admin_dashboard.html', 
                                users=users, 
                                total_users=total_users,
                                new_users_24h=new_users_24h)
    except sqlite3.Error as e:
        flash(f'Database error: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    try:
        with sqlite3.connect('presentation_users.db') as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
            conn.commit()
            flash('User deleted successfully', 'success')
    except sqlite3.Error as e:
        flash(f'Error deleting user: {str(e)}', 'error')
    return redirect(url_for('admin_dashboard'))

# Presentation Control Routes
@app.route('/upload_folder', methods=['POST'])
def upload_folder():
    folder_path = request.form.get("folder_path")
    
    # Convert relative path to absolute path
    abs_folder_path = os.path.abspath(folder_path)
    
    if not folder_path or not os.path.exists(abs_folder_path):
        return "Invalid folder", 400

    # Get all valid image files
    state.pathImages = []
    for img in os.listdir(abs_folder_path):
        if img.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
            full_path = os.path.join(abs_folder_path, img)
            if os.path.isfile(full_path):  # Verify it's a file
                state.pathImages.append(full_path)
    
    state.pathImages = sorted(state.pathImages)
    
    if not state.pathImages:
        return "No images found in folder", 400

    state.imgNumber = 0
    return "OK", 200

@app.route('/next_slide')
def nextSlide():
    if state.imgNumber < len(state.pathImages) - 1:
        state.imgNumber += 1
    return "OK"

@app.route('/previous_slide')
def prevSlide():
    if state.imgNumber > 0:
        state.imgNumber -= 1
    return "OK"

@app.route('/clear_drawings')
def clearDrawings():
    state.annotations = [[]]
    state.annotationNumber = 0
    return "OK"

# Information Routes
@app.route('/about')
def about():
    return render_template("about.html")

@app.route('/introduction')
def introduction():
    return render_template("introduction.html")

# Initialize and Run Application
if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5000)