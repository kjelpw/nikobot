import secrets
from PIL import Image, PngImagePlugin
import requests
import base64
import io
import json
import uuid

def dream(prompt):
    requests.post(secrets.login_endpoint, secrets.login)
    form = {"prompt":f"{prompt}, (8k, RAW photo, best quality, masterpiece:1.2), (intricate details), best quality, hyper detailed, highres, cinematic lighting, rim light, edge light, reflections, smooth, sharp focus, depth of field, bokeh, octane render, hyper realistic - amazing sunlight, Dynamic composition, Bokeh",
            "steps" : 30,
            "negative_prompt": "(worst quality:2), (low quality:2), (normal quality:2), lowres, normal quality, ((monochrome)), child, ((grayscale)), bad anatomy,extra fingers,extra legs,extra arms,extra hands,fewer legs,fewer arms,fewer fingers, blur, noise, out of focus"}
    r = requests.post(secrets.api_endpoint, json=form).json()

    for i in r['images']:
        image = Image.open(io.BytesIO(base64.b64decode(i.split(",",1)[0])))
    
    file_name = f"dream/sd_{uuid.uuid4()}.jpg"
    image.save(file_name)
    return file_name