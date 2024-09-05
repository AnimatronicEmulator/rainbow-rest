import requests

url = "http://127.0.0.1:5000/wx/"

endpoint = "current"

params = {"lat": 39.6459929, "lon": -104.9867769}

data = requests.get(url=url+endpoint, params=params)

print(data.content)