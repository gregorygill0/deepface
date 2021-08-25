import os
import numpy as np
import cv2
import base64
from pathlib import Path

from deepface.detectors import FaceDetector

import tensorflow as tf

tf_version = tf.__version__
tf_major_version = int(tf_version.split(".")[0])
tf_minor_version = int(tf_version.split(".")[1])

if tf_major_version == 1:
    import keras
    from keras.preprocessing.image import load_img, save_img, img_to_array
    from keras.applications.imagenet_utils import preprocess_input
    from keras.preprocessing import image
elif tf_major_version == 2:
    from tensorflow import keras
    from tensorflow.keras.preprocessing.image import load_img, save_img, img_to_array
    from tensorflow.keras.applications.imagenet_utils import preprocess_input
    from tensorflow.keras.preprocessing import image


# --------------------------------------------------

def initialize_input(img1_path, img2_path=None):
    if type(img1_path) == list:
        bulkProcess = True
        img_list = img1_path.copy()
    else:
        bulkProcess = False

        if (
                (type(img2_path) == str and img2_path != None)  # exact image path, base64 image
                or (isinstance(img2_path, np.ndarray) and img2_path.any())  # numpy array
        ):
            img_list = [[img1_path, img2_path]]
        else:  # analyze function passes just img1_path
            img_list = [img1_path]

    return img_list, bulkProcess


def initialize_folder():
    home = get_deepface_home()

    if not os.path.exists(home + "/.deepface"):
        os.makedirs(home + "/.deepface")
        print("Directory ", home, "/.deepface created")

    if not os.path.exists(home + "/.deepface/weights"):
        os.makedirs(home + "/.deepface/weights")
        print("Directory ", home, "/.deepface/weights created")


def get_deepface_home():
    return str(os.getenv('DEEPFACE_HOME', default=Path.home()))


