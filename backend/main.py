# backend/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any
import json
import os

app = FastAPI(title="Uma Musume Deck Builder API - Modular Production Core")

# CORSの許可リストを全開放し、LAN内の別IPからのアクセスを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
RACE_EVENTS_DIR = os.path.join(DATA_DIR, "race_events")
SAVE_FILE_PATH = os.path.join(DATA_DIR, "saved_deck.json")
LEGACY_SAVE_FILE_PATH = os.path.join(BASE_DIR, "saved_deck.json")
CARDS_FILE_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "..", "frontend", "src", "data", "cards.json")
)

os.makedirs(RACE_EVENTS_DIR, exist_ok=True)

class SupportCard(BaseModel):
    id: int
    name: str
    char: str
    card: str
    rarity: str
    type: str
    skills: List[str]
    rare_skills: List[str] = Field(default_factory=list)

def load_deck_from_file() -> List[dict]:
    save_path = SAVE_FILE_PATH if os.path.exists(SAVE_FILE_PATH) else LEGACY_SAVE_FILE_PATH
    if not os.path.exists(save_path):
        return []
    try:
        with open(save_path, "r", encoding="utf-8") as file:
            content = file.read().strip()
            if not content:
                return []
            data = json.loads(content)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []

def save_deck_to_file(deck_data: List[dict]) -> None:
    try:
        with open(SAVE_FILE_PATH, "w", encoding="utf-8") as file:
            json.dump(deck_data, file, ensure_ascii=False, indent=2)
    except IOError as error:
        raise HTTPException(status_code=500, detail=f"Failed to write deck storage: {error}")

def load_cards_from_file() -> List[dict]:
    if not os.path.exists(CARDS_FILE_PATH):
        raise HTTPException(status_code=404, detail="cards.json was not found.")
    try:
        with open(CARDS_FILE_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"Invalid cards.json: {error}")
    except IOError as error:
        raise HTTPException(status_code=500, detail=f"Failed to read cards.json: {error}")

    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="cards.json must contain a JSON array.")
    return data

def load_all_race_events_combined() -> Dict[str, Any]:
    combined_master_data = {}
    if not os.path.exists(RACE_EVENTS_DIR):
        return combined_master_data

    for filename in os.listdir(RACE_EVENTS_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(RACE_EVENTS_DIR, filename)
            race_name_key = os.path.splitext(filename)[0]
            
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    raw_content = file.read().strip()
                    if not raw_content:
                        continue
                        
                    file_content = json.loads(raw_content)
                    
                    for track_name, strategies in file_content.items():
                        display_name = f"{race_name_key} ({track_name})"
                        combined_master_data[display_name] = strategies
            except (json.JSONDecodeError, IOError) as error:
                print(f"Skipping invalid JSON file {filename}: {error}")
                continue
                    
    return combined_master_data

@app.get("/api/deck")
def get_deck():
    return {"deck": load_deck_from_file()}

@app.post("/api/deck")
def save_deck(deck: List[SupportCard]):
    deck_dicts = [
        card.model_dump() if hasattr(card, "model_dump") else card.dict()
        for card in deck
    ]
    save_deck_to_file(deck_dicts)
    return {"status": "success"}

@app.get("/api/cards")
def get_cards():
    return {"cards": load_cards_from_file()}

@app.get("/api/race-data")
def get_race_data():
    return load_all_race_events_combined()

if __name__ == "__main__":
    import uvicorn
    # hostを 127.0.0.1 から 0.0.0.0 に変更し、外部アクセスを許可
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
