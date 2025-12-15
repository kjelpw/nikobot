"""AI Image generation utility"""
import base64
import io
import json
import uuid
from typing import Optional

import requests
from PIL import Image

import config


class ImageGenerator:
    """Generate AI images using configured API"""
    
    def __init__(self):
        self.api_endpoint = getattr(config, 'API_ENDPOINT', '')
        self.login_endpoint = getattr(config, 'LOGIN_ENDPOINT', '')
        self.login_credentials = getattr(config, 'LOGIN_CREDENTIALS', {})
        self.output_dir = 'dream'
        
    def generate_image(self, prompt: str) -> Optional[str]:
        """
        Generate an image from a text prompt
        
        Args:
            prompt: Text description of the image to generate
            
        Returns:
            Path to the generated image file, or None if not configured
        """
        if not self.api_endpoint:
            return None
            
        try:
            # Login if credentials provided
            if self.login_endpoint and self.login_credentials:
                requests.post(self.login_endpoint, self.login_credentials)
            
            # Prepare the request with enhanced prompt
            enhanced_prompt = (
                f"{prompt}, (8k, RAW photo, best quality, masterpiece:1.2), "
                "(intricate details), best quality, hyper detailed, highres, "
                "cinematic lighting, rim light, edge light, reflections, smooth, "
                "sharp focus, depth of field, bokeh, octane render, hyper realistic - "
                "amazing sunlight, Dynamic composition, Bokeh"
            )
            
            form_data = {
                "prompt": enhanced_prompt,
                "steps": 30,
                "negative_prompt": (
                    "(worst quality:2), (low quality:2), (normal quality:2), lowres, "
                    "normal quality, ((monochrome)), child, ((grayscale)), bad anatomy, "
                    "extra fingers, extra legs, extra arms, extra hands, fewer legs, "
                    "fewer arms, fewer fingers, blur, noise, out of focus"
                )
            }
            
            response = requests.post(self.api_endpoint, json=form_data).json()
            
            # Process the response images
            if 'images' in response and response['images']:
                # Take the first image
                image_data = response['images'][0]
                image_bytes = base64.b64decode(image_data.split(",", 1)[0])
                image = Image.open(io.BytesIO(image_bytes))
                
                # Save the image
                import os
                os.makedirs(self.output_dir, exist_ok=True)
                file_name = f"{self.output_dir}/sd_{uuid.uuid4()}.jpg"
                image.save(file_name)
                
                return file_name
            else:
                return None
                
        except Exception as e:
            print(f"Error generating image: {e}")
            return None
