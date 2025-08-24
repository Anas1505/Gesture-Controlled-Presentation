import os
import cv2
from cvzone.HandTrackingModule import HandDetector
import numpy as np

# Variables
width = 1280
height = 720
folderPath = "Resources"
w = 960
h = 540

# Camera Setup
cap = cv2.VideoCapture(0)
cap.set(3, width)
cap.set(4, height)

# Get the list of presentation images
pathImages = sorted(os.listdir(folderPath), key=len)
# print(pathImages)

# Variables
imgNumber = 0
ws, hs = 213, 120
gestureThreshold = 300
buttonPressed = False
buttonCounter = 0
buttonDelay = 20
annotations = [[]]
annotationNumber = 0
annotationStart = False

# Hand Detector
detector = HandDetector(detectionCon=0.7, maxHands=1)

while True:
    # Import Images
    success, img = cap.read()
    img = cv2.flip(img, 1)
    pathFullImage = os.path.join(folderPath, pathImages[imgNumber])
    imgCurrent = cv2.imread(pathFullImage)
    imgSlide = cv2.resize(imgCurrent, (w, h))

    hands, img = detector.findHands(img)
    cv2.line(img, (0, gestureThreshold), (width, gestureThreshold), (0, 255, 255), 5)

    if hands and buttonPressed is False:
        hand = hands[0]
        fingers = detector.fingersUp(hand)
        cx, cy = hand['center']
        lmList = hand['lmList']

        # Constrain values for easier pointer drawing

        xVal = int(np.interp(lmList[8][0], [width // 2, w], [0, width]))
        yVal = int(np.interp(lmList[8][1], [150, height-150], [0, height]))
        indexFinger = xVal, yVal

        if cy <= gestureThreshold: # If hand is at the height of the face
            annotationStart = False
            # Gesture 1 - Left
            if fingers == [1, 0, 0, 0, 0]:
                annotationStart = False
                if imgNumber > 0:
                    buttonPressed = True
                    annotations = [[]]
                    annotationNumber = 0
                    imgNumber -= 1

            # Gesture 2 - Right
            if fingers == [0, 0, 0, 0, 1]:
                annotationStart = False
                if imgNumber < len(pathImages) - 1:
                    buttonPressed = True
                    annotations = [[]]
                    annotationNumber = 0
                    imgNumber += 1

        # Gesture 3 - Show Pointer
        if fingers == [0, 1, 1, 0, 0]:
            cv2.circle(imgSlide, indexFinger, 10, (0, 0, 255), cv2.FILLED)
            annotationStart = False

        # Gesture 4 - Draw Pointer
        if fingers == [0, 1, 0, 0, 0]:
            if annotationStart is False:
                annotationStart = True
                annotationNumber += 1
                annotations.append([])
            cv2.circle(imgSlide, indexFinger, 5, (200, 200, 0), cv2.FILLED)
            annotations[annotationNumber].append(indexFinger)

        else:
            annotationStart = False

        # Gesture 5 - Erase
        if fingers == [0, 1, 1, 1, 0]:
            if annotations:
                if annotationNumber >= 0:
                    annotations.pop(-1)
                    annotationNumber -= 1
                    buttonPressed = True

    else:
        annotationStart = False

    # Button Pressed Iterations
    if buttonPressed:
        buttonCounter += 1
        if buttonCounter > buttonDelay:
            buttonCounter = 0
            buttonPressed = False

    for i in range(len(annotations)):
        for j in range(len(annotations[i])):
            if j != 0:
                cv2.line(imgSlide, annotations[i][j-1], annotations[i][j], (200, 200, 0), 5)

    # Adding a webcam image on the slides
    imgSmall = cv2.resize(img, (ws, hs))
    imgSlide[0:hs, w-ws:w] = imgSmall

    cv2.imshow("Slides", imgSlide)
    cv2.imshow("Image", img)
    key = cv2.waitKey(1)
    if key == ord('q'):
        break
