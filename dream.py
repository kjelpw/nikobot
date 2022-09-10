from flask import request
import discord


api_endpoint = "1112house.tplinkdns.com/dream"

def dream(prompt):
    form = request.form
    form['prompt'] = prompt
    r = requests.post(api_endpoint, form)

    return r
