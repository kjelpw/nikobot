#stored username and password
import secrets

caption_url = 'https://api.imgflip.com/caption_image'
template_id = '188611958'

import requests

def make_meme(text):
    obj = {'template_id': template_id, 'username': secrets.username, 'password': secrets.password, 'text0': text, 'text1': ''}
    return requests.post(caption_url, obj)