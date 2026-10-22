import sys
from PIL import Image
a, y0, y1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
im = Image.open(a); print(im.size)
out = a.replace(".png", f"_c{y0}.png")
im.crop((0, y0, im.size[0], min(y1, im.size[1]))).save(out); print(out)
