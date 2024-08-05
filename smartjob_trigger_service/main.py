import json

from fastapi import FastAPI, Request

app = FastAPI()


@app.get("/")
async def hello():
    return {"message": "Hello World"}


@app.post("/process")
async def process(request: Request):
    body = await request.json()
    print(json.dumps(body, indent=4))
    return {"message": "Processing job"}
