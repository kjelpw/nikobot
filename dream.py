import secrets
from PIL import Image, PngImagePlugin
import requests
import base64
import io
import json
import uuid
import asyncio
import os, pickle


class Style:
    def __init__(self, name, pos_prompt, neg_prompt):
        self.name = name
        self.pos_prompt = pos_prompt
        self.neg_prompt = neg_prompt
    

class Style_Library:
    def __init__(self):
        self.library = {}
        self.lock = asyncio.Lock()

    async def add_style_async(self, name, pos_prompt, neg_prompt):
        async with self.lock:
            self.library[name] = Style(name, pos_prompt, neg_prompt)
            save_style_library(self.library)

    async def get_styles_async(self):
        async with self.lock:
            return list(self.library.values())

    def add_style(self, name, pos_prompt, neg_prompt):
        asyncio.run(self.add_style_async(name, pos_prompt, neg_prompt))

    def get_styles(self):
        return asyncio.run(self.get_styles_async())

    
def load_style_library():
    # Load the Style_Library object from the pickle file if it exists
    if os.path.exists('style_library.pickle'):
        with open('style_library.pickle', 'rb') as f:
            style_library = pickle.load(f)
    else:
        style_library = Style_Library()
    return style_library

def save_style_library(style_library):
    # Check if the Style_Library object has been modified since the last save
    if os.path.exists('style_library.pickle'):
        file_mod_time = os.path.getmtime('style_library.pickle')
        obj_mod_time = os.path.getmtime(__file__)
        if obj_mod_time < file_mod_time:
            # Object has not been modified since last save
            return
    
    # Serialize the Style_Library object to the pickle file
    with open('style_library.pickle', 'wb') as f:
        pickle.dump(style_library, f)
    



def dream(prompt):
    requests.post(secrets.login_endpoint, secrets.login)
    # Parse the request, if "neg" in the text, then add negative prompt
    pos_prompt = ""
    neg_prompt = ""

    # Check if the prompt includes a style name
    if "style:" in prompt:
        style_library = load_style_library()

        # Extract the style name
        style_name_start = prompt.index("style:") + len("style:")
        style_name_end = prompt.index(",", style_name_start) if "," in prompt[style_name_start:] else len(prompt)
        style_name = prompt[style_name_start:style_name_end].strip()
        
        # Lookup the style in the library, if it exists
        style = style_library.library[style_name]
        if style is not None:
            # Update the prompt with the style's positive prompt
            if style.pos_prompt:
                pos_prompt = f"{style.pos_prompt}"
            # Update the prompt with the style's negative prompt
            if style.neg_prompt:
                neg_prompt = style.neg_prompt
        
        prompt = prompt[:style_name_start]
        
    # Now add the rest of the prompt,
    if "neg:" in prompt:
        neg_prompt = prompt.split("neg:")[-1]
        pos_prompt = prompt.split("neg:")[0]
    else:
        pos_prompt = prompt
   
    form = {"prompt":f"{pos_prompt}",
            "steps" : 25,
            "negative_prompt": f"{neg_prompt}"}
    r = requests.post(secrets.api_endpoint, json=form).json()

    for i in r['images']:
        image = Image.open(io.BytesIO(base64.b64decode(i.split(",",1)[0])))
    
    file_name = f"dream/sd_{uuid.uuid4()}.jpg"
    image.save(file_name)
    return file_name