from PIL import Image
from pathlib import Path

# 入力フォルダ
input_folder = Path("newfruits")

# 出力フォルダ
output_folder = Path("sqfruits")
output_folder.mkdir(exist_ok=True)

# 対応拡張子
extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

for image_path in input_folder.iterdir():
    if image_path.suffix.lower() not in extensions:
        continue

    try:
        with Image.open(image_path) as img:
            width, height = img.size

            # 正方形の一辺（短辺）
            size = min(width, height)

            # 中央部分を切り抜く座標
            left = (width - size) // 2
            top = (height - size) // 2
            right = left + size
            bottom = top + size

            cropped = img.crop((left, top, right, bottom))

            save_path = output_folder / image_path.name
            cropped.save(save_path)

            print(f"完了: {image_path.name}")

    except Exception as e:
        print(f"エラー: {image_path.name} -> {e}")

print("すべての処理が完了しました。")