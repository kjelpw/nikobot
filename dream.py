import requests
import uuid

api_endpoint = secrets.api_endpoint

def dream(prompt):
    form = {"prompt":f"{prompt}"}
    r = requests.post(api_endpoint, data=form)
    file_name = f"dream/sd_{uuid.uuid4()}.jpg"
    with open(file_name, 'wb') as f:
        f.write(r.content)

    return file_name