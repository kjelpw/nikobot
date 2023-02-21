import secrets
from PIL import Image, PngImagePlugin
import requests
import base64
import io
import json
import uuid

def dream(prompt):
    requests.post(secrets.login_endpoint, secrets.login)
    form = {"prompt":f"{prompt}"}
    r = requests.post(secrets.api_endpoint, json=form).json()

    for i in r['images']:
        image = Image.open(io.BytesIO(base64.b64decode(i.split(",",1)[0])))
    
    file_name = f"dream/sd_{uuid.uuid4()}.jpg"
    image.save(file_name)
    return file_name