def loadBase64Img(uri):
    encoded_data = uri.split(',')[1]
    nparr = np.fromstring(base64.b64decode(encoded_data), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    return img


def load_image(img):
    exact_image = False
    if type(img).__module__ == np.__name__:
        exact_image = True

    base64_img = False
    if len(img) > 11 and img[0:11] == "data:image/":
        base64_img = True

    # ---------------------------

    if base64_img == True:
        img = loadBase64Img(img)

    elif exact_image != True:  # image path passed as input
        if os.path.isfile(img) != True:
            raise ValueError("Confirm that ", img, " exists")

        img = cv2.imread(img)

    return img


def detect_faces(img, enforce_detection=True, detector_backend='opencv', align=True):
    # img might be path, base64 or numpy array. Convert it to numpy whatever it is.
    img = load_image(img)

    img_region = [0, 0, img.shape[0], img.shape[1]]

    # ----------------------------------------------
    # people would like to skip detection and alignment if they already have pre-processed images
    if detector_backend == 'skip':
        return [(img, img_region)]

    # ----------------------------------------------
    # Detector stored in a global variable in FaceDetector object.
    # this call should be completed very fast because it will return found in memory
    # it will not build face detector model in each call (consider for loops)
    face_detector = FaceDetector.build_model(detector_backend)

    try:
        faces = FaceDetector.detect_faces(face_detector, detector_backend, img, align)
    except:  # if detected face shape is (0, 0) and alignment cannot be performed, this block will be run
        faces = []

    if len(faces) == 0:
        if not enforce_detection:
            raise ValueError(
                "No face could be detected. Please confirm that the picture is a face photo or consider "
                "to set enforce_detection param to False.")
        else:
            faces = [(img, [0, 0, img.shape[0], img.shape[1]])]  # Set whole image as the detected face

    for img, region in faces:
        if (img.shape[0] == 0 or img.shape[1] == 0) and enforce_detection:
            raise ValueError(f'Detected face shape is {img.shape}, Consider to set enforce_detection argument to False.')

    return faces


def normalize_input(img, normalization='base'):
    # issue 131 declares that some normalization techniques improves the accuracy

    if normalization == 'base':
        return img
    else:
        # @trevorgribble and @davedgd contributed this feature

        img *= 255  # restore input in scale of [0, 255] because it was normalized in scale of  [0, 1] in preprocess_face

        if normalization == 'raw':
            pass  # return just restored pixels

        elif normalization == 'Facenet':
            mean, std = img.mean(), img.std()
            img = (img - mean) / std

        elif (normalization == "Facenet2018"):
            # simply / 127.5 - 1 (similar to facenet 2018 model preprocessing step as @iamrishab posted)
            img /= 127.5
            img -= 1

        elif normalization == 'VGGFace':
            # mean subtraction based on VGGFace1 training data
            img[..., 0] -= 93.5940
            img[..., 1] -= 104.7624
            img[..., 2] -= 129.1863

        elif (normalization == 'VGGFace2'):
            # mean subtraction based on VGGFace2 training data
            img[..., 0] -= 91.4953
            img[..., 1] -= 103.8827
            img[..., 2] -= 131.0912

        elif (normalization == 'ArcFace'):
            # Reference study: The faces are cropped and resized to 112×112,
            # and each pixel (ranged between [0, 255]) in RGB images is normalised
            # by subtracting 127.5 then divided by 128.
            img -= 127.5
            img /= 128

    # -----------------------------

    return img


def preprocess_face(img, target_size=(224, 224), grayscale=False, enforce_detection=True, detector_backend='opencv', align=True):
    # img might be path, base64 or numpy array. Convert it to numpy whatever it is.
    img = load_image(img)
    base_img = img.copy()

    detected_faces = detect_faces(img=img, enforce_detection=enforce_detection, detector_backend=detector_backend, align=align)

    # only take first detected face
    img, region = detected_faces[0]
    if img.shape[0] == 0 or img.shape[1] == 0:
        img = base_img.copy()

    return reshape_face(img, region, target_size, grayscale)


def reshape_face(img, region, target_size=(224, 224), grayscale=False):
    if grayscale == True:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ---------------------------------------------------
    # resize image to expected shape

    # img = cv2.resize(img, target_size) #resize causes transformation on base image, adding black pixels to resize will not deform the base image

    factor_0 = target_size[0] / img.shape[0]
    factor_1 = target_size[1] / img.shape[1]
    factor = min(factor_0, factor_1)

    dsize = (int(img.shape[1] * factor), int(img.shape[0] * factor))
    img = cv2.resize(img, dsize)

    # Then pad the other side to the target size by adding black pixels
    diff_0 = target_size[0] - img.shape[0]
    diff_1 = target_size[1] - img.shape[1]
    if grayscale == False:
        # Put the base image in the middle of the padded image
        img = np.pad(img, ((diff_0 // 2, diff_0 - diff_0 // 2), (diff_1 // 2, diff_1 - diff_1 // 2), (0, 0)),
                     'constant')
    else:
        img = np.pad(img, ((diff_0 // 2, diff_0 - diff_0 // 2), (diff_1 // 2, diff_1 - diff_1 // 2)), 'constant')

    # double check: if target image is not still the same size with target.
    if img.shape[0:2] != target_size:
        img = cv2.resize(img, target_size)

    # ---------------------------------------------------

    # normalizing the image pixels

    img_pixels = image.img_to_array(img)  # what this line doing? must?
    img_pixels = np.expand_dims(img_pixels, axis=0)
    img_pixels /= 255  # normalize input in [0, 1]

    # ---------------------------------------------------

    return img_pixels, region


def find_input_shape(model):
    # face recognition models have different size of inputs
    # my environment returns (None, 224, 224, 3) but some people mentioned that they got [(None, 224, 224, 3)]. I think this is because of version issue.

    input_shape = model.layers[0].input_shape

    if type(input_shape) == list:
        input_shape = input_shape[0][1:3]
    else:
        input_shape = input_shape[1:3]

    # ----------------------
    # issue 289: it seems that tf 2.5 expects you to resize images with (x, y)
    # whereas its older versions expect (y, x)

    if tf_major_version == 2 and tf_minor_version >= 5:
        x = input_shape[0];
        y = input_shape[1]
        input_shape = (y, x)

    # ----------------------

    if type(input_shape) == list:  # issue 197: some people got array here instead of tuple
        input_shape = tuple(input_shape)

    return input_shape
