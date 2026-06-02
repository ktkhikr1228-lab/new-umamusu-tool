# backend/parse_screenshot.py
import os
import re
import json
import easyocr
from PIL import Image

# ディレクトリ・ファイルパスの確定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RACE_DATA_PATH = os.path.join(BASE_DIR, "race_data.json")

def load_race_data() -> dict:
    if not os.path.exists(RACE_DATA_PATH):
        return {}
    with open(RACE_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_race_data(data: dict):
    with open(RACE_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def execute_autonomous_ocr_patch(image_name: str):
    """
    開発者環境のローカルにあるスクショ画像をパースし、
    レース条件・アクティブ脚質を自動判別して重要度別に race_data.json を更新する。
    """
    image_path = os.path.join(BASE_DIR, image_name)
    if not os.path.exists(image_path):
        print(f"【Error】指定されたスクショファイルが見つかりません: {image_path}")
        return

    print(f"EasyOCRインスタンスを起動中... 対象ファイル: {image_name}")
    ocr_reader = easyocr.Reader(['ja', 'en'], gpu=False)
    
    # 解析実行
    ocr_results = ocr_reader.readtext(image_path)
    ocr_results.sort(key=lambda x: x[0][0][1]) # Y座標順にソート

    image_instance = Image.open(image_path).convert("RGB")
    
    detected_race = "未知のレース条件"
    active_strategy = "先行"
    
    system_noise = ["トレーナーガイド", "獲得おすすめスキル", "閉じる", "対象レース一覧", "解除", "コース詳細", "出走人数", "9人", "EX", "CLASSIC"]
    strategies = ["逃げ", "先行", "差し", "追込"]
    
    # 1. レース条件マッチ
    race_pattern = re.compile(r"(東京|中山|京都|阪神|新潟|中京|小倉|函館|札幌|福島|大井|ロンシャン).*(芝|ダート).*\d+m")
    for _, text, _ in ocr_results:
        match = race_pattern.search(text)
        if match:
            detected_race = text.split("(")[0].strip()
            print(f"-> 【検出成功】レース条件: {detected_race}")
            break

    # 2. アクティブ脚質判定 (Color Sampling)
    for bbox, text, _ in ocr_results:
        cleaned_text = text.strip()
        if cleaned_text in strategies:
            x_center = int((bbox[0][0] + bbox[2][0]) / 2)
            y_bottom_offset = int(bbox[2][1] + 5)
            
            if 0 <= x_center < image_instance.width and 0 <= y_bottom_offset < image_instance.height:
                r, g, b = image_instance.getpixel((x_center, y_bottom_offset))
                if g > r + 35 and g > b + 35 and g > 130: # 緑色判定
                    active_strategy = cleaned_text
                    print(f"-> 【検出成功】アクティブ脚質: {active_strategy}")

    # 3. 階層分類の抽出
    skills_super = []
    skills_normal = []
    current_tier = "super"
    
    for bbox, text, confidence in ocr_results:
        cleaned = text.strip().replace(" ", "")
        if confidence < 0.35 or len(cleaned) < 2 or cleaned in system_noise or cleaned in strategies:
            continue
        if "超おすすめ" in cleaned:
            current_tier = "super"
            continue
        elif "おすすめ" in cleaned:
            current_tier = "normal"
            continue
        if race_pattern.search(cleaned):
            continue
            
        if current_tier == "super":
            skills_super.append(cleaned)
        else:
            skills_normal.append(cleaned)

    # 4. JSONデータのクレンジングと上書きマージ
    race_master = load_race_data()
    
    if detected_race not in race_master:
        race_master[detected_race] = {}
        
    if active_strategy not in race_master[detected_race] or isinstance(race_master[detected_race][active_strategy], list):
        race_master[detected_race][active_strategy] = {"super_recommended": [], "recommended": []}

    # Set型で完全に重複を排除（クレンジング）
    super_set = set(race_master[detected_race][active_strategy].get("super_recommended", []))
    normal_set = set(race_master[detected_race][active_strategy].get("recommended", []))
    
    for s in skills_super: super_set.add(s)
    for n in skills_normal: normal_set.add(n)
    
    race_master[detected_race][active_strategy]["super_recommended"] = list(super_set)
    race_master[detected_race][active_strategy]["recommended"] = list(normal_set)
    
    save_race_data(race_master)
    print(f"★ データのクレンジング及び {RACE_DATA_PATH} への書き込みが完了しました。")
    print(f"   [超おすすめ]: {skills_super}")
    print(f"   [おすすめ]: {skills_normal}")

if __name__ == "__main__":
    # 解析したいスクショのファイル名をここに記述して実行する
    # 例として、backendフォルダに置いた 'image_b4db5a.jpg' を処理する場合:
    execute_autonomous_ocr_patch("26_01sen.jpg")