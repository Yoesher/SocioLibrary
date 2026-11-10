"""Generate an original book mark for the Windows executable."""
from pathlib import Path

from PIL import Image, ImageDraw

image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, 248, 248), radius=52, fill="#285c49")
draw.polygon([(55, 68), (121, 80), (121, 195), (55, 181)], fill="#eef3e6")
draw.polygon([(135, 80), (201, 68), (201, 181), (135, 195)], fill="#c9ddbf")
for y in (105, 130, 155):
    draw.line((71, y, 104, y + 6), fill="#6b8d70", width=5)
    draw.line((151, y + 6, 185, y), fill="#638969", width=5)
Path("build").mkdir(exist_ok=True)
image.save("build/desktop.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
