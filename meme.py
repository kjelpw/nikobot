#stored username and password
import secrets

caption_url = 'https://api.imgflip.com/caption_image'
template_id = '367801389'

import requests

def make_meme(text):
    obj = {'template_id': template_id, 'username': secrets.username, 'password': secrets.password, 'text0': text, 'text1': ''}
    response = requests.post(caption_url, obj, timeout=30).json()
    if response['success'] is True:
        response = response['data']['url']
    else:
        response = response['error_message']
    return response