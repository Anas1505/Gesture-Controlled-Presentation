# Gesture Controlled Presentation using OpenCV, Python and Mediapipe
  This project is a gesture-controlled presentation application that allows users to navigate through a set of images in a slideshow format using hand gestures recognized by computer vision              techniques. Additionally, it enables users to annotate slides by drawing on them using hand gestures.

### Features
  * **Gesture Recognition:** The application detects hand gestures using computer vision techniques, allowing users to control the presentation with hand movements.
  * **Slide Navigation:** Users can navigate forward and backward through the slides using specific hand gestures.
  * **Slide Annotation:** Hand gestures enable users to draw on slides, facilitating real-time annotation during presentations.
  * **Webcam Integration:** The application integrates the webcam feed onto the presentation slides, providing users with additional visual context.

### Requirements
  * **Python 3.x**: The project is written in Python, so ensure you have a compatible version installed.
  * **OpenCV**: OpenCV is used for image processing and computer vision tasks. You can install it using `pip install opencv-python`.
  * **cvzone**: The `HandTrackingModule` is imported from the `cvzone` library. You can install it using `pip install cvzone`.
  * **Numpy**: Numpy is a fundamental package for numerical computing with Python. Install it using `pip install numpy`.

### Installation
  1. Clone the repository to your local machine: `git clone <repository-url>`
  2. Navigate to the project directory: `cd gesture-controlled-presentation-app`
  3. Install the required dependencies: `pip install -r requirements.txt`

### Usage
  1. Place the images you want to use in the presentation in the `Resources` folder.
  2. Run the `presentation.py` script: `python presentation.py`
  3. The webcam feed will start, and you'll see the presentation window. You can now control the presentation using hand gestures as described below.

### Hand Gestures
  * **Gesture 1** - Left: Extend your index finger while keeping other fingers closed to navigate to the previous slide.
  * **Gesture 2** - Right: Extend your little finger while keeping other fingers closed to navigate to the next slide.
  * **Gesture 3** - Show Pointer: Extend your index and middle fingers while keeping other fingers closed to display a pointer on the slide.
  * **Gesture 4** - Draw Pointer: Extend your index finger while keeping other fingers closed to draw on the slide.
  * **Gesture 5** - Erase: Extend your index, middle, and ring fingers while keeping the thumb and little finger closed to erase the last annotation drawn on the slide.
