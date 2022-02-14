#stored username and password
import secrets

caption_url = 'https://api.imgflip.com/caption_image'
template_id_stuff = '367801389'
template_id_aidna = '369320225'

import requests

def make_meme_stuff(text):
    obj = {'template_id': template_id_stuff, 'username': secrets.username, 'password': secrets.password, 'text0': text, 'text1': ''}
    response = requests.post(caption_url, obj, timeout=30).json()
    if response['success'] is True:
        response = response['data']['url']
    else:
        response = response['error_message']
    return response

def make_meme_aidna(text):
    obj = {'template_id': template_id_aidna, 'username': secrets.username, 'password': secrets.password, 'text0': text, 'text1': ''}
    response = requests.post(caption_url, obj, timeout=30).json()
    if response['success'] is True:
        response = response['data']['url']
    else:
        response = response['error_message']
    return